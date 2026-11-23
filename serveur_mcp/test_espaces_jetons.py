"""Un espace par jeton : un jeton créé dans un espace n'existe que dans sa base ; à l'adresse d'un autre espace, il est
inconnu (401). Les assistants se permettent espace par espace. Aucune requête vers la base d'un autre espace."""
import json
import logging

from django.test import Client

from espaces import contexte as E
from espaces.aides_tests import creer
from espaces.essais import EspacesTestCase

from . import jetons as JT
from .models import ReglageMCP


class JetonParEspaceTests(EspacesTestCase):
    def setUp(self):
        journal = logging.getLogger("serveur_mcp")  # jetons refusés : au journal du serveur, pas dans la sortie des tests
        self.addCleanup(journal.setLevel, journal.level)
        journal.setLevel(logging.ERROR)
        self.u = creer("deux@exemple.example", "admin")
        creer("deux@exemple.example", "admin", "essai")
        for code in ("principal", "essai"):
            with E.activer(code):
                ReglageMCP.objects.update_or_create(pk=1, defaults={"actif": True})
        with E.activer("principal"):
            self.ici, _ = JT.creer(self.u, "Principal", 7)
        with E.activer("essai"):
            from referentiel.models import Utilisateur

            self.la, _ = JT.creer(Utilisateur.objects.get(pk=self.u.pk), "Essai", 7)

    def statut(self, url, jeton):
        corps = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        return Client(raise_request_exception=True).post(url, corps, content_type="application/json",
                                                         HTTP_AUTHORIZATION=f"Bearer {jeton}").status_code

    def test_un_jeton_ne_sert_que_dans_son_espace(self):
        self.assertEqual(self.statut("/mcp/", self.ici), 200)
        self.assertEqual(self.statut("/espace/essai/mcp/", self.la), 200)
        self.assertEqual(self.statut("/espace/essai/mcp/", self.ici), 401)
        self.assertEqual(self.statut("/mcp/", self.la), 401)

    def appel(self, url, jeton, outil, arguments):
        corps = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": outil, "arguments": arguments}})
        return Client(raise_request_exception=True).post(url, corps, content_type="application/json",
                                                         HTTP_AUTHORIZATION=f"Bearer {jeton}")

    def test_outil_de_lecture_et_d_ecriture_refuses_a_l_adresse_d_un_autre_espace(self):
        """De bout en bout par HTTP, dans les deux sens : un appel d'outil (lecture, écriture) avec le jeton d'un autre
        espace est refusé avant tout (401), et rien n'est écrit dans aucune des deux bases (journal, appels, valeurs)."""
        from collecte.models import Journal, Reponse

        from .models import AppelMCP

        for code in ("principal", "essai"):
            with E.activer(code):
                ReglageMCP.objects.filter(pk=1).update(ecriture=True)
        avant = {}
        for code in ("principal", "essai"):
            with E.activer(code):
                avant[code] = (Journal.objects.count(), AppelMCP.objects.count(), Reponse.objects.count())
        ecriture = {"campaign_id": 1, "kpi_code": "EFF", "organisation_id": 1, "value": "1", "version": ""}
        for url, jeton in (("/espace/essai/mcp/", self.ici), ("/mcp/", self.la)):
            for outil, arguments in (("list_campaigns", {}), ("save_value", ecriture)):
                with self.subTest(url=url, outil=outil):
                    rep = self.appel(url, jeton, outil, arguments)
                    self.assertEqual(rep.status_code, 401)
                    self.assertEqual(rep.json()["error"]["data"]["reason"], "invalid_token")
                    self.assertNotIn("result", rep.json())
        for code in ("principal", "essai"):
            with E.activer(code):
                self.assertEqual((Journal.objects.count(), AppelMCP.objects.count(), Reponse.objects.count()), avant[code])
        # contrôle : le même appel de lecture avec le jeton de l'espace passe
        self.assertEqual(self.appel("/espace/essai/mcp/", self.la, "list_campaigns", {}).status_code, 200)

    def test_permis_espace_par_espace(self):
        with E.activer("essai"):
            ReglageMCP.objects.filter(pk=1).update(actif=False)
        self.assertEqual(self.statut("/espace/essai/mcp/", self.la), 403)
        self.assertEqual(self.statut("/mcp/", self.ici), 200)
