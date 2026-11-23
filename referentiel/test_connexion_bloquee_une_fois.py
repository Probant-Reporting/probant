"""Historique des connexions et limite d'essais : une seule ligne « bloquee » par période de blocage (par identifiant et
adresse), sur la page de l'outil comme dans le mode expert (/admin/) ; insister ne fait plus grossir la table ni les
sauvegardes. Mode expert : un bon mot de passe dont l'accès est dans un autre espace laisse un échec (pas de connexion
ailleurs depuis /admin/)."""
from django.core.cache import caches
from django.test import Client

from espaces import contexte as E
from espaces.aides_tests import MDP, creer
from espaces.essais import EspacesTestCase

from . import connexion as CX
from . import historique_connexions as HC
from .models import HistoriqueConnexion


def resultats(espace="principal"):
    with E.activer(espace):
        return list(HistoriqueConnexion.objects.order_by("pk").values_list("resultat", flat=True))


class BloqueeUneFoisTests(EspacesTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.contrib = creer("contrib@exemple.example")
        cls.admin = creer("admin@exemple.example", "admin")
        cls.achats = creer("achats@exemple.example", "admin", "essai")  # « essai » seulement

    def setUp(self):
        super().setUp()
        caches["connexion"].clear()

    def test_page_de_l_outil_30_envois(self):
        for _ in range(30):
            Client().post("/connexion/", {"username": "contrib@exemple.example", "password": "mauvais"})
        self.assertEqual(resultats(), ["echec"] * CX.ESSAIS_MAX + ["bloquee"])

    def test_mode_expert_30_envois(self):
        for _ in range(30):
            Client().post("/admin/login/", {"username": "admin@exemple.example", "password": "mauvais"})
        self.assertEqual(resultats(), ["echec"] * CX.ESSAIS_MAX + ["bloquee"])

    def test_outil_puis_mode_expert_meme_periode(self):
        """Même identifiant, même adresse : une seule ligne « bloquee » pour les deux pages."""
        for _ in range(10):
            Client().post("/connexion/", {"username": "admin@exemple.example", "password": "mauvais"})
        for _ in range(10):
            Client().post("/admin/login/", {"username": "admin@exemple.example", "password": MDP})
        self.assertEqual(resultats(), ["echec"] * CX.ESSAIS_MAX + ["bloquee"])

    def test_nouvelle_periode_nouvelle_ligne(self):
        for _ in range(8):
            Client().post("/connexion/", {"username": "contrib@exemple.example", "password": "mauvais"})
        caches["connexion"].clear()  # fin du blocage (les clés expirent ensemble)
        for _ in range(8):
            Client().post("/connexion/", {"username": "contrib@exemple.example", "password": "mauvais"})
        self.assertEqual(resultats(), (["echec"] * CX.ESSAIS_MAX + ["bloquee"]) * 2)

    def test_autre_identifiant_sa_propre_ligne(self):
        for ident in ("contrib@exemple.example", "admin@exemple.example"):
            for _ in range(8):
                Client().post("/connexion/", {"username": ident, "password": "mauvais"})
        self.assertEqual(resultats(), (["echec"] * CX.ESSAIS_MAX + ["bloquee"]) * 2)

    def test_mode_expert_bon_mot_de_passe_acces_ailleurs(self):
        """/admin/ ne connecte pas dans l'espace où la personne a accès : l'essai est un échec, noté ici (par l'empreinte :
        le compte n'a pas de copie dans l'espace principal)."""
        rep = Client().post("/admin/login/", {"username": "achats@exemple.example", "password": MDP})
        self.assertEqual(rep.status_code, 200)
        with E.activer("principal"):
            self.assertEqual(list(HistoriqueConnexion.objects.values_list("utilisateur_id", "resultat", "empreinte")),
                             [(None, "echec", HC.empreinte("achats@exemple.example"))])
        self.assertEqual(resultats("essai"), [])

    def test_page_de_l_outil_bon_mot_de_passe_acces_ailleurs_inchange(self):
        """La page de l'outil connecte dans l'espace où la personne a accès : une réussite là-bas, rien ici."""
        rep = Client().post("/connexion/", {"username": "achats@exemple.example", "password": MDP})
        self.assertEqual(rep.status_code, 302)
        self.assertEqual(resultats(), [])
        self.assertEqual(resultats("essai"), ["reussie"])
