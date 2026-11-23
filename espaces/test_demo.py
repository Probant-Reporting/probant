"""Démo à deux espaces (charger_demo --espaces) : « Sustainability » et « Achats », rôles différents pour les mêmes personnes."""
import io

from django.core.management import call_command
from django.test import Client

from collecte.models import Campagne
from referentiel.models import KPI, Utilisateur

from . import contexte as E
from .models import Espace
from .essais import EspacesTestCase
from .aides_tests import DossierTemporaire


class DemoEspacesTests(DossierTemporaire, EspacesTestCase):
    def test_charger_demo_espaces(self):
        Espace.objects.filter(code="essai").update(nom="Essai")
        call_command("charger_demo", "--language", "fr", "--espaces", stdout=io.StringIO())
        self.assertEqual(Espace.objects.get(code="principal").nom, "Sustainability")
        self.assertEqual((Espace.objects.get(code="achats").nom, Espace.objects.get(code="achats").etat), ("Achats", "actif"))
        with E.activer("achats"):
            self.assertEqual(KPI.objects.count(), 9)
            self.assertEqual(sorted(Campagne.objects.values_list("statut", flat=True)), ["cloturee", "ouverte"])
            roles = dict(Utilisateur.objects.values_list("username", "role"))
        self.assertEqual(roles, {"admin": "admin", "contributeur": "validateur", "acheteur": "contributeur"})
        self.assertEqual(Utilisateur.objects.get(username="contributeur").role, "contributeur")
        self.assertFalse(Utilisateur.objects.filter(username="acheteur").exists())
        c = Client()
        r = c.post("/connexion/", {"username": "acheteur", "password": "demo-probant-2026"})
        self.assertEqual(r["Location"], "/espace/achats/")
        self.assertEqual(c.get("/espace/achats/saisie/").status_code, 200)
        c = Client()
        c.post("/connexion/", {"username": "lecteur", "password": "demo-probant-2026"})
        self.assertEqual(c.get("/espace/achats/").status_code, 403)
