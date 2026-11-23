"""Anglais, langue de base : langue par défaut d'une nouvelle installation et langue de repli
d'un texte absent. Les installations existantes gardent leur langue (le champ est déjà rempli)."""
from django.test import TestCase, override_settings

from . import libelles as LB
from .models import Instance, langue_par_defaut


class LangueParDefautTests(TestCase):
    def test_nouvelle_installation_en_anglais(self):
        Instance.objects.all().delete()
        with override_settings(LANGUE_PAR_DEFAUT="en"):
            self.assertEqual(langue_par_defaut(), "en")
            self.assertEqual(Instance.courante().langue, "en")
        self.assertEqual(Instance.courante().langue_reference, "fr")  # contenus fournis : textes de référence français

    def test_installation_existante_inchangee(self):
        i = Instance.courante()
        i.langue = "fr"
        i.save()
        with override_settings(LANGUE_PAR_DEFAUT="en"):
            self.assertEqual(Instance.courante().langue, "fr")

    def test_reglage_par_variable(self):
        with override_settings(LANGUE_PAR_DEFAUT="es"):
            Instance.objects.all().delete()
            self.assertEqual(Instance.courante().langue, "es")

    def test_repli_en_anglais(self):
        self.assertEqual(LB.REPLI, "en")
        self.assertEqual(LB.candidates("ja")[-1], "en")
