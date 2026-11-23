"""Historique des connexions : un échec n'est rattaché à la copie du compte dans l'espace que si elle porte le même
e-mail que le registre commun (même comparaison que ``auth.copie_active``). Après la restauration d'une base d'espace où
ce numéro appartient à quelqu'un d'autre, l'échec ne lui est pas attribué : il reste anonyme (empreinte seulement)."""
from django.core.cache import caches
from django.test import Client

from espaces import contexte as E
from espaces.aides_tests import creer
from espaces.essais import EspacesTestCase

from . import historique_connexions as HC
from .models import HistoriqueConnexion, Utilisateur


def lignes(espace):
    with E.activer(espace):
        return list(HistoriqueConnexion.objects.order_by("pk").values_list("utilisateur_id", "resultat", "empreinte"))


class CopieDuCompteTests(EspacesTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.achats = creer("achats@exemple.example", "contributeur", "essai")

    def setUp(self):
        super().setUp()
        caches["connexion"].clear()

    def test_meme_email_rattache(self):
        Client().post("/espace/essai/connexion/", {"username": "achats@exemple.example", "password": "mauvais"})
        self.assertEqual(lignes("essai"), [(self.achats.pk, "echec", HC.empreinte("achats@exemple.example"))])

    def test_numero_d_une_autre_personne_apres_restauration(self):
        with E.activer("essai"):  # base restaurée : ce numéro y porte une autre personne
            Utilisateur._default_manager.filter(pk=self.achats.pk).update(email="autre@exemple.example", username="autre@exemple.example")
        Client().post("/espace/essai/connexion/", {"username": "achats@exemple.example", "password": "mauvais"})
        self.assertEqual(lignes("essai"), [(None, "echec", HC.empreinte("achats@exemple.example"))])

    def test_casse_de_l_email_ignoree(self):
        with E.activer("essai"):
            Utilisateur._default_manager.filter(pk=self.achats.pk).update(email="Achats@exemple.example")
        Client().post("/espace/essai/connexion/", {"username": "achats@exemple.example", "password": "mauvais"})
        self.assertEqual(lignes("essai")[0][0], self.achats.pk)
