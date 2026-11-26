"""Page demandée après la connexion d'entreprise (``next``) : seulement une adresse de l'outil ; une adresse d'un autre
site, sous toutes ses formes, est ignorée (arrivée à l'accueil), au départ comme au retour."""
from .aides_tests import BaseEntreprise

PIEGES = ["https://pirate.example/", "//pirate.example/x", "/\\pirate.example/x", "\\\\pirate.example", "javascript:alert(1)",
          "http://testserver@pirate.example/", "https:pirate.example", " //pirate.example",
          "data:text/html,x"]


class PageSuivanteTests(BaseEntreprise):
    def setUp(self):
        super().setUp()
        self.regler()

    def test_redirection_jamais_vers_un_autre_site(self):
        for piege in PIEGES:
            c, r = self.parcours(suivante=piege)
            self.assertEqual(r.status_code, 302, piege)
            self.assertEqual(r["Location"], "/", piege)
            c.post("/deconnexion/")

    def test_adresse_de_l_outil_gardee(self):
        c, r = self.parcours(suivante="/coherence/?campagne=1")
        self.assertEqual(r["Location"], "/coherence/?campagne=1")
