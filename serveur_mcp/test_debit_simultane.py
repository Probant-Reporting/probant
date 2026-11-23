"""PostgreSQL : appels et créations de jetons au même instant, relus sous verrou avant d'écrire. Cinq appels simultanés
pour une seule place : un seul passe. Trois créations simultanées pour un seul jeton restant : une seule réussit.
(SQLite : les transactions « immediate » font déjà passer les écritures l'une après l'autre.)"""
import threading

from django.db import connection
from django.test import TransactionTestCase, skipUnlessDBFeature

from referentiel.models import Utilisateur

from . import jetons as JT
from . import journal as J
from .models import AppelMCP, JetonMCP, ReglageMCP


def simultanement(n, action):
    depart = threading.Barrier(n)
    sorties = []

    def fil():
        try:
            depart.wait()
            sorties.append(action())
        except Exception as e:  # noqa: BLE001
            sorties.append(e)
        finally:
            connection.close()

    fils = [threading.Thread(target=fil) for _ in range(n)]
    [f.start() for f in fils]
    [f.join() for f in fils]
    return sorties


@skipUnlessDBFeature("has_select_for_update")
class SimultaneTests(TransactionTestCase):
    def setUp(self):
        self.u = Utilisateur.objects.create(username="simul", email="simul@exemple.test")
        ReglageMCP.objects.update_or_create(pk=1, defaults={"actif": True})

    def test_une_seule_place_un_seul_appel(self):
        _, jeton = JT.creer(self.u, "Essai", 7)
        sorties = simultanement(5, lambda: J.commencer(self.u, jeton, "list_campaigns", 1))
        self.assertEqual(sum(isinstance(s, AppelMCP) for s in sorties), 1, sorties)
        self.assertEqual(sum(isinstance(s, J.Debit) for s in sorties), 4, sorties)
        self.assertEqual(AppelMCP.objects.count(), 1)

    def test_un_seul_jeton_restant_une_seule_creation(self):
        for i in range(JT.JETONS_MAX - 1):
            JT.creer(self.u, f"J{i}", 7)
        sorties = simultanement(3, lambda: JT.creer(self.u, "Dernier", 7))
        self.assertEqual(sum(isinstance(s, tuple) for s in sorties), 1, sorties)
        self.assertEqual(JetonMCP.objects.filter(utilisateur=self.u).count(), JT.JETONS_MAX)
