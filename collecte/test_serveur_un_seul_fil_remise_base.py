"""Serveur de test des tests du navigateur (``ServeurDeTestUnSeulFil``) : la base n'est jamais vidée ni rechargée entre
deux tests pendant qu'une requête du test qui finit est encore traitée, ou attend de l'être.

Un test du navigateur peut finir alors que la page a encore des requêtes en vol (sections chargées après coup, envoi
au déchargement) : le navigateur est fermé, mais le serveur de test les a déjà reçues et les traite ensuite. Sous SQLite
en mémoire, le serveur partage la connexion du fil des tests : une requête traitée pendant le rechargement de la base
du test suivant (``deserialize_db_from_string``, dans un bloc atomique) y ouvrait un point de sauvegarde ;
« cannot release savepoint - SQL statements in progress » dans le fil du serveur, puis « An error occurred in the
current transaction » dans la préparation du test suivant (vu une fois sur GitHub, sur
``EditionTests.test_lecteur_vue_partagee_non_modifiable``). Sous PostgreSQL, une telle requête écrivait dans la base
vidée ou dans celle du test suivant.

Chaque test lance deux requêtes lentes puis finit aussitôt, la première en cours de traitement, la seconde en attente
derrière elle (le serveur n'a qu'un fil). Au début du test suivant, on vérifie que le vidage (``flush``) et le
rechargement de la base ont attendu la fin des deux."""
import http.client
import threading
import time
from unittest import mock
from urllib.parse import urlsplit

from django.core.handlers.wsgi import WSGIHandler
from django.core.management.commands.flush import Command as Vidage
from django.db.backends.base.creation import BaseDatabaseCreation
from django.test import LiveServerTestCase

from .outils_tests import RetourSerialiseIndependantDeLOrdre, ServeurDeTestUnSeulFil

LENTE = "/sante/?lente=1"


class RemiseDeLaBaseApresLesRequetesTests(ServeurDeTestUnSeulFil, RetourSerialiseIndependantDeLOrdre, LiveServerTestCase):
    serialized_rollback = True

    @classmethod
    def setUpClass(cls):
        cls.lancees = 0  # requêtes lentes lancées par les tests
        cls.finies = 0  # requêtes lentes dont le serveur a fini le traitement
        cls.commencee = threading.Event()
        cls.ecarts = []  # (étape de la remise de la base, requêtes lentes pas encore finies à ce moment)
        cls.fils = []
        traiter, vider, recharger = WSGIHandler.__call__, Vidage.handle, BaseDatabaseCreation.deserialize_db_from_string

        def lente(handler, environ, start_response):
            if environ.get("QUERY_STRING") != "lente=1":
                return traiter(handler, environ, start_response)
            cls.commencee.set()
            try:
                time.sleep(0.4)
                return traiter(handler, environ, start_response)
            finally:
                cls.finies += 1

        def noter(etape, fonction):
            def appel(*args, **kwargs):
                cls.ecarts.append((etape, cls.lancees - cls.finies))
                return fonction(*args, **kwargs)
            return appel

        cls._remplacements = [mock.patch.object(WSGIHandler, "__call__", lente),
                              mock.patch.object(Vidage, "handle", noter("flush", vider)),
                              mock.patch.object(BaseDatabaseCreation, "deserialize_db_from_string", noter("rechargement", recharger))]
        for r in cls._remplacements:
            r.start()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        try:
            super().tearDownClass()
        finally:
            for r in reversed(cls._remplacements):
                r.stop()
            for fil in cls.fils:
                fil.join(30)

    def requete_lente(self):
        adresse = urlsplit(self.live_server_url)

        def envoyer():
            connexion = http.client.HTTPConnection(adresse.hostname, adresse.port, timeout=30)
            try:
                connexion.request("GET", LENTE)
                connexion.getresponse().read()
            finally:
                connexion.close()
        fil = threading.Thread(target=envoyer, daemon=True)
        type(self).lancees += 1
        type(self).fils.append(fil)
        fil.start()
        return fil

    def finir_avec_deux_requetes_en_vol(self):
        type(self).commencee.clear()
        self.requete_lente()
        self.assertTrue(type(self).commencee.wait(10), "la première requête lente n'a pas commencé")
        self.requete_lente()  # en attente derrière la première : le serveur n'a qu'un fil
        time.sleep(0.05)  # reçue par le serveur avant la fin du test

    def verifier_remise_apres_les_requetes(self):
        self.assertEqual([e for e in type(self).ecarts if e[1]], [],
                         "base vidée ou rechargée pendant qu'une requête du test précédent était en vol")

    def test_a_requetes_en_vol_a_la_fin(self):
        self.verifier_remise_apres_les_requetes()
        self.finir_avec_deux_requetes_en_vol()

    def test_b_requetes_en_vol_a_la_fin(self):
        self.verifier_remise_apres_les_requetes()
        self.finir_avec_deux_requetes_en_vol()
