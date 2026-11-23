"""Justification d'une alerte depuis le panneau de saisie (``vues_cellule._justifier``) : un identifiant d'alerte qui
n'est pas écrit en chiffres ASCII est refusé proprement (404), jamais par une erreur 500."""
from django.test import TestCase

from .aides_tests.coherence import FETCH, BasePanneau
from .models import Alerte


class IdentifiantAlerteTests(TestCase):
    setUp = BasePanneau.setUp
    saisir = BasePanneau.saisir
    alertes = BasePanneau.alertes
    url = BasePanneau.url
    historique = BasePanneau.historique

    def test_chiffres_non_ascii_refuses(self):
        a = self.historique()
        self.client.force_login(self.admin)
        # « ² » passe isdigit() mais pas int() ; « ١٢ » (chiffres arabes) ; un nombre trop long pour la base
        for pk in ("²", "١٢", f"{a.pk}²", "9" * 30):
            rep = self.client.post(self.url(), {"action": "justifier", "alerte": pk, "justification": "x"}, **FETCH)
            self.assertEqual(rep.status_code, 404, pk)
        a.refresh_from_db()
        self.assertEqual(a.statut, Alerte.Statut.OUVERTE)
