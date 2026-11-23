"""Guides par rôle (sept langues):
- « Mes dernières connexions » (Mon compte, ``cadre.compte.connexions.titre``) est présenté dans le guide de chaque rôle
  qui a Mon compte, validateur et auditeur compris (il manquait dans ces deux guides) ;
- guide de l'administrateur, page Santé : l'administrateur d'un autre espace ne voit pas « l'état de l'installation »
  pour la base de données et la mise à jour de la base, seulement son espace et le registre commun ; le guide le dit."""
from django.test import SimpleTestCase

from parametres.libelles import libelle

from . import aide as AI

ANCIENNE_PHRASE = {
    "en": "sees the status of the installation", "fr": "voit l'état de l'installation",
    "es": "ve el estado de la instalación", "de": "sieht den Zustand der Installation",
    "it": "vede lo stato dell'installazione", "nl": "ziet de status van de installatie",
    "pt": "vê o estado da instalação",
}


class GuidesConnexionsSanteTests(SimpleTestCase):
    def texte(self, guide, langue):
        return AI.chemin_guide(guide, langue).read_text(encoding="utf-8")

    def test_mes_dernieres_connexions_dans_chaque_guide(self):
        for guide in AI.GUIDES:
            for langue in AI.LANGUES_GUIDES:
                with self.subTest(guide=guide, langue=langue):
                    titre = libelle("cadre.compte.connexions.titre", langue=langue)
                    self.assertIn(f"**{titre}**", self.texte(guide, langue))

    def test_sante_autre_espace_base_et_registre(self):
        for langue in AI.LANGUES_GUIDES:
            with self.subTest(langue=langue):
                texte = self.texte("administrator", langue)
                self.assertNotIn(ANCIENNE_PHRASE[langue], texte)
