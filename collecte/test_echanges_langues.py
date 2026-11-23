"""Zone « suivi » en trois langues : fichiers Excel et CSV produits dans la langue choisie (français, anglais, espagnol),
et en-têtes reconnus à la relecture quelle que soit la langue du fichier ; phrase de l'export et relances dans la langue de
l'interface."""
import datetime
import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from openpyxl import load_workbook

from parametres import langues as L
from parametres.models import Langue
from referentiel.models import KPI, Niveau, Organisation, Utilisateur

from . import exports as E
from . import fichiers as X
from . import imports as I
from . import saisie as S
from .models import Campagne
from .outils_tests import xlsx

LANGUES = ("fr", "en", "es")


class LanguesFichiersTests(TestCase):
    def setUp(self):
        Langue.objects.create(code="es", libelle="Español", ordre=3)
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.g)
        self.c = Campagne.objects.create(exercice=2026, statut=Campagne.Statut.OUVERTE,
                                         date_fin_saisie=timezone.localdate() + datetime.timedelta(days=30))
        self.eff = KPI.objects.create(code="EFF", libelle="Effectif", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                                      methode_agregation="Somme")
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        S.enregistrer(self.admin, self.c, self.eff, self.e1, "12", False, "")

    def test_langue_du_fichier(self):
        self.assertEqual([X.langue_fichier(c) for c in ("fr", "en", "es", "", "ja", "ja-JP")], ["fr", "en", "es", "fr", "en", "en"])
        self.assertEqual(X.t("es", "suivi.fichier.a_lire"), "Léame")
        self.assertEqual(X.t("ja", "suivi.fichier.a_lire"), "Read me")  # sans fichiers de langue : l'anglais, comme avant
        self.assertIn("Léame", X.tous_les_textes("suivi.fichier.a_lire"))

    def test_entetes_d_import_reconnus_dans_toutes_les_langues(self):
        for langue in LANGUES:
            titres = [X.t(langue, f"suivi.remplir.colonne.{c}") for c in ("kpi", "organisation", "periode", "valeur")]
            with self.subTest(langue=langue):
                a = I.analyser(self.admin, xlsx([titres, ["EFF", "E1", "2026", "15"]]))
                self.assertEqual(a.erreur, "")
                self.assertEqual([(l.kpi_id, l.action) for l in a.lignes], [("EFF", "modifier")])

    def test_na_oui_en_espagnol(self):
        a = I.analyser(self.admin, xlsx([["ID KPI", "Organización", "Periodo", "Valor", "N/A"], ["EFF", "E1", "2026", "", "Sí"]]))
        self.assertEqual(a.erreur, "")
        self.assertTrue(a.lignes[0].na)

    def test_export_base_relu_dans_chaque_langue(self):
        for langue in LANGUES:
            p = E.Parametres.depuis({"presentation": "base", "langue": langue})
            rep = E.exporter(self.admin, p)
            wb = load_workbook(io.BytesIO(rep.content))
            with self.subTest(langue=langue):
                self.assertEqual(wb.sheetnames[0], X.t(langue, "suivi.fichier.a_lire"))
                a = I.analyser(self.admin, SimpleUploadedFile("export.xlsx", rep.content))
                self.assertEqual(a.erreur, "")
                # la saisie de E1 est inchangée ; le total agrégé du groupe est ignoré (recalculé)
                self.assertEqual(sorted((l.kpi_id, l.org.nom, l.action) for l in a.lignes), [("EFF", "E1", "inchange"), ("EFF", "Groupe", "ignore")])

    def test_export_csv_en_espagnol(self):
        p = E.Parametres.depuis({"presentation": "base", "langue": "es", "format": "csv"})
        texte = E.exporter(self.admin, p).content.decode("utf-8-sig")
        self.assertTrue(texte.startswith("Ejercicio;Periodo;Inicio del periodo;ID KPI;Indicador;"))
        a = I.analyser(self.admin, SimpleUploadedFile("export.csv", texte.encode("utf-8")))
        self.assertEqual(sorted((l.org.nom, l.action) for l in a.lignes), [("E1", "inchange"), ("Groupe", "ignore")])

    def test_fichier_a_remplir_dans_chaque_langue_puis_relu(self):
        for langue in LANGUES:
            lignes = I.lignes_modele(self.admin, self.c)
            rep = I.modele(self.admin, self.c, lignes, "xlsx", langue=langue)
            wb = load_workbook(io.BytesIO(rep.content))
            with self.subTest(langue=langue):
                self.assertEqual(wb.sheetnames, [X.t(langue, "suivi.fichier.a_lire"), X.t(langue, "suivi.remplir.onglet_saisie"),
                                                 X.t(langue, "suivi.remplir.onglet_definitions")])
                ws = wb.worksheets[1]
                entete = next(r for r in range(1, 12) if ws.cell(r, 2).value == X.t(langue, "suivi.remplir.colonne.kpi"))
                col = next(c for c in range(1, 20) if ws.cell(entete, c).value == X.t(langue, "suivi.remplir.colonne.valeur"))
                ws.cell(entete + 1, col).value = 30
                flux = io.BytesIO()
                wb.save(flux)
                a = I.analyser(self.admin, SimpleUploadedFile("rempli.xlsx", flux.getvalue()))
                self.assertEqual(a.erreur, "")
                self.assertEqual([(l.kpi_id, l.action, str(l.valeur)) for l in a.lignes], [("EFF", "modifier", "30.0000000000")])

    def test_rapport_des_rejets_en_espagnol(self):
        a = I.analyser(self.admin, xlsx([["ID KPI", "Organisation", "Valeur"], ["XXX", "E1", "1"]]))
        rep = I.fichier_rejets(self.admin, I.lignes_rejetees(a, self.admin), "fichier.xlsx", langue="es")
        wb = load_workbook(io.BytesIO(rep.content))
        self.assertIn("Líneas rechazadas", wb.sheetnames)
        valeurs = [c.value for ws in wb.worksheets for row in ws.iter_rows() for c in row if c.value]
        self.assertTrue(any("Rechazada" == v for v in valeurs))
        # le fichier des rejets se corrige puis se réimporte
        flux = io.BytesIO(rep.content)
        self.assertEqual(I.analyser(self.admin, SimpleUploadedFile("rejets.xlsx", flux.getvalue())).erreur, "")

    def test_entetes_des_fichiers_d_administration(self):
        self.assertEqual(X.entete("Nom (FR)", "es"), "Nombre (FR)")
        self.assertEqual(X.entete("Nom (FR)", "en"), "Name (FR)")
        self.assertEqual(X.entete("Nom (FR)", "fr"), "Nom (FR)")
        # français, anglais, espagnol d'abord, puis l'en-tête de chaque autre langue de l'interface, sans doublon
        acceptes = X.entetes_acceptes("Nom (FR)")
        self.assertEqual(acceptes[:3], ["Nom (FR)", "Name (FR)", "Nombre (FR)"])
        self.assertEqual(len(acceptes), len(set(acceptes)))
        from parametres import libelles as LB

        self.assertEqual(set(acceptes), {X.entete("Nom (FR)", c) for c in LB.langues_disponibles()})
        self.assertEqual((X.nom_onglet("Langues", "es"), X.nom_onglet("Langues", "en"), X.nom_onglet("Langues")), ("Idiomas", "Languages", "Langues"))
        self.assertEqual(X.onglets_en_francais({X.normaliser("Idiomas"): [1]})[X.normaliser("Langues")], [1])

    def test_phrase_et_resume_dans_la_langue_de_l_interface(self):
        p = E.Parametres.depuis({"presentation": "base", "exercices": ["tous"]})
        self.assertEqual(p.phrase().split(" : ")[0], "Base de données Excel")
        with L.activer_interface("en"):
            self.assertTrue(p.phrase().startswith("Database Excel: validated values, drafts and calculated totals, all years"))
            self.assertEqual(p.resume(), "Database · Excel · all years")
        with L.activer_interface("es"):
            self.assertEqual(p.resume(), "Base de datos · Excel · todos los ejercicios")


