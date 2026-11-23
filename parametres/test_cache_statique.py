"""Feuille de style : cache long seulement pour l'adresse versionnée courante (?v=), jamais pour les autres."""
from django.test import TestCase

from . import contexte


class CacheStatiqueTests(TestCase):
    def get(self, adresse):
        rep = self.client.get(adresse)
        self.assertEqual(rep.status_code, 200)
        return rep["Cache-Control"]

    def test_adresse_versionnee_courante_gardee_un_an(self):
        cc = self.get(f"/static/css/outil.css?v={contexte.version_css()}")
        self.assertIn("max-age=31536000", cc)
        self.assertIn("immutable", cc)
        cc = self.get(f"/static/js/visualisation.js?v={contexte.version_css('js/visualisation.js')}")
        self.assertIn("immutable", cc)

    def test_sans_version_ou_ancienne_version_cache_court(self):
        for adresse in ("/static/css/outil.css", "/static/css/outil.css?v=1.0.0-0000000000", "/static/css/outil.css?v="):
            cc = self.get(adresse)
            self.assertNotIn("immutable", cc, adresse)
            self.assertNotIn("31536000", cc, adresse)

    def test_la_version_d_un_fichier_ne_vaut_pas_pour_un_autre(self):
        cc = self.get(f"/static/js/visualisation.js?v={contexte.version_css()}")  # empreinte de la feuille de style
        self.assertNotIn("immutable", cc)

    def test_adresse_versionnee_change_avec_le_fichier(self):
        # la garantie de sécurité : l'empreinte suit le contenu (voir aussi parametres.test_identite, test de version_css)
        self.assertNotEqual(contexte.version_css(), contexte.version_css("js/visualisation.js"))
