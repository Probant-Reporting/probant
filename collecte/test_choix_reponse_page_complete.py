"""« Je réponds à » ouvert par son adresse (/je-reponds-a/) : page complète (en-tête, styles, viewport), et non le
fragment du panneau de la barre du haut, qui reste rendu pour le script des pages (défaut déjà présent dans ``main``).

Données inventées uniquement."""
from django.urls import reverse

from .aides_tests.echanges import Base


class ChoixReponsePageCompleteTests(Base):
    def test_acces_direct_page_complete(self):
        self.client.force_login(self.contrib)
        page = self.client.get(reverse("collecte:choix_reponse")).content.decode()
        self.assertIn("<html", page)
        self.assertIn('name="viewport"', page)
        self.assertEqual(page.count("<h1"), 1)
        self.assertNotIn("data-fermer-choix", page.split('id="titre-choix-reponse"')[1][:400])

    def test_script_des_pages_recoit_le_fragment(self):
        self.client.force_login(self.contrib)
        frag = self.client.get(reverse("collecte:choix_reponse"), HTTP_X_REQUESTED_WITH="fetch").content.decode()
        self.assertNotIn("<html", frag)
        self.assertIn("data-fermer-choix", frag)
