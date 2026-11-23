"""Seconde recette (B4) : limite du jour de l'assistant IA atteinte, aucun bouton IA n'est montré (docs/ai_socket.md §1 :
« No AI button is shown in any of these cases ») ; avant, « Expliquer avec l'IA » restait affiché et le refus
n'apparaissait qu'au clic. Le lendemain (ou une limite relevée), le bouton revient."""
from parametres import ia as IA
from parametres.aides_tests.ia import AvecIA

from django.urls import reverse

from .aides_tests.coherence import FETCH, BasePanneau
from .models import Journal

BOUTON = 'data-ia-expliquer="'


class PlafondAtteintTests(AvecIA, BasePanneau):
    def setUp(self):
        super().setUp()
        self.a = self.historique(260)

    def panneau(self, u):
        self.client.force_login(u)
        return self.client.get(self.url(), **FETCH).json()["html"]

    def fiche(self, u):
        self.client.force_login(u)
        return self.client.get(reverse("collecte:alerte", args=[self.a.pk])).content.decode()

    def test_plus_de_bouton_une_fois_la_limite_du_jour_atteinte(self):
        i = self.allumer(ia_appels_jour=1)
        self.assertIn(BOUTON, self.panneau(self.contrib))
        Journal.ecrire(self.admin, IA.ACTION, i, "expliquer_alerte", "", "factice")  # un appel aujourd'hui : limite atteinte
        self.assertNotIn(BOUTON, self.panneau(self.contrib))
        self.assertNotIn(BOUTON, self.fiche(self.admin))
        self.assertFalse(IA.bouton_visible("traduction"))
        i.ia_appels_jour = 2
        i.save()
        self.assertIn(BOUTON, self.panneau(self.contrib))
