"""Import de valeurs : un nombre écrit en texte se lit dans la langue du fichier.

La langue des nombres : pour un CSV séparé par « ; » ou « , », ce séparateur (l'outil écrit « ; » avec la virgule
décimale, « , » avec le point, quelle que soit la langue des en-têtes) ; sinon celle de l'en-tête de sa colonne
« Valeur » (« Value », « Valeur », « Wert »… : un fichier exporté par l'outil l'écrit dans la langue de l'export) ;
sinon (assistant de reprise, en-tête qui ne la dit pas) celle de l'interface de la personne. L'aperçu le dit. Un nombre d'Excel ne change jamais. Un texte au séparateur ambigu
(« 1,234 ») reste signalé, avec la lecture faite ; un texte qui n'est pas un nombre dans cette langue est rejeté.
Avant : « 1,234 » était lu 1,234 même dans un fichier anglais, « 0,205.5 » lu 205,5 en silence."""
import tempfile
from decimal import Decimal as D
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from openpyxl import Workbook, load_workbook

from parametres import langues as L

from . import fichiers as X
from . import imports as I
from .templatetags.collecte import separateurs
from .aides_tests.saisie import Base
from .outils_tests import xlsx

LANGUES = ("en", "fr", "es", "de", "it", "nl", "pt")


def csv_(lignes, sep=";"):
    import csv
    import io

    flux = io.StringIO()
    csv.writer(flux, delimiter=sep).writerows(lignes)
    return SimpleUploadedFile("valeurs.csv", flux.getvalue().encode("utf-8"))




class LireNombreImporteTests(SimpleTestCase):
    def test_nombre_d_excel_inchange_dans_toutes_les_langues(self):
        for lg in LANGUES:
            for brut, attendu in ((1234.5, "1234.5"), (1.234, "1.234"), (1234, "1234"), (D("0.205"), "0.205")):
                self.assertEqual(X.lire_nombre_importe(brut, lg), D(attendu), (lg, brut))

    def test_texte_lu_dans_la_langue_du_fichier(self):
        self.assertEqual(X.lire_nombre_importe("1,234", "en"), D(1234))
        self.assertEqual(X.lire_nombre_importe("1,234,567", "en"), D(1234567))
        for lg in LANGUES[1:]:
            self.assertEqual(X.lire_nombre_importe("1,234", lg), D("1.234"), lg)
        for lg in LANGUES:
            for brut, attendu in {"1 234,5": "1234.5", "1,234.5": "1234.5", "1.234,5": "1234.5", "0,205": "0.205",
                                  "12 %": "12", "-3": "-3", "1.234.567": "1234567", "1.5E-05": "0.000015"}.items():
                self.assertEqual(X.lire_nombre_importe(brut, lg), D(attendu), (lg, brut))
            for vide in (None, "", "  ", "%"):
                self.assertIsNone(X.lire_nombre_importe(vide, lg))

    def test_impossible_dans_la_langue_refuse_jamais_lu_autrement(self):
        for lg in LANGUES:
            for brut in ("0,205.5", "0,205,123", "12 kWh", "abc", "1e", True):
                with self.subTest(langue=lg, brut=brut), self.assertRaises(ValueError):
                    X.lire_nombre_importe(brut, lg)


class LangueDesNombresTests(SimpleTestCase):
    def test_d_apres_l_entete_de_la_colonne_valeur(self):
        with L.activer_interface("fr"):
            self.assertEqual(I.langue_des_nombres("Value"), ("en", "entete"))
            self.assertEqual(I.langue_des_nombres("Result"), ("en", "entete"))  # format historique
            self.assertEqual(I.langue_des_nombres("valeur"), ("fr", "entete"))
            self.assertEqual(I.langue_des_nombres("Wert"), ("de", "entete"))
            self.assertEqual(I.langue_des_nombres("Waarde"), ("nl", "entete"))
            self.assertIn(I.langue_des_nombres("Valor"), (("es", "entete"), ("pt", "entete")))  # même décimale
        with L.activer_interface("pt"):
            self.assertEqual(I.langue_des_nombres("Valor"), ("pt", "entete"))  # celle de l'interface quand elle en est

    def test_entete_muet_langue_de_l_interface(self):
        with L.activer_interface("en"):
            self.assertEqual(I.langue_des_nombres(""), ("en", "interface"))

    def test_separateur_du_csv_decide_de_la_decimale(self):
        with L.activer_interface("en"):
            langue, raison = I.langue_des_nombres("Value", ";")  # export anglais en style « ; » : virgule décimale
            self.assertEqual((separateurs(langue)[1], raison), (",", "csv"))
            self.assertEqual(I.langue_des_nombres("Wert", ";"), ("de", "csv"))
            self.assertEqual(I.langue_des_nombres("Valeur", ","), ("en", "csv"))
            self.assertEqual(I.langue_des_nombres("Value", "\t"), ("en", "entete"))


