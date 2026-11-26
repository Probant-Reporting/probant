"""Où tournent les alertes par e-mail : ``check_data --alerts`` (tâche planifiée « cron » d'un hébergement sans tâche de
fond), la fin de ``check_data`` (cron de la nuit), et les boucles ``check_data --schedule`` et ``backup --schedule``
(``alertes.passage_planifie`` : jamais d'erreur qui arrête la boucle). Sans réglage, rien n'est envoyé."""
import io
from unittest import mock

from django.core import mail
from django.core.management import call_command

from espaces.aides_tests import creer
from espaces.essais import EspacesTestCase
from parametres import alertes as AL
from parametres.aides_tests.alertes import DossierAlertes, disque_plein


class CommandeAlertesTests(DossierAlertes, EspacesTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        creer("admin@exemple.example", "admin")

    def test_check_data_alerts_seulement(self):
        sortie = io.StringIO()
        with disque_plein(), mock.patch("collecte.controle_donnees.controler") as controle:
            call_command("check_data", "--alerts", stdout=sortie)
        controle.assert_not_called()  # pas de contrôle des données : seulement les alertes
        self.assertIn("Email alerts: 1 new", sortie.getvalue())
        self.assertEqual([m.to for m in mail.outbox], [["admin@exemple.example"]])

    def test_check_data_de_la_nuit_puis_alertes(self):
        with disque_plein():
            call_command("check_data", "--no-save", stdout=io.StringIO())
        self.assertEqual(len(mail.outbox), 1)

    def test_alertes_eteintes_rien(self):
        AL.enregistrer(None, False, True, "")
        sortie = io.StringIO()
        with disque_plein():
            call_command("check_data", "--alerts", stdout=sortie)
        self.assertEqual((sortie.getvalue(), mail.outbox), ("", []))

    def test_boucle_du_controle_lance_les_alertes(self):
        from django.db import connections

        from collecte import controle_donnees as CD

        class Arret(Exception):
            pass

        with mock.patch.object(CD, "menage_nocturne"), mock.patch.object(CD.ESP, "pour_chaque_espace"), \
                mock.patch.object(connections, "close_all"), mock.patch.object(CD.time, "sleep", side_effect=Arret), \
                mock.patch.object(AL, "passage_planifie") as p, self.assertRaises(Arret):
            CD.planifier("03:30")
        p.assert_called_once_with()
