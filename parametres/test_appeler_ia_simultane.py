"""``ia.appeler`` en même temps depuis deux processus : le plafond du jour n'est jamais dépassé (compte relu sous le
verrou de la ligne des paramètres ; sous SQLite, transactions « immediate »). Vrais fils et vraies transactions sous
PostgreSQL ; la base SQLite des tests (en mémoire, cache partagé) répond « table verrouillée » au lieu d'attendre : on y
vérifie que les transactions sont bien « immediate », ce qui sérialise la réservation (une base SQLite sur disque attend
jusqu'à 60 s)."""
import threading
import unittest
import time
from unittest import mock

from django.db import connection, connections
from django.test import TransactionTestCase

from collecte.models import Journal
from parametres import ia as IA
from parametres import ia_invites as INV
from parametres.aides_tests.ia import AvecIA
from parametres.ia_fournisseurs import ErreurIA
from parametres.models import Instance
from referentiel.models import Utilisateur


class PlafondSimultaneTests(AvecIA, TransactionTestCase):
    databases = {"default", "commun"}

    def test_sqlite_transactions_immediate(self):
        if connection.vendor != "sqlite":
            self.skipTest("PostgreSQL : verrou de ligne (test suivant)")
        self.assertEqual(connection.settings_dict["OPTIONS"].get("transaction_mode"), "IMMEDIATE")

    @unittest.skipUnless(connection.vendor == "postgresql", "vrais fils : PostgreSQL (voir l'en-tête)")
    def test_deux_demandes_simultanees_un_seul_appel_permis(self):
        self.allumer(ia_appels_jour=1)
        admin = Utilisateur.objects.create(username="adm", email="adm@exemple.test", role=Utilisateur.Role.ADMIN)
        vrai = IA.appels_aujourdhui

        def lent():  # compte lu, puis une pause : sans verrou, l'autre demande lirait le même compte
            n = vrai()
            time.sleep(0.4)
            return n
        resultats = []

        def demander():
            try:
                IA.appeler(admin, INV.expliquer_alerte({"finding": "x"}), Instance.courante())
                resultats.append("envoye")
            except IA.Refus:
                resultats.append("refus")
            except ErreurIA as e:
                resultats.append(e.code)
            finally:
                connections.close_all()
        with mock.patch.object(IA, "appels_aujourdhui", lent):
            fils = [threading.Thread(target=demander) for _ in range(2)]
            for f in fils:
                f.start()
            for f in fils:
                f.join(30)
        self.assertEqual(sorted(resultats), ["envoye", "refus"])
        self.assertEqual(Journal.objects.filter(action=IA.ACTION).count(), 1)
        self.assertEqual(len(self.factice.demandes), 1)
