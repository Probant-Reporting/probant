"""Un oui / non tapé à la main accepte le « oui » et le « non » de chaque langue de
l'interface, sans collision entre langues ; une seule fonction (``fichiers.oui_non``) pour l'écran, l'import et le serveur
MCP (tous passent par ``saisie.lire_reponse``)."""
from unittest import mock

from django.core.exceptions import ValidationError
from django.test import TestCase

from collecte import fichiers as X
from collecte import saisie as S
from parametres.models import TypeReponse
from referentiel.models import KPI, Niveau


class OuiNonToutesLanguesTests(TestCase):
    def setUp(self):
        ouinon = TypeReponse.objects.create(code="OuiNonQ26", libelle="Oui / non", format="oui_non")
        self.kpi = KPI.objects.create(code="ON", libelle="Politique", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                                      type_reponse=ouinon)

    def test_oui_et_non_de_chaque_langue(self):
        for mot in ("Oui", "Yes", "Sí", "si", "Ja", "Sì", "Sim", "oui ", "VRAI", "x", "1"):
            with self.subTest(mot=mot):
                self.assertEqual(S.lire_reponse(mot, self.kpi), (None, "Oui"))
        for mot in ("Non", "No", "Nein", "Nee", "Não", "nao", "faux", "0"):
            with self.subTest(mot=mot):
                self.assertEqual(S.lire_reponse(mot, self.kpi), (None, "Non"))

    def test_mot_inconnu_refuse(self):
        for mot in ("peut-être", "na", "N/A", "oui non"):
            with self.subTest(mot=mot), self.assertRaises(ValidationError):
                S.lire_reponse(mot, self.kpi)

    def test_aucun_mot_n_est_a_la_fois_oui_et_non(self):
        langues = ("en", "fr", "es", "de", "it", "nl", "pt")
        self.assertFalse(X._mots_oui_non(langues)[0] & X._mots_oui_non(langues)[1])

    def test_un_mot_des_deux_cotes_est_refuse(self):
        """Une langue (ajoutée plus tard) dont le « non » serait le « oui » d'une autre : le mot est ambigu, refusé."""
        X._mots_oui_non.cache_clear()
        self.addCleanup(X._mots_oui_non.cache_clear)
        vraie = X.table_libelles

        def table(langue):
            t = dict(vraie(langue))
            if langue == "nl":
                t["suivi.export.terme.non"] = "Ja"
            return t

        with mock.patch.object(X, "table_libelles", table):
            self.assertIsNone(X.oui_non("Ja"))
            with self.assertRaises(ValidationError):
                S.lire_reponse("Ja", self.kpi)
            self.assertTrue(X.oui_non("Sim"))
