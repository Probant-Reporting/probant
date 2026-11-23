"""Connexion avec un hachage de mot de passe dépassé (après une mise à jour de Django) : la connexion le recalcule
(``referentiel.auth``, écrit par ``update()``, donc sans signal) ; les jetons MCP de la personne restent valides dans
chaque espace, comme Mon compte les montre. Un vrai changement de mot de passe les révoque toujours."""
import json
import logging

from django.contrib.auth import authenticate
from django.contrib.auth.hashers import make_password
from django.test import Client, override_settings

from espaces import contexte as E
from espaces.aides_tests import MDP, creer
from espaces.essais import EspacesTestCase
from espaces.models import Compte
from referentiel.models import Utilisateur

from . import jetons as JT
from .models import JetonMCP, ReglageMCP

HACHAGES = ["django.contrib.auth.hashers.PBKDF2PasswordHasher", "django.contrib.auth.hashers.MD5PasswordHasher"]


class HachageRecalculeALaConnexionTests(EspacesTestCase):
    def setUp(self):
        journal = logging.getLogger("serveur_mcp")
        self.addCleanup(journal.setLevel, journal.level)
        journal.setLevel(logging.ERROR)
        self.u = creer("hachage@exemple.example", "admin")
        creer("hachage@exemple.example", "admin", "essai")
        ancien = make_password(MDP, hasher="md5")  # hachage d'avant la mise à jour
        Compte.objects.filter(pk=self.u.pk).update(password=ancien)
        for code in ("principal", "essai"):
            with E.activer(code):
                Utilisateur.objects.filter(pk=self.u.pk).update(password=ancien)
                ReglageMCP.objects.update_or_create(pk=1, defaults={"actif": True})
        with E.activer("principal"):
            self.ici, _ = JT.creer(Utilisateur.objects.get(pk=self.u.pk), "Principal", 7)
        with E.activer("essai"):
            self.la, _ = JT.creer(Utilisateur.objects.get(pk=self.u.pk), "Essai", 7)

    def statut(self, url, jeton):
        corps = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        return Client().post(url, corps, content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {jeton}").status_code

    def test_jetons_toujours_valides_apres_la_connexion(self):
        with override_settings(PASSWORD_HASHERS=HACHAGES):
            self.assertIsNotNone(authenticate(None, username="hachage@exemple.example", password=MDP))
            self.assertTrue(Compte.objects.get(pk=self.u.pk).password.startswith("pbkdf2_"))  # recalculé
            self.assertEqual(self.statut("/mcp/", self.ici), 200)
            self.assertEqual(self.statut("/espace/essai/mcp/", self.la), 200)
        for code in ("principal", "essai"):
            with E.activer(code):
                self.assertFalse(JetonMCP.objects.filter(revoque_le__isnull=False).exists())

    def test_vrai_changement_apres_la_connexion_revoque_toujours(self):
        with override_settings(PASSWORD_HASHERS=HACHAGES):
            authenticate(None, username="hachage@exemple.example", password=MDP)
            with E.activer("principal"):
                u = Utilisateur.objects.get(pk=self.u.pk)
                u.set_password("Nouveau-mot-de-passe-2026")
                u.save()
            self.assertEqual(self.statut("/mcp/", self.ici), 401)
            self.assertEqual(self.statut("/espace/essai/mcp/", self.la), 401)
        for code in ("principal", "essai"):
            with E.activer(code):
                self.assertIsNotNone(JetonMCP.objects.get().revoque_le)
