"""Paramètres › Assistant IA (vues_ia.reglages), affichage : l'hôte du fournisseur s'écrit entre une seule paire de
parenthèses, aussi avec le fournisseur factice (« ((none)) » avant)."""
import html

from django.test import TestCase
from django.urls import reverse

from parametres.aides_tests.ia import AvecIA
from referentiel.models import Utilisateur


class AffichageHoteTests(AvecIA, TestCase):
    def test_pas_de_doubles_parentheses(self):
        self.allumer()
        admin = Utilisateur.objects.create(username="adm", email="adm@exemple.test", role=Utilisateur.Role.ADMIN)
        self.client.force_login(admin)
        page = html.unescape(self.client.get(reverse("parametres:ia")).content.decode())
        self.assertNotIn("((none))", page)
        self.assertIn("Fake provider (tests) (none)", page)
