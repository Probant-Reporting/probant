"""Administration › Preuves à supprimer sans durée réglée : un seul titre (celui de la page), puis l'état de page vide
(``_vide.html``, centré, bouton sous le texte) et non un bloc vide en ligne dans une carte au même titre."""
from django.urls import reverse

from .test_conservation_preuves import ConservationBase


class PageSansDureeTests(ConservationBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)
        self.html = self.client.get(reverse("collecte:admin_preuves")).content.decode()

    def test_un_seul_titre_de_page(self):
        self.assertEqual(self.html.count("Preuves à supprimer</h2>"), 1)
        self.assertEqual(self.html.count('<h2 id="titre-preuves"'), 0)

    def test_etat_de_page_vide_centre_avec_son_bouton(self):
        self.assertIn('<div class="page-vide">', self.html)  # pas « page-vide compact » : le bouton passe sous le texte
        self.assertNotIn("page-vide compact", self.html)
        self.assertIn("Régler la durée", self.html)
