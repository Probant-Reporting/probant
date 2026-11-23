"""Changement de mot de passe (Mon compte) : essais limités sur l'ancien mot de passe. Après
``connexion.ESSAIS_MAX`` échecs, le même seuil que la connexion, l'ancien mot de passe n'est plus vérifié pendant
``connexion.DUREE`` (même le bon), avec un message clair ; la session reste ouverte. Le compteur suit la personne (tous
les espaces) ; un bon ancien mot de passe le remet à zéro."""
from django.core.cache import caches
from django.test import Client
from django.utils.html import escape

from espaces import contexte as E
from espaces.aides_tests import MDP, creer
from espaces.essais import EspacesTestCase
from espaces.models import Compte
from parametres.libelles import libelle
from referentiel import connexion as CX
from referentiel.models import Utilisateur

NOUVEAU = "Nouveau-mot-de-passe-2026"


class EssaisAncienMotDePasseTests(EspacesTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.contrib = creer("contrib@exemple.example")
        creer("contrib@exemple.example", "contributeur", "essai")

    def setUp(self):
        super().setUp()
        caches["connexion"].clear()
        self.c = Client()
        self.c.force_login(Utilisateur.objects.get(pk=self.contrib.pk))

    def changer(self, ancien, espace="principal", client=None):
        url = "/mon-compte/" if espace == "principal" else f"/espace/{espace}/mon-compte/"
        return (client or self.c).post(url, {"old_password": ancien, "new_password1": NOUVEAU, "new_password2": NOUVEAU})

    def mot_de_passe_inchange(self):
        from django.contrib.auth.hashers import check_password

        return check_password(MDP, Compte.objects.get(pk=self.contrib.pk).password)

    def test_cinq_echecs_puis_attente_meme_avec_le_bon(self):
        for _ in range(CX.ESSAIS_MAX):
            rep = self.changer("mauvais")
            self.assertContains(rep, escape(libelle("cadre.compte.mdp.erreur_actuel")))
        rep = self.changer(MDP)
        self.assertEqual(rep.status_code, 200)
        self.assertContains(rep, escape(libelle("cadre.compte.mdp.trop_essais")))
        self.assertNotContains(rep, escape(libelle("cadre.compte.mdp.erreur_actuel")))
        self.assertTrue(self.mot_de_passe_inchange())
        self.assertEqual(self.c.get("/mon-compte/").status_code, 200)  # session toujours ouverte
        self.assertEqual(self.c.get("/saisie/").status_code, 200)

    def test_sous_le_seuil_le_bon_passe(self):
        for _ in range(CX.ESSAIS_MAX - 1):
            self.changer("mauvais")
        rep = self.changer(MDP)
        self.assertEqual(rep.status_code, 302)
        self.assertFalse(self.mot_de_passe_inchange())

    def test_bon_ancien_mot_de_passe_remet_a_zero(self):
        for _ in range(CX.ESSAIS_MAX - 1):
            self.changer("mauvais")
        rep = self.c.post("/mon-compte/", {"old_password": MDP, "new_password1": NOUVEAU, "new_password2": "autre"})
        self.assertEqual(rep.status_code, 200)  # confirmation différente : refusé, mais l'ancien était bon
        for _ in range(CX.ESSAIS_MAX - 1):
            self.changer("mauvais")
        self.assertEqual(self.changer(MDP).status_code, 302)

    def test_le_compteur_suit_la_personne_dans_tous_les_espaces(self):
        autre = Client()
        with E.activer("essai"):
            autre.force_login(Utilisateur.objects.get(pk=self.contrib.pk))
        for i in range(CX.ESSAIS_MAX):
            self.changer("mauvais", *(("essai", autre) if i % 2 else ()))
        self.assertContains(self.changer(MDP, "essai", autre), escape(libelle("cadre.compte.mdp.trop_essais")))
        self.assertTrue(self.mot_de_passe_inchange())

    def test_la_connexion_n_est_pas_bloquee(self):
        """Les essais sur l'ancien mot de passe ne bloquent pas la connexion (compteurs distincts)."""
        for _ in range(CX.ESSAIS_MAX + 2):
            self.changer("mauvais")
        rep = Client().post("/connexion/", {"username": "contrib@exemple.example", "password": MDP})
        self.assertEqual(rep.status_code, 302)
