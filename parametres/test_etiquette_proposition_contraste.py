"""Étiquette « à choisir » de la reprise (orange sur orange pâle) : lisible (4,5:1) dans chaque palette fournie, en clair et
en sombre."""
from django.test import SimpleTestCase

from . import couleurs as CO


class EtiquettePropositionContrasteTests(SimpleTestCase):
    def test_orange_texte_sur_orange_pale(self):
        for nom, p in CO.PALETTES.items():
            g = CO.gamme(p["principale"], p["accent"], p["fond"], p["texte"], nom)
            for apparence, gam in (("clair", g), ("sombre", CO.gamme_sombre(g))):
                with self.subTest(palette=nom, apparence=apparence):
                    self.assertGreaterEqual(CO.contraste(gam["orange-texte"], gam["orange-pale"]), 4.5)
