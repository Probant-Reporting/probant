"""Preuves supprimées et sauvegardes déjà faites : une sauvegarde garde le fichier d'une preuve
supprimée jusqu'à sa rotation, et une restauration le remet dans la liste. Le rappel est sur la page Preuves à supprimer
(avec une durée réglée), dans la confirmation de suppression et sur la page Hébergement, dans chaque langue."""
from django.urls import reverse

from parametres.libelles import libelle

from .test_conservation_preuves import ConservationBase


class MessageSauvegardesTests(ConservationBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def test_page_des_preuves_rappelle_les_sauvegardes_avec_une_duree(self):
        self.duree(1)
        self.sensible()
        html = self.client.get(reverse("collecte:admin_preuves")).content.decode()
        self.assertIn('id="note-sauvegardes"', html)
        self.assertIn(libelle("admin.preuves.sauvegardes_note"), html)
        self.assertIn("Une restauration le remet dans cette liste", html)

    def test_page_des_preuves_sans_duree_n_a_pas_de_note(self):
        self.assertNotIn('id="note-sauvegardes"', self.client.get(reverse("collecte:admin_preuves")).content.decode())

    def test_confirmation_de_suppression_dit_que_les_sauvegardes_gardent_le_fichier(self):
        self.duree(1)
        self.sensible()
        html = self.client.get(reverse("collecte:admin_preuves")).content.decode()
        self.assertIn("Les sauvegardes déjà faites le contiennent encore", html.replace("&#x27;", "'"))

    def test_page_hebergement_a_sa_phrase_pres_des_sauvegardes(self):
        html = self.client.get(reverse("parametres:hebergement")).content.decode()
        self.assertIn('id="aide-preuves-sauvegardes"', html)
        self.assertIn(libelle("admin.hebergement.preuves_sauvegardes"), html)

    def test_message_dans_chaque_langue_et_sans_texte_identique_a_l_anglais(self):
        for cle in ("admin.preuves.sauvegardes_note", "admin.hebergement.preuves_sauvegardes"):
            textes = {langue: libelle(cle, langue) for langue in ("en", "fr", "es", "de", "it", "nl", "pt")}
            self.assertEqual(len(set(textes.values())), 7, cle)
            self.assertTrue(all(textes.values()), cle)
