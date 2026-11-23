"""Aide « ? » : chaque page de l'administrateur (et la Visualisation du contributeur) ouvre sa section du guide, pas le
haut du guide ; l'Historique ne renvoie plus à la suppression des preuves."""
from django.test import TestCase

from referentiel.models import Utilisateur

from . import aide as AI

PAGES_ADMIN = {
    "saisie": "entry", "consolidation": "consolidation", "coherence": "consistency", "regles": "consistency",
    "regle_nouvelle": "consistency", "echanges_importer": "import-values", "export_officiel": "official-formats",
    "echanges_listes_page": "kpi-lists", "visu": "visualisation", "visu_vue": "visualisation", "identite": "settings",
    "niveaux": "settings", "seuils": "settings", "visualisation": "visualisation", "liste": "spaces", "nouveau": "spaces",
    "historique": "history", "admin_journal": "history", "admin_preuves": "evidence-delete",
}


class SectionsDesPagesTests(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create(username="a", email="a@exemple.test", role="admin")
        self.contrib = Utilisateur.objects.create(username="c", email="c@exemple.test", role="contributeur")

    def test_pages_de_l_administrateur(self):
        for nom, section in PAGES_ADMIN.items():
            for langue in AI.LANGUES_GUIDES:
                url = AI.lien_aide(self.admin, nom, langue)
                self.assertTrue(url.endswith(f"#{section}"), (nom, langue, url))

    def test_visualisation_du_contributeur(self):
        for langue in AI.LANGUES_GUIDES:
            self.assertTrue(AI.lien_aide(self.contrib, "visu", langue).endswith("#visualisation"), langue)
