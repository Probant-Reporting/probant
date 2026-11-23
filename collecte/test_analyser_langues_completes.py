"""Aller-retour des fichiers dans CHAQUE langue complète de l'interface (``libelles.langues_disponibles()``) : un fichier
produit dans une langue est relu sans refus et sans changement (onglets et en-têtes reconnus, mots oui / non, N/A)."""
import io

from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import load_workbook

from parametres import libelles as LB
from parametres.models import Langue

from . import configuration as C
from . import exports as E
from . import fichiers as X
from . import imports as I
from .aides_tests.aller_retour import Base
from .aides_tests.echanges import classeur


class AllerRetourToutesLanguesTests(Base):
    def setUp(self):
        super().setUp()
        for i, code in enumerate(LB.langues_disponibles(), start=1):
            Langue.objects.get_or_create(code=code, defaults={"libelle": code, "ordre": i})

    def test_il_y_a_plus_de_trois_langues(self):
        self.assertGreaterEqual(len(LB.langues_disponibles()), 7)

    def test_fichier_a_remplir_relu_sans_refus_ni_changement(self):
        for langue in LB.langues_disponibles():
            with self.subTest(langue=langue):
                rep = I.modele(self.admin, self.c, I.lignes_modele(self.admin, self.c), "xlsx", langue=langue)
                wb = load_workbook(io.BytesIO(rep.content))
                self.assertEqual(wb.sheetnames[1], X.t(langue, "suivi.remplir.onglet_saisie"))
                a = I.analyser(self.admin, SimpleUploadedFile("rempli.xlsx", rep.content))
                self.assertEqual(a.erreur, "")
                self.assertEqual(len(a.rejets), 0, [(l.kpi_id, l.motif) for l in a.rejets])
                self.assertEqual({l.action for l in a.lignes} - {"inchange", "ignore", "vide"}, set(), langue)

    def test_fichier_a_remplir_na_et_valeur_ecrits_dans_la_langue(self):
        """Dans le fichier à remplir : « Ja » / « Sim »… dans la colonne N/A est un N/A, un nombre est une valeur."""
        for langue in LB.langues_disponibles():
            with self.subTest(langue=langue):
                rep = I.modele(self.admin, self.c, I.lignes_modele(self.admin, self.c), "xlsx", langue=langue)
                wb = load_workbook(io.BytesIO(rep.content))
                ws = wb.worksheets[1]
                entete = next(r for r in range(1, 12) if ws.cell(r, 2).value == X.t(langue, "suivi.remplir.colonne.kpi"))
                col = {k: next(c for c in range(1, 20) if ws.cell(entete, c).value == X.t(langue, f"suivi.remplir.colonne.{k}"))
                       for k in ("valeur", "na", "commentaire")}
                lignes = {ws.cell(r, 2).value: r for r in range(entete + 1, ws.max_row + 1) if ws.cell(r, 2).value}
                ws.cell(lignes["EFF"], col["valeur"]).value = 31
                ws.cell(lignes["TX"], col["na"]).value = X.t(langue, "suivi.export.terme.oui")
                ws.cell(lignes["TX"], col["commentaire"]).value = "Sans objet"
                flux = io.BytesIO()
                wb.save(flux)
                a = I.analyser(self.admin, SimpleUploadedFile("rempli.xlsx", flux.getvalue()))
                self.assertEqual((a.erreur, [(l.kpi_id, l.motif) for l in a.rejets]), ("", []))
                modifiees = {(l.kpi_id, l.org.nom): (l.na, str(l.valeur or "")[:2]) for l in a.lignes if l.action == "modifier"}
                self.assertEqual(modifiees, {("EFF", "E2"): (False, "31"), ("TX", "E2"): (True, "")}, langue)

    def test_export_base_de_donnees_relu_sans_refus_ni_changement(self):
        for langue in LB.langues_disponibles():
            with self.subTest(langue=langue):
                p = E.Parametres.depuis({"presentation": "base", "exercices": ["courant"], "langue": langue})
                rep = E.exporter(self.admin, p)
                a = I.analyser(self.admin, SimpleUploadedFile("base.xlsx", rep.content))
                self.assertEqual(a.erreur, "")
                self.assertEqual(len(a.rejets), 0)
                self.assertEqual(self.actions(a), ["ignore", "inchange"])
                # le N/A (colonne « N/A » : « Ja », « Sim »… selon la langue) est relu comme N/A, pas comme une valeur vide
                na = [l for l in a.lignes if l.kpi_id == "TX" and l.org.nom == "E2"]
                self.assertEqual([(l.na, l.action) for l in na], [(True, "inchange")], langue)
                # le même export en CSV, avec le séparateur de la langue de l'interface
                p = E.Parametres.depuis({"presentation": "base", "exercices": ["courant"], "langue": langue, "format": "csv"})
                a = I.analyser(self.admin, SimpleUploadedFile("base.csv", E.exporter(self.admin, p).content))
                self.assertEqual((a.erreur, len(a.rejets)), ("", 0))
                self.assertEqual(self.actions(a), ["ignore", "inchange"])

    def test_fichier_de_configuration_reimporte_sans_changement(self):
        for langue in LB.langues_disponibles():
            with self.subTest(langue=langue):
                wb = C.classeur(langue=langue)
                flux = io.BytesIO()
                wb.save(flux)
                a, n, campagnes = C.appliquer(self.admin, SimpleUploadedFile("config.xlsx", flux.getvalue()), "config.xlsx")
                self.assertEqual((a.erreur, a.nb_rejets, n, campagnes), ("", 0, 0, []), [str(e) for e in getattr(a, "erreurs", [])])
                self.assertFalse(a.importable)
        self.assertTrue(classeur is not None)
