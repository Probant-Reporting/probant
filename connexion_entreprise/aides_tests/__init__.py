"""Aides des tests de la connexion d'entreprise : faux fournisseur partagé par la classe, réglage allumé, parcours
complet (page de connexion → fournisseur → retour)."""
import urllib.parse

from django.core.cache import caches
from django.test import Client

from espaces.aides_tests import creer
from espaces.essais import EspacesTestCase
from espaces.models import Compte

from .. import oidc
from ..models import ReglageEntreprise
from ..secret import chiffrer
from .faux_fournisseur import CLIENT_ID, SECRET, FauxFournisseur

RETOUR = "/connexion/entreprise/retour/"


def regler(faux, **valeurs):
    """Réglage allumé et complet pour ce faux fournisseur (``valeurs`` : champs remplacés)."""
    champs = {"actif": True, "emetteur": faux.emetteur, "client_id": CLIENT_ID, "secret_chiffre": chiffrer(SECRET),
              "email_non_declare": False, "mot_de_passe_pour_tous": False, **valeurs}
    ReglageEntreprise.objects.update_or_create(pk=1, defaults=champs)
    oidc.oublier_caches()


class BaseEntreprise(EspacesTestCase):
    """Deux espaces (principal, « essai »), un faux fournisseur ; un contributeur, un administrateur gestionnaire des
    espaces (compte de secours) et un administrateur qui ne l'est pas."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.faux = FauxFournisseur()

    @classmethod
    def tearDownClass(cls):
        cls.faux.arreter()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.faux.mode, self.faux.claims, self.faux.decouverte = "", {}, {}
        self.faux.appels.clear()
        self.faux.echanges.clear()
        oidc.oublier_caches()
        caches["connexion"].clear()
        self.gestionnaire = creer("gestion@exemple.example", "admin")
        self.contrib = creer("contrib@exemple.example", "contributeur")
        self.admin = creer("admin2@exemple.example", "admin")
        Compte.objects.update(gestionnaire=False)
        Compte.objects.filter(pk=self.gestionnaire.pk).update(gestionnaire=True)

    def regler(self, **valeurs):
        regler(self.faux, **valeurs)

    def aller(self, client=None, suivante="", espace="principal"):
        """(client, réponse du début) : la page du bouton renvoie vers le fournisseur."""
        c = client or Client()
        page = "/connexion/entreprise/" if espace == "principal" else f"/espace/{espace}/connexion/entreprise/"
        return c, c.get(page, {"next": suivante} if suivante else {})

    def parcours(self, client=None, suivante="", espace="principal"):
        """(client, réponse du retour) : aller, le fournisseur accepte (ou refuse en mode « refus »), retour."""
        c, r = self.aller(client, suivante, espace)
        self.assertEqual(r.status_code, 302, r.content[:300])
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(r["Location"]).query))
        self.assertTrue(r["Location"].startswith(self.faux.emetteur + "/authorize?"), r["Location"])
        params = {"error": "access_denied", "state": q["state"]} if self.faux.mode == "refus" else {
            "code": self.faux.emettre_code(q), "state": q["state"]}
        return c, c.get(RETOUR, params)

    def connecte(self, client):
        return client.session.get("_auth_user_id")
