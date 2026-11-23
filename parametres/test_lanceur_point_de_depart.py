"""Version tout-en-un : le premier démarrage demande quoi préparer, la démo (réponse par défaut) ou un outil vide
(``portable/launch.py``, ``starting_point``)."""
import importlib.util
import os
import sys
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase


def module():
    """Le lanceur, chargé sans toucher à l'environnement du test (il règle DATA_DIR et le chemin des modules)."""
    chemin = Path(settings.BASE_DIR) / "portable" / "launch.py"
    spec = importlib.util.spec_from_file_location("launch_essai", chemin)
    m = importlib.util.module_from_spec(spec)
    with mock.patch.dict(os.environ), mock.patch.object(sys, "path", list(sys.path)):
        spec.loader.exec_module(m)
    return m


def reponses(*textes):
    it = iter(textes)
    return lambda _question: next(it)


class PointDeDepart(SimpleTestCase):
    def setUp(self):
        self.m = module()
        sortie = mock.patch("builtins.print")
        sortie.start()
        self.addCleanup(sortie.stop)

    def test_entree_seule_donne_la_demo(self):
        self.assertEqual(self.m.starting_point(reponses(""), forced=""), "demo")

    def test_un_donne_la_demo_et_deux_l_outil_vide(self):
        self.assertEqual(self.m.starting_point(reponses("1"), forced=""), "demo")
        self.assertEqual(self.m.starting_point(reponses(" 2 "), forced=""), "empty")

    def test_reponse_inconnue_redemandee_puis_demo(self):
        self.assertEqual(self.m.starting_point(reponses("x", "2"), forced=""), "empty")
        self.assertEqual(self.m.starting_point(reponses("x", "y", "z"), forced=""), "demo")

    def test_sans_clavier_la_demo(self):
        def sans_clavier(_question):
            raise EOFError

        self.assertEqual(self.m.starting_point(sans_clavier, forced=""), "demo")

    def test_variable_repond_a_la_place_de_la_personne(self):
        def interdit(_question):
            raise AssertionError("aucune question ne doit être posée")

        self.assertEqual(self.m.starting_point(interdit, forced="empty"), "empty")
        self.assertEqual(self.m.starting_point(interdit, forced="DEMO"), "demo")
        with mock.patch.dict(os.environ, {"PROBANT_START": "empty"}):
            self.assertEqual(self.m.starting_point(interdit), "empty")

    def test_environnement_du_test_intact(self):
        avant = os.environ.get("DATA_DIR")
        module()
        self.assertEqual(os.environ.get("DATA_DIR"), avant)
