"""Monnaie de référence par espace : un nouvel espace part de l'euro, le défaut, même si
l'espace d'où il est créé compte dans une autre monnaie (l'identité reprise ne la contient pas) ; régler l'un ne change
pas l'autre. Données inventées uniquement."""
from parametres.models import Instance
from referentiel.models import Utilisateur

from . import contexte as E
from .aides_tests import DossierTemporaire, creer
from .creation import creer as creer_espace
from .essais import EspacesTestCase


class MonnaieNouvelEspaceTests(DossierTemporaire, EspacesTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.gestionnaire = creer("gestion@exemple.example", "admin")

    def test_nouvel_espace_en_euros_et_independant(self):
        Instance.objects.filter(pk=Instance.courante().pk).update(monnaie="USD")
        creer_espace("Achats France", "achats", Utilisateur.objects.get(pk=self.gestionnaire.pk))
        with E.activer("achats"):
            self.assertEqual(Instance.courante().monnaie, "EUR")
            Instance.objects.filter(pk=1).update(monnaie="GBP")
        self.assertEqual(Instance.courante().monnaie, "USD")
        with E.activer("achats"):
            self.assertEqual(Instance.courante().monnaie, "GBP")
