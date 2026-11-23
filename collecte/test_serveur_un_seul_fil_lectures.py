"""Serveur de test des tests du navigateur (``ServeurDeTestUnSeulFil``) : une lecture de la base faite par le fil des tests
n'a jamais lieu pendant qu'une requête est traitée.

Sous SQLite en mémoire, le serveur de test et le fil des tests partagent la même connexion : une lecture faite pendant un
enregistrement voyait la ligne déjà créée mais pas encore remplie (valeur vide, « à saisir »). Les tests du navigateur
ne pouvaient pas l'éviter en attendant « plus aucune requête en cours » : Chromium déclare abandonné (net::ERR_ABORTED)
l'envoi « keepalive » parti au déchargement de la page, alors que le serveur le reçoit et le traite ensuite."""
import threading
import time
import urllib.request
from unittest import mock

from django.core.handlers.wsgi import WSGIHandler
from django.test import LiveServerTestCase

from .outils_tests import RetourSerialiseIndependantDeLOrdre, ServeurDeTestUnSeulFil, hors_requete


class LectureHorsRequeteTests(ServeurDeTestUnSeulFil, RetourSerialiseIndependantDeLOrdre, LiveServerTestCase):
    serialized_rollback = True

    def test_lecture_attend_la_fin_de_la_requete_en_cours(self):
        commencee, finie = threading.Event(), threading.Event()
        traiter = WSGIHandler.__call__

        def lente(handler, environ, start_response):
            commencee.set()
            time.sleep(0.5)  # enregistrement en cours (ligne créée, pas encore remplie)
            try:
                return traiter(handler, environ, start_response)
            finally:
                finie.set()

        with mock.patch.object(WSGIHandler, "__call__", lente):
            fil = threading.Thread(target=lambda: urllib.request.urlopen(self.live_server_url + "/sante/", timeout=30).read())
            fil.start()
            self.assertTrue(commencee.wait(10))
            with hors_requete():
                self.assertTrue(finie.is_set(), "lecture faite pendant le traitement d'une requête")
            fil.join(30)
