"""JSON à l'imbrication démesurée (« [[[[…]]]] », 100 Ko) envoyé aux points d'accès JSON (lot V5) : ``json.loads`` lève ``RecursionError`` (pas une ``ValueError``) ; avant, erreur 500 et une trace au journal du
serveur à chaque envoi, y compris par un lecteur (données de la Visualisation) ou par un assistant (point MCP). Le paquet
de configuration le refusait déjà (``bibliotheque_json.depuis_json``)."""
import json

from django.test import SimpleTestCase
from django.urls import reverse

from serveur_mcp.aides_tests import BaseMCP

from . import configuration as CF
from .aides_tests.lecture_seule import Base

PROFOND = "[" * 50_000 + "]" * 50_000


class ImbricationTests(Base):
    def test_visualisation_par_un_lecteur(self):
        self.client.force_login(self.lecteur)
        rep = self.client.post(reverse("collecte:visu_donnees"), PROFOND, content_type="application/json")
        self.assertEqual(rep.status_code, 400)

    def test_glisser_deposer_et_attributions(self):
        self.client.force_login(self.admin)
        for nom in ("collecte:echanges_ordre_modeles", "collecte:attribuer"):
            rep = self.client.post(reverse(nom), PROFOND, content_type="application/json")
            self.assertEqual(rep.status_code, 400, nom)


class ImbricationMCPTests(BaseMCP):
    def test_point_mcp(self):
        rep = self.mcp.post(self.url_mcp, PROFOND, content_type="application/json",
                            HTTP_AUTHORIZATION=f"Bearer {self.jetons['lecteur']}")
        self.assertLess(rep.status_code, 500)
        self.assertEqual(json.loads(rep.content)["error"]["code"], -32700)


class ImbricationConfigurationTests(SimpleTestCase):
    def test_cellule_json_du_fichier_de_configuration(self):
        with self.assertRaises(ValueError):
            CF.depuis_cellule(PROFOND, "json")
