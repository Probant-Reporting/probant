"""Mauvais jetons en boucle : au plus un avertissement par espace et par minute au journal du serveur (avant : une ligne
par requête), la ligne suivante dit combien ont été tus ; jamais le jeton lui-même."""
import json
import logging
from unittest import mock

from django.test import Client

from .aides_tests import BaseMCP

from . import vues as V



class FrequenceDesAvertissementsTests(BaseMCP):
    def setUp(self):
        super().setUp()
        logging.getLogger("serveur_mcp").setLevel(logging.WARNING)  # BaseMCP le met à ERROR (remis à la fin)
        V._refus.clear()
        self.addCleanup(V._refus.clear)

    def envoyer(self, n):
        corps = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        for _ in range(n):
            rep = Client().post("/mcp/", corps, content_type="application/json", HTTP_AUTHORIZATION="Bearer prb_mauvais_jeton")
            self.assertEqual(rep.status_code, 401)

    def test_un_avertissement_par_minute(self):
        with self.assertLogs("serveur_mcp", "WARNING") as l:
            self.envoyer(5)
        self.assertEqual(len(l.output), 1)
        self.assertNotIn("prb_mauvais_jeton", l.output[0])
        V._refus["principal"] = (V._refus["principal"][0] - V.REFUS_INTERVALLE - 1, V._refus["principal"][1])  # une minute après
        with self.assertLogs("serveur_mcp", "WARNING") as l:
            self.envoyer(1)
        self.assertEqual(len(l.output), 1)
        self.assertIn("4 other refusal(s) not logged", l.output[0])

    def test_sans_limite_une_ligne_par_requete(self):
        """Comparaison : sans intervalle (le comportement d'avant), autant de lignes que de requêtes."""
        with mock.patch.object(V, "REFUS_INTERVALLE", 0), self.assertLogs("serveur_mcp", "WARNING") as l:
            self.envoyer(3)
        self.assertEqual(len(l.output), 3)
