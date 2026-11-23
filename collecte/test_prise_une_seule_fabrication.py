"""Prise d'un gros export (``exports_arriere_plan.prise``) sous PostgreSQL : une seule fabrication à la fois par espace,
même quand deux processus prennent deux tâches DIFFÉRENTES au même instant. Le ``NOT EXISTS`` de la mise à jour ne voit
pas la prise non encore validée de l'autre processus : un verrou consultatif de transaction les fait passer l'une après
l'autre. Un processus tient sa prise dans une transaction ouverte ; l'autre essaie de prendre une autre tâche."""
import threading
import unittest

from django.db import connection, connections, transaction
from django.test import TransactionTestCase

from referentiel.models import Utilisateur

from . import exports_arriere_plan as EAP
from .models import TacheExport

T = TacheExport.Statut


class PriseUneSeuleFabricationTests(TransactionTestCase):
    databases = {"default", "commun"}

    @unittest.skipUnless(connection.vendor == "postgresql", "deux vraies connexions : PostgreSQL")
    def test_deux_taches_differentes_une_seule_prise(self):
        u = Utilisateur.objects.create(username="adm", email="adm@exemple.test", role=Utilisateur.Role.ADMIN)
        t1 = TacheExport.objects.create(utilisateur=u, titre="un")
        t2 = TacheExport.objects.create(utilisateur=u, titre="deux")
        prise_faite, fin = threading.Event(), threading.Event()
        resultat = {}

        def premier():
            try:
                with transaction.atomic():  # prise faite, pas encore validée
                    resultat["premier"] = EAP.prise(t1)
                    prise_faite.set()
                    fin.wait(2)
            finally:
                prise_faite.set()
                connections.close_all()

        fil = threading.Thread(target=premier)
        fil.start()
        self.assertTrue(prise_faite.wait(10))
        minuteur = threading.Timer(1, fin.set)  # le premier valide sa prise une seconde plus tard
        minuteur.start()
        try:
            resultat["second"] = EAP.prise(t2)  # attend la fin de la transaction du premier, puis la voit
        finally:
            fin.set()
            fil.join(30)
            minuteur.cancel()
        self.assertEqual((resultat["premier"], resultat["second"]), (True, False))
        self.assertEqual(sorted(TacheExport.objects.values_list("titre", "statut")), [("deux", T.ATTENTE), ("un", T.EN_COURS)])
