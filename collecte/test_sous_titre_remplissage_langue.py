"""Visualisation, visuel « taux de remplissage » : le sous-titre nomme la campagne dans la langue de l'interface (il disait
« Campaign Exercice 2025 » en anglais : le nom français de la campagne, celui des fichiers exportés)."""
from types import SimpleNamespace

from django.test import TestCase

from parametres import langues as L

from .models import Campagne
from .visuels.assemblage import sous_titre


class SousTitreRemplissageLangueTests(TestCase):
    def sous_titre(self, langue):
        contexte = SimpleNamespace(campagne=Campagne(exercice=2025), fixes=[])
        with L.activer_interface(langue):
            return sous_titre({"type": "remplissage"}, contexte, [])

    def test_campagne_nommee_dans_la_langue_de_l_interface(self):
        self.assertEqual(self.sous_titre("en"), "Campaign Reporting year 2025")
        self.assertEqual(self.sous_titre("de"), "Kampagne Berichtsjahr 2025")
        self.assertEqual(self.sous_titre("fr"), "Campagne Exercice 2025")