class InterfaceSansContenusTests(TestCase):
    """Espagnol choisi dans Mon compte alors que ce n'est pas une langue des contenus de l'installation (installation en français et en anglais) : le
    fichier à remplir et le rapport des rejets sont écrits en espagnol (onglets, consignes, en-têtes), comme les exports."""

    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.g)
        self.c = Campagne.objects.create(exercice=2026, statut=Campagne.Statut.OUVERTE,
                                         date_fin_saisie=timezone.localdate() + datetime.timedelta(days=30))
        KPI.objects.create(code="EFF", libelle="Effectif", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                           methode_agregation="Somme")
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN,
                                                langue="es")
        self.client.force_login(self.admin)

    def test_fichier_a_remplir_en_espagnol(self):
        self.assertFalse(Langue.objects.filter(code="es").exists())
        rep = self.client.get(f"/import-export/modele/?campagne={self.c.pk}&choix_kpi=tous&format=xlsx")
        wb = load_workbook(io.BytesIO(rep.content))
        self.assertEqual(wb.sheetnames, ["Léame", "Captura", "Definiciones"])
        self.assertEqual(wb.worksheets[0].cell(1, 1).value, X.t("es", "suivi.remplir.titre"))
        a = I.analyser(self.admin, SimpleUploadedFile("rempli.xlsx", rep.content))
        self.assertEqual(a.erreur, "")
        csv = self.client.get(f"/import-export/modele/?campagne={self.c.pk}&choix_kpi=tous&format=csv")
        self.assertTrue(csv.content.decode("utf-8-sig").startswith("Organización;ID KPI;Indicador;"))

    def test_rapport_des_rejets_en_espagnol(self):
        a = I.analyser(self.admin, xlsx([["ID KPI", "Organisation", "Valeur"], ["XXX", "E1", "1"]]))
        with L.activer_interface("es"):
            rep = I.fichier_rejets(self.admin, I.lignes_rejetees(a, self.admin), "fichier.xlsx")
        self.assertIn("Líneas rechazadas", load_workbook(io.BytesIO(rep.content)).sheetnames)


class ExportAnglaisTests(TestCase):
    """T2 : export en anglais, méthodes d'agrégation traduites."""

    def test_agregations(self):
        from .exports import traduire

        self.assertEqual([traduire(m, "en") for m in ("Somme", "Formule", "Aucune", "Décompte")], ["Sum", "Formula", "None", "Count"])
        self.assertEqual(traduire("Somme", "fr"), "Somme")
