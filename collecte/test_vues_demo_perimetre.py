"""Démo Exemplia, vue d'accueil « Mon périmètre » des contributeurs et des validateurs (règle du projet) : elle n'est plus fixée sur France, où la contributrice de démo n'a aucun droit (chaque visuel disait « Rien à
montrer pour ces filtres ») ; elle s'ouvre sur le périmètre de la personne. ``charger_demo.vues_demo``."""
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from referentiel.models import Utilisateur

from . import visuels as VS
from .models import AccueilVisu


class VueMonPerimetreTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("load_demo", "--language", "fr", stdout=StringIO())

    def test_sans_organisation_fixee(self):
        vue = AccueilVisu.objects.get(role="contributeur").vue
        self.assertEqual(vue.nom, "Mon périmètre")
        self.assertNotIn("org", vue.filtres)
        self.assertEqual(AccueilVisu.objects.get(role="validateur").vue, vue)

    def test_chaque_visuel_montre_le_perimetre_de_la_personne(self):
        for nom in ("contributeur", "validateur"):
            u = Utilisateur.objects.get(username=nom)
            vue = AccueilVisu.objects.get(role=u.role).vue
            d = VS.donnees(u, vue.filtres, vue.visuels)
            with self.subTest(compte=nom):
                etats = {i: v["etat"] for i, v in d["visuels"].items()}
                self.assertEqual(len(etats), len(vue.visuels))
                self.assertEqual({i for i, e in etats.items() if e != "ok"}, set(), etats)
