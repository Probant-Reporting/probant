"""Points d'accès qui attendent un corps JSON, appelés avec un formulaire « multipart » (lot V6, trouvé par ``test_droits_balayage_perimetre``) : le corps a déjà été lu par les gardes (formulaire, jeton CSRF),
``request.body`` n'est plus lisible ; avant, erreur 500 (et une trace au journal du serveur) au lieu d'un refus 400."""
import json

from django.urls import reverse

from serveur_mcp.aides_tests import BaseMCP

from .aides_tests.lecture_seule import Base


class FormulaireAuLieuDeJsonTests(Base):
    def test_visualisation(self):
        self.client.force_login(self.contrib)
        for nom in ("collecte:visu_donnees", "collecte:visu_vue_creer", "collecte:visu_vues_ordre"):
            rep = self.client.post(reverse(nom), {"a": "b"})
            self.assertEqual(rep.status_code, 400, nom)

    def test_glisser_deposer_et_attributions(self):
        self.client.force_login(self.admin)
        for nom in ("collecte:echanges_ordre_modeles", "collecte:attribuer"):
            rep = self.client.post(reverse(nom), {"a": "b"})
            self.assertEqual(rep.status_code, 400, nom)


class FormulaireAuLieuDeJsonMCPTests(BaseMCP):
    def test_point_mcp(self):
        rep = self.mcp.post(self.url_mcp, {"jsonrpc": "2.0"}, HTTP_AUTHORIZATION=f"Bearer {self.jetons['contributeur']}")
        self.assertLess(rep.status_code, 500)
        self.assertEqual(json.loads(rep.content)["error"]["code"], -32700)
