"""Limite des vues personnelles de la Visualisation (Paramètres › Visualisation, 10 par défaut ; règle du projet) :
- restaurer une vue personnelle depuis la corbeille compte comme une création : refusée, avec le message de la création,
  quand son propriétaire a déjà le maximum (« Annuler » du message, Mon compte › Récemment supprimés, page de
  l'administrateur) ; la vue reste dans la corbeille. Une vue partagée ne compte pas ;
- deux créations simultanées ne dépassent pas la limite : le compte est relu sous le verrou de la ligne du propriétaire.
  Vrais fils et vraies transactions sous PostgreSQL ; la base SQLite des tests (en mémoire) répond « table verrouillée »
  au lieu d'attendre : on y vérifie que les transactions sont « immediate », ce qui sérialise les créations (une base
  SQLite sur disque attend jusqu'à 60 s), comme ``parametres/test_appeler_ia_simultane.py``."""
import json
import threading
import time
import unittest
from unittest import mock

from django.db import connection, connections
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from parametres.models import Instance
from referentiel.models import Utilisateur

from . import vues_visu as VV
from .models import VueVisu

MESSAGE = "Vous avez atteint le maximum de 2 vues personnelles. Supprimez-en une ou demandez à l'administrateur."
FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}


def maximum(n):
    Instance.objects.filter(pk=Instance.courante().pk).update(vues_personnelles_max=n)


class RestaurerCommeUneCreationTests(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        self.contrib = Utilisateur.objects.create(username="contrib", email="contrib@exemple.test")
        maximum(2)
        self.supprimee = VueVisu.objects.create(nom="Supprimée", proprietaire=self.contrib)
        self.supprimee.supprimer(self.contrib)
        for i in range(2):
            VueVisu.objects.create(nom=f"Vue {i}", proprietaire=self.contrib)
        self.url = reverse("collecte:corbeille_restaurer", args=["vue", self.supprimee.pk])

    def dans_la_corbeille(self):
        return VueVisu.tous.get(pk=self.supprimee.pk).supprime_le is not None

    def test_annuler_refuse_au_maximum(self):
        self.client.force_login(self.contrib)
        rep = self.client.post(self.url, **FETCH)
        self.assertEqual(rep.status_code, 400)
        self.assertEqual(rep.json()["erreur"], MESSAGE)
        self.assertTrue(self.dans_la_corbeille())
        self.assertEqual(VueVisu.objects.filter(proprietaire=self.contrib, partage=False).count(), 2)

    def test_recemment_supprimes_refuse_au_maximum(self):
        self.client.force_login(self.contrib)
        rep = self.client.post(self.url, {"rester": "1", "suivant": "/mon-compte/"}, follow=True)
        self.assertRedirects(rep, "/mon-compte/")
        self.assertContains(rep, "Vous avez atteint le maximum de 2 vues personnelles")  # première phrase, en gras
        self.assertTrue(self.dans_la_corbeille())

    def test_administrateur_restaure_pour_le_proprietaire(self):
        self.client.force_login(self.admin)  # l'admin n'a aucune vue : c'est le compte du propriétaire qui compte
        rep = self.client.post(self.url, **FETCH)
        self.assertEqual((rep.status_code, rep.json()["erreur"]), (400, MESSAGE))
        self.assertTrue(self.dans_la_corbeille())

    def test_sous_le_maximum_restauree(self):
        VueVisu.objects.filter(nom="Vue 0").delete()
        self.client.force_login(self.contrib)
        rep = self.client.post(self.url, **FETCH)
        self.assertEqual(rep.status_code, 200)
        self.assertFalse(self.dans_la_corbeille())

    def test_vue_partagee_hors_compte(self):
        partagee = VueVisu.objects.create(nom="Comité", proprietaire=self.admin, partage=True)
        for i in range(2):
            VueVisu.objects.create(nom=f"Perso admin {i}", proprietaire=self.admin)
        partagee.supprimer(self.admin)
        self.client.force_login(self.admin)
        rep = self.client.post(reverse("collecte:corbeille_restaurer", args=["vue", partagee.pk]), **FETCH)
        self.assertEqual(rep.status_code, 200)
        self.assertIsNone(VueVisu.tous.get(pk=partagee.pk).supprime_le)


class CreationsSimultaneesTests(TransactionTestCase):
    databases = {"default", "commun"}

    def test_sqlite_transactions_immediate(self):
        if connection.vendor != "sqlite":
            self.skipTest("PostgreSQL : verrou de ligne (test suivant)")
        self.assertEqual(connection.settings_dict["OPTIONS"].get("transaction_mode"), "IMMEDIATE")

    @unittest.skipUnless(connection.vendor == "postgresql", "vrais fils : PostgreSQL (voir l'en-tête)")
    def test_deux_creations_simultanees_ne_depassent_pas(self):
        contrib = Utilisateur.objects.create(username="contrib", email="contrib@exemple.test")
        maximum(2)
        VueVisu.objects.create(nom="Existante", proprietaire=contrib)
        vrai = VV.limite_vues

        def lent(utilisateur):  # compte lu, puis une pause : sans verrou, l'autre création lirait le même compte
            r = vrai(utilisateur)
            time.sleep(0.4)
            return r
        statuts = []

        def creer(i):
            try:
                c = Client()
                c.force_login(contrib)
                rep = c.post(reverse("collecte:visu_vue_creer"), json.dumps({"nom": f"Vue {i}", "visuels": []}),
                             content_type="application/json")
                statuts.append(rep.status_code)
            finally:
                connections.close_all()
        with mock.patch.object(VV, "limite_vues", lent):
            fils = [threading.Thread(target=creer, args=(i,)) for i in range(2)]
            for f in fils:
                f.start()
            for f in fils:
                f.join(30)
        self.assertEqual(sorted(statuts), [201, 400])
        self.assertEqual(VueVisu.objects.filter(proprietaire=contrib, partage=False).count(), 2)
