"""Saisies « 0,205 », « 1,5 », « 1,234 », « 1.234,5 », « 1 234,5 » relues dans les sept langues de l'interface
(``saisie.texte_nombre``, saisie et serveur MCP) et dans un fichier de configuration (``fichiers.lire_decimal``).

Défaut corrigé : en anglais (décimale « . »), « 0,205 » était lu 205 en silence (virgule prise pour celle des milliers),
alors que la règle des séparateurs dit que « 0,125 » n'est pas ambigu (un nombre ne commence jamais par « 0, » suivi de
milliers) : le panneau ne posait donc aucune question. Un groupe de milliers commence par un chiffre de 1 à 9, comme dans
la règle du séparateur ambigu ; « 0,205,123 » n'est plus lu 205 123 mais refusé (« nombre attendu »)."""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from parametres import langues as L

from . import saisie as S
from .fichiers import lire_decimal

LANGUES = ("en", "fr", "es", "de", "it", "nl", "pt")
# saisie → valeur lue, identique dans les sept langues, sauf « 1,234 » (ambigu : le panneau demande avant d'enregistrer)
ATTENDU = {"0,205": "0.205", "-0,205": "-0.205", "1,5": "1.5", "1.234,5": "1234.5", "1 234,5": "1234.5", "0.205": "0.205"}


class Kpi:
    est_pourcentage = est_entier = False
    symbole = ""
    unite_id = None


class TexteNombreZeroVirguleTests(SimpleTestCase):
    def test_zero_virgule_jamais_lu_en_milliers(self):
        for lg in LANGUES:
            for saisi, lu in ATTENDU.items():
                with self.subTest(langue=lg, saisie=saisi):
                    self.assertEqual(S.texte_nombre(saisi, lg), lu)

    def test_un_virgule_234_suit_la_langue(self):
        """Règle écrite (README, « Numbers ») : en anglais « 1,234 » est mille deux cent trente-quatre ; ailleurs 1,234.
        Le panneau pose la question avant d'enregistrer (séparateur ambigu)."""
        self.assertTrue(S.separateur_ambigu("1,234"))
        self.assertEqual(S.texte_nombre("1,234", "en"), "1234")
        for lg in LANGUES[1:]:
            self.assertEqual(S.texte_nombre("1,234", lg), "1.234")

    def test_groupe_de_milliers_qui_commence_par_zero_refuse(self):
        for lg in LANGUES:
            with self.subTest(langue=lg), L.activer(lg), self.assertRaises(ValidationError):
                S.lire_nombre("0,205,123", Kpi(), bornes=False)

    def test_lire_nombre_en_anglais(self):
        with L.activer("en"):
            self.assertEqual(S.lire_nombre("0,205", Kpi()), Decimal("0.205"))

    def test_import_sans_langue(self):
        """Cellule texte d'un fichier de configuration (``fichiers.lire_decimal``) : lecture indépendante de la langue
        (un séparateur seul est la décimale). L'import de valeurs, lui, suit la langue du fichier
        (``fichiers.lire_nombre_importe``, test_lire_nombre_importe_langue.py)."""
        for saisi, lu in {**ATTENDU, "1,234": "1.234"}.items():
            with self.subTest(saisie=saisi):
                self.assertEqual(lire_decimal(saisi), Decimal(lu))
