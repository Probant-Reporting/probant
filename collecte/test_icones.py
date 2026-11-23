"""Icônes Lucide : bibliothèque gardée dans collecte/icones/, chaque icône de l'outil y existe,
et le tracé ne dépend d'aucun service extérieur."""
import json
from pathlib import Path

from django.template import Context, Template
from django.test import SimpleTestCase

from .templatetags.collecte import ICONES, icone, trace_icone

DOSSIER = Path(__file__).resolve().parent / "icones"


class IconesTests(SimpleTestCase):
    def test_bibliotheque_et_licence(self):
        info = json.loads((DOSSIER / "lucide-info.json").read_text(encoding="utf-8"))
        self.assertEqual(info["license"]["spdx"], "ISC")
        self.assertGreater(len(json.loads((DOSSIER / "lucide.json").read_text(encoding="utf-8"))["icons"]), 1000)

    def test_toutes_les_icones_de_l_outil_existent(self):
        for nom in ICONES:
            with self.subTest(nom=nom):
                self.assertTrue(trace_icone(nom).startswith("<"))
                self.assertNotIn("http", trace_icone(nom))

    def test_nom_lucide_direct_et_inconnu(self):
        self.assertIn("<", trace_icone("calendar"))
        with self.assertRaises(KeyError):
            trace_icone("icone-qui-n-existe-pas")

    def test_balise(self):
        self.assertIn('class="icone-svg"', icone("coche"))
        self.assertIn('aria-hidden="true"', icone("coche"))
        self.assertNotIn("class=", Template('{% load collecte %}{% icone "rechercher" "" %}').render(Context()))
