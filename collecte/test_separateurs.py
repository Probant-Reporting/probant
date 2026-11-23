"""Séparateur ambigu à la saisie d'un nombre : « 1,234 » ou « 12.500 » se lisent milliers ou
décimale. Le panneau de saisie demande laquelle avant d'enregistrer (_app/03_envoi.js, même règle) ; l'aperçu d'un import signale
une cellule texte ambiguë, sans la refuser ; la lecture elle-même ne change pas."""
from decimal import Decimal

from django.test import SimpleTestCase
from django.urls import reverse

from . import imports as I
from .outils_tests import script_des_pages
from .saisie import lectures_ambigues, separateur_ambigu, texte_nombre
from .aides_tests.echanges import Base
from .outils_tests import xlsx


class RegleTests(SimpleTestCase):
    def test_ambigus(self):
        for texte in ("1,234", "12.500", "999,000", "-1,234", "+12.345", " 1.234 "):
            with self.subTest(texte=texte):
                self.assertTrue(separateur_ambigu(texte))

    def test_non_ambigus(self):
        for texte in ("0,125", "1,23", "1,2345", "1234,567", "1 234,5", "1,234.5", "1.234,5", "1.234.567", "1234", "1,5",
                      "01,234", "1,234%", "abc", "", None, 1.234, Decimal("1.234")):
            with self.subTest(texte=texte):
                self.assertFalse(separateur_ambigu(texte))

    def test_deux_lectures_dans_le_format_de_la_langue(self):
        self.assertEqual(lectures_ambigues("1,234", "fr"), ("1 234", "1,234"))
        self.assertEqual(lectures_ambigues("1,234", "en"), ("1,234", "1.234"))
        self.assertEqual(lectures_ambigues("12.500", "es"), ("12.500", "12,500"))
        self.assertEqual(lectures_ambigues("-1.234", "en"), ("-1,234", "-1.234"))
        self.assertIsNone(lectures_ambigues("1,23", "fr"))

    def test_formes_reecrites_par_le_panneau_lues_sans_hesiter(self):
        """Le choix du panneau réécrit la saisie : « 1234 » partout ; la décimale de la langue (« 1,234 » en français et en
        espagnol, « 1.234 » en anglais) est lue avec sa décimale par le serveur (règle de lecture inchangée)."""
        for langue, decimal in (("fr", "1,234"), ("en", "1.234"), ("es", "1,234")):
            with self.subTest(langue=langue):
                self.assertEqual(texte_nombre("1234", langue), "1234")
                self.assertEqual(texte_nombre(decimal, langue), "1.234")

    def test_meme_regle_dans_le_script(self):
        js = script_des_pages()
        self.assertIn(r"const AMBIGU = /^([-+]?)([1-9]\d{0,2})([.,])(\d{3})$/;", js)


class ImportAmbiguTests(Base):
    def test_cellule_texte_ambigue_signalee_sans_refus(self):
        f = xlsx([
            ["ID KPI", "Organisation", "Exercice", "Valeur"],
            ["TX", "E1", 2026, "12,500"],  # texte ambigu : lu 12,5 %, signalé
            ["EFF", "E1", 2026, 1.5],  # nombre d'Excel : jamais ambigu
            ["EFF", "E2", 2026, "1 234,5"],  # deux groupes : pas ambigu
        ])
        a = I.analyser(self.admin, f)
        tx, eff1, eff2 = a.lignes
        self.assertEqual((tx.action, tx.valeur), ("modifier", Decimal("0.125")))
        self.assertEqual(tx.ambigu, "« 12,500 » lu 12,500, pas 12 500 : à vérifier.")
        self.assertEqual((eff1.ambigu, eff2.ambigu), ("", ""))
        self.assertEqual(a.ambigus, 1)

    def test_apercu_affiche_l_avertissement(self):
        self.client.force_login(self.contrib)
        f = xlsx([["ID KPI", "Organisation", "Valeur"], ["TX", "E1", "12,500"]])
        rep = self.client.post(reverse("collecte:echanges_importer"), {"action": "verifier", "fichier": f, "campagne": self.c.pk})
        self.assertContains(rep, "<b>1 valeur</b> a un seul séparateur suivi de 3 chiffres")
        self.assertContains(rep, "« 12,500 » lu 12,500, pas 12 500 : à vérifier.")
        self.assertContains(rep, "Importer 1 ligne")  # avertissement, pas un refus
