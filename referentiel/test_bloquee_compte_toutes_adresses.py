"""Limite des essais de connexion par compte, toutes adresses confondues : après
``ESSAIS_MAX_COMPTE`` échecs sur un même compte, depuis autant d'adresses qu'on veut, la connexion par mot de passe est
refusée pendant ``DUREE``, avec le message des autres blocages (il ne dit pas si le compte existe : un identifiant
inconnu est bloqué de la même façon), une seule ligne « bloquee » à l'historique par période de blocage, sur la page de
l'outil comme dans le mode expert (/admin/), dans tous les espaces (le compteur suit la personne du registre commun).
Une session déjà ouverte et un jeton d'assistant (MCP) ne sont pas touchés."""
from django.core.cache import caches
from django.test import Client

from espaces import contexte as E
from espaces.aides_tests import MDP, creer
from espaces.essais import EspacesTestCase
from referentiel.models import HistoriqueConnexion, Utilisateur

from . import connexion as CX


def client(n):
    """Un visiteur par adresse (aucune n'atteint les limites par adresse ni par identifiant et adresse)."""
    return Client(REMOTE_ADDR=f"203.0.113.{n % 250 + 1}" if n < 250 else f"198.51.100.{n % 250 + 1}")


def resultats(espace="principal"):
    with E.activer(espace):
        return list(HistoriqueConnexion.objects.order_by("pk").values_list("resultat", flat=True))


