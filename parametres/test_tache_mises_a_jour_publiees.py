"""Tâche « Update from every published version » de ``.github/workflows/tests.yml`` : ce qu'elle appelle existe, elle lit
les étiquettes (historique complet), n'écrit aucun numéro de version et n'a besoin d'aucun secret. Lecture du texte, sans
réseau (comme ``test_workflows_publics``)."""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from .test_workflows_publics import tache, texte

RACINE = Path(settings.BASE_DIR)


class TacheMisesAJourPubliees(SimpleTestCase):

    def setUp(self):
        self.bloc = tache("tests.yml", "update-published")

    def test_deux_bases_et_historique_complet_pour_les_etiquettes(self):
        self.assertIn("name: Update from every published version", self.bloc)
        self.assertRegex(self.bloc, r"database: \[sqlite, postgresql\]")
        self.assertIn("fail-fast: false", self.bloc)
        self.assertIn("fetch-depth: 0", self.bloc)  # sans lui, ni les étiquettes ni l'historique de VERSION
        self.assertIn("image: postgres:16", self.bloc)

    def test_le_script_appele_existe_et_ses_options_aussi(self):
        self.assertIn("python qa/update_from_published.py", self.bloc)
        source = (RACINE / "qa" / "update_from_published.py").read_text(encoding="utf-8")
        commande = self.bloc[self.bloc.index("python qa/update_from_published.py"):]
        options = set(re.findall(r"^\s+(--[a-z-]+)", commande, re.M))
        self.assertTrue(options)
        for option in options:
            self.assertIn(f'"{option}"', source, option)

    def test_aucun_numero_de_version_ni_secret_dans_la_tache(self):
        self.assertIsNone(re.search(r"(?<![\d.])\d+\.\d+\.\d+(?![\d.])", self.bloc), "le contrôle lit les versions dans CHANGELOG.md")
        self.assertNotIn("secrets.", self.bloc)

    def test_la_tache_est_citee_en_tete_du_fichier(self):
        self.assertIn("#   update-published", texte("tests.yml"))
