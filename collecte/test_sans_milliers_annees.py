"""Années (unité « année » : GES-ANNEE-REF, GES-ANNEE-CIBLE, GES-PLAN-ANNEE, CLI-SCEN-ANNEE) écrites sans séparateur de
milliers, dans toutes les langues et partout (``nombres.sans_milliers``) : grille de saisie et panneau (``valeur``,
``formater``), Visualisation (``visuels.formes``), formats Excel des exports, du dossier d'audit et du fichier à remplir.
Avant : « 2,028 » en anglais, « 2 028 » en français. Une durée en « années » (ancienneté) garde son séparateur."""
from decimal import Decimal

from django.test import TestCase

from parametres import langues as L
from parametres.models import Unite
from referentiel.models import KPI, Niveau

from . import nombres as N
from .templatetags import collecte as T
from .visuels import formes as VF

LANGUES = ("en", "fr", "es", "de", "it", "nl", "pt")


class Reponse:
    non_applicable = False
    texte = ""

    def __init__(self, v):
        self.valeur = v


class SansMilliersAnneesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        an = Unite.objects.create(code="année", symbole="année", libelle="année", entier=True, decimales=0,
                                  traductions={"en": {"symbole": "year"}})
        duree = Unite.objects.create(code="années", symbole="années", libelle="années", decimales=1)
        cls.annee = KPI.objects.create(code="GES-ANNEE-CIBLE", libelle="Année cible", type_saisie_id="Saisi",
                                       granularite_id=Niveau.GROUP, methode_agregation="Aucune", unite=an)
        cls.duree = KPI.objects.create(code="ANCIENNETE", libelle="Ancienneté", type_saisie_id="Saisi",
                                       granularite_id=Niveau.GROUP, methode_agregation="Aucune", unite=duree)

    def test_unite_annee_reconnue(self):
        self.assertTrue(N.sans_milliers(self.annee))
        self.assertFalse(N.sans_milliers(self.duree))

    def test_grille_panneau_et_visualisation_dans_les_sept_langues(self):
        for lg in LANGUES:
            with self.subTest(langue=lg), L.activer(lg):
                self.assertEqual(T.valeur(Reponse(Decimal(2028)), self.annee, False), "2028")
                self.assertTrue(T.formater(Decimal(2028), self.annee).startswith("2028 "))
                self.assertTrue(VF.formater(Decimal(2028), self.annee).startswith("2028"))
                self.assertNotEqual(T.formater(Decimal(1234), self.duree, False), "1234.0")  # durée : séparateur gardé

    def test_formats_excel(self):
        from . import exports as E
        from .imports_modele import format_nombre_kpi

        self.assertEqual(N.format_excel(0, milliers=False), "0")
        self.assertEqual(E._format_lisible(self.annee), "0")
        self.assertEqual(format_nombre_kpi(self.annee), "0")
        self.assertTrue(E._format_lisible(self.duree).startswith("#,##0."))