class CompteToutesAdressesTests(EspacesTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.contrib = creer("contrib@exemple.example")
        cls.admin = creer("admin@exemple.example", "admin")
        cls.partage = creer("partage@exemple.example", "contributeur")  # accès aux deux espaces
        creer("partage@exemple.example", "contributeur", "essai")

    def setUp(self):
        super().setUp()
        caches["connexion"].clear()

    def assertBloquee(self, rep, msg=None):
        """Même message que les autres blocages (« Trop d'essais », gabarit de la page de connexion), pas de session."""
        self.assertEqual(rep.status_code, 200, msg)
        self.assertTrue(rep.context["form"].bloquee, msg)
        self.assertNotIn("_auth_user_id", rep.client.session, msg)

    def echouer(self, identifiant, n, depart=0, page="/connexion/"):
        for i in range(depart, depart + n):
            client(i).post(page, {"username": identifiant, "password": "mauvais"})

    def test_seuil(self):
        self.assertEqual((CX.ESSAIS_MAX_COMPTE, CX.DUREE), (20, 15 * 60))
        self.assertGreater(CX.ESSAIS_MAX_COMPTE, CX.ESSAIS_MAX)

    def test_bloque_depuis_beaucoup_d_adresses(self):
        self.echouer("contrib@exemple.example", CX.ESSAIS_MAX_COMPTE)
        rep = client(500).post("/connexion/", {"username": "contrib@exemple.example", "password": MDP})
        self.assertEqual(rep.status_code, 200)  # bon mot de passe, nouvelle adresse : refusé
        self.assertBloquee(rep)
        self.assertNotIn("_auth_user_id", rep.client.session)

    def test_sous_le_seuil_la_connexion_passe(self):
        self.echouer("contrib@exemple.example", CX.ESSAIS_MAX_COMPTE - 1)
        rep = client(500).post("/connexion/", {"username": "contrib@exemple.example", "password": MDP})
        self.assertEqual(rep.status_code, 302)

    def test_identifiant_inconnu_meme_reponse(self):
        """Le blocage ne révèle pas si le compte existe."""
        self.echouer("personne@exemple.example", CX.ESSAIS_MAX_COMPTE)
        inconnu = client(500).post("/connexion/", {"username": "personne@exemple.example", "password": "x"})
        self.echouer("contrib@exemple.example", CX.ESSAIS_MAX_COMPTE, depart=600)
        connu = client(900).post("/connexion/", {"username": "contrib@exemple.example", "password": "x"})
        self.assertBloquee(inconnu)
        self.assertBloquee(connu)

    def test_casse_et_espaces_meme_compteur(self):
        for i in range(CX.ESSAIS_MAX_COMPTE):
            ident = ("contrib@exemple.example", " CONTRIB@exemple.example", "Contrib@exemple.example ")[i % 3]
            client(i).post("/connexion/", {"username": ident, "password": "mauvais"})
        rep = client(500).post("/connexion/", {"username": "contrib@exemple.example", "password": MDP})
        self.assertBloquee(rep)

    def test_une_seule_ligne_bloquee_par_periode(self):
        self.echouer("contrib@exemple.example", CX.ESSAIS_MAX_COMPTE)
        self.echouer("contrib@exemple.example", 15, depart=300)  # 15 adresses de plus, toutes refusées
        self.assertEqual(resultats(), ["echec"] * CX.ESSAIS_MAX_COMPTE + ["bloquee"])

    def test_mode_expert(self):
        self.echouer("admin@exemple.example", CX.ESSAIS_MAX_COMPTE, page="/admin/login/")
        c = client(500)
        c.post("/admin/login/", {"username": "admin@exemple.example", "password": MDP})
        self.assertNotIn("_auth_user_id", c.session)
        self.assertEqual(resultats()[-1], "bloquee")
        rep = client(501).post("/connexion/", {"username": "admin@exemple.example", "password": MDP})
        self.assertBloquee(rep)  # aussi sur la page de l'outil

    def test_le_compteur_suit_la_personne_dans_tous_les_espaces(self):
        moitie = CX.ESSAIS_MAX_COMPTE // 2
        self.echouer("partage@exemple.example", moitie)
        self.echouer("partage@exemple.example", CX.ESSAIS_MAX_COMPTE - moitie, depart=100, page="/espace/essai/connexion/")
        for page in ("/connexion/", "/espace/essai/connexion/"):
            rep = client(500).post(page, {"username": "partage@exemple.example", "password": MDP})
            self.assertBloquee(rep, page)

    def test_session_deja_ouverte_non_touchee(self):
        ouverte = client(500)
        ouverte.post("/connexion/", {"username": "contrib@exemple.example", "password": MDP})
        self.assertIn("_auth_user_id", ouverte.session)
        self.echouer("contrib@exemple.example", CX.ESSAIS_MAX_COMPTE + 5)
        self.assertEqual(ouverte.get("/saisie/").status_code, 200)

    def test_jeton_d_assistant_non_touche(self):
        from serveur_mcp import jetons as JT
        from serveur_mcp.models import ReglageMCP

        ReglageMCP.objects.update_or_create(pk=1, defaults={"actif": True})
        u = Utilisateur.objects.get(pk=self.contrib.pk)
        clair, _ = JT.creer(u, "Portable", 30)
        self.echouer("contrib@exemple.example", CX.ESSAIS_MAX_COMPTE)
        self.assertEqual(JT.authentifier(clair)[0].pk, u.pk)

    def test_reussite_remet_le_compteur_du_compte_a_zero(self):
        self.echouer("contrib@exemple.example", CX.ESSAIS_MAX_COMPTE - 1)
        self.assertEqual(client(500).post("/connexion/", {"username": "contrib@exemple.example", "password": MDP}).status_code, 302)
        self.echouer("contrib@exemple.example", CX.ESSAIS_MAX_COMPTE - 1, depart=600)
        self.assertEqual(client(900).post("/connexion/", {"username": "contrib@exemple.example", "password": MDP}).status_code, 302)

    def test_refus_d_une_adresse_bloquee_ne_bloque_pas_le_compte(self):
        """Une adresse bloquée (5 échecs) qui insiste ne bloque pas la personne ailleurs : seuls les mots de passe
        vérifiés comptent pour le compte."""
        for _ in range(CX.ESSAIS_MAX_COMPTE + 10):
            client(1).post("/connexion/", {"username": "contrib@exemple.example", "password": "mauvais"})
        rep = client(500).post("/connexion/", {"username": "contrib@exemple.example", "password": MDP})
        self.assertEqual(rep.status_code, 302)