class ImportSuitLaLangueDuFichierTests(Base):
    def ligne(self, analyse, n=0):
        return analyse.lignes[n]

    def test_fichier_anglais_un_virgule_234_vaut_mille(self):
        with L.activer_interface("fr"):
            a = I.analyser(self.admin, xlsx([["KPI ID", "Organization", "Year", "Value"], ["EFF", "E1", 2026, "1,234"]]))
            l = self.ligne(a)
            self.assertEqual((l.action, l.valeur), ("creer", D(1234)))
            self.assertEqual(l.ambigu, "« 1,234 » lu 1 234, pas 1,234 : à vérifier.")
            self.assertEqual(a.ambigus, 1)
            self.assertEqual(a.lectures_nombres, ["Les nombres écrits en texte sont lus comme en anglais (séparateur décimal "
                                                  "« . »), la langue de la colonne « Value »."])

    def test_csv_separe_par_virgules_point_decimal(self):
        with L.activer_interface("fr"):
            a = I.analyser(self.admin, csv_([["ID KPI", "Organisation", "Exercice", "Valeur"], ["EFF", "E1", 2026, "1,234"]],
                                            sep=","))
            self.assertEqual(self.ligne(a).valeur, D(1234))
            self.assertEqual(a.lectures_nombres, ["Les nombres écrits en texte sont lus avec le séparateur décimal « . », celui "
                                                  "d'un fichier CSV dont les colonnes sont séparées par « , » (comme l'écrivent "
                                                  "l'outil et les tableurs)."])

    def test_export_anglais_en_csv_point_virgule_relu_tel_quel(self):
        # l'outil écrit un export anglais en style « ; » avec la virgule décimale : « 12,345 » % reste 12,345 %
        with L.activer_interface("en"):
            a = I.analyser(self.admin, csv_([["KPI ID", "Organisation", "Year", "Value"], ["TX", "E1", 2026, "12,345"]]))
        self.assertEqual((self.ligne(a).action, self.ligne(a).valeur), ("creer", D("0.12345")))

    def test_fichier_francais_un_virgule_234_reste_decimal(self):
        with L.activer_interface("en"):
            a = I.analyser(self.admin, xlsx([["ID KPI", "Organisation", "Exercice", "Valeur"], ["EFF", "E1", 2026, "1,234"]]))
            l = self.ligne(a)
            self.assertEqual(l.valeur, D("1.234"))
            self.assertEqual(l.ambigu, "“1,234” read as 1.234, not 1,234: check it.")

    def test_valeur_impossible_rejetee_avec_message(self):
        a = I.analyser(self.admin, xlsx([["KPI ID", "Organization", "Year", "Value"], ["EFF", "E1", 2026, "0,205.5"]]))
        l = self.ligne(a)
        self.assertEqual((l.action, l.valeur), ("rejet", None))
        self.assertIn("0,205.5", l.motif)

    def test_nombre_d_excel_inchange_et_rien_a_dire(self):
        a = I.analyser(self.admin, xlsx([["KPI ID", "Organization", "Year", "Value"], ["EFF", "E1", 2026, 1.234]]))
        self.assertEqual((self.ligne(a).valeur, self.ligne(a).ambigu, a.lectures_nombres), (D("1.234"), "", []))

    def test_reprise_langue_donnee(self):
        onglets = {"Reprise": [["ID KPI", "Organisation", "Période", "Valeur"], ["EFF", "E1", "2026", "1,234"]]}
        with L.activer_interface("fr"):
            a = I.analyser(self.admin, None, onglets=onglets, langue_nombres="en")
            self.assertEqual(self.ligne(a).valeur, D(1234))
            self.assertEqual(a.lectures_nombres, ["Les nombres écrits en texte sont lus comme en anglais (séparateur décimal "
                                                  "« . »), la langue de votre interface."])

    def test_correction_de_l_apercu_lue_comme_a_l_ecran(self):
        f = csv_([["KPI ID", "Organization", "Year", "Value"], ["EFF", "E1", 2026, "x"]])
        with L.activer_interface("fr"):
            a = I.analyser(self.admin, f, corrections={"CSV|2": {"valeur": "1,234"}})
        self.assertEqual(self.ligne(a).valeur, D("1.234"))

    def test_rapport_des_rejets_relit_la_valeur_dans_la_langue_du_fichier(self):
        a = I.analyser(self.admin, xlsx([["KPI ID", "Organization", "Year", "Value"], ["EFF", "Inconnue", 2026, "1,234"]]))
        self.assertEqual(self.ligne(a).action, "rejet")
        rejets = I.lignes_rejetees(a, self.admin)
        r = I.fichier_rejets(self.admin, rejets, "valeurs.csv", "xlsx", langue="fr")
        with tempfile.TemporaryDirectory() as d:
            chemin = Path(d) / "r.xlsx"
            chemin.write_bytes(r.content)
            wb = load_workbook(chemin, data_only=True)
            valeurs = [c.value for ws in wb.worksheets for ligne in ws.iter_rows() for c in ligne]
        self.assertIn(1234, valeurs)
        self.assertNotIn(1.234, valeurs)

    def test_commande_import_valeurs_entetes_anglais(self):
        from .echange import importer_valeurs
        from .models import Reponse

        wb = Workbook()
        wb.active.append(["ID KPI", "Result", "Organisation", "Year"])
        wb.active.append(["EFF", "1,234", "E1", 2025])
        with tempfile.TemporaryDirectory() as d:
            chemin = Path(d) / "h.xlsx"
            wb.save(chemin)
            rapport = importer_valeurs(str(chemin))
        self.assertEqual(rapport.crees, 1)
        self.assertEqual(Reponse.objects.get(periode=self.c0.periode, kpi=self.eff, organisation=self.e1).valeur, D(1234))
        self.assertIn("ambigu", [t for t, _ in rapport.avertissements])
