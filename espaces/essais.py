"""Tests : chaque test peut toucher la base de l'espace principal et le registre commun ; les tests des espaces
(``EspacesTestCase``) ont en plus un second espace, « essai » (alias ``espace_essai``, déclaré pendant les tests)."""
from django.test import TestCase, TransactionTestCase
from django.test.runner import DiscoverRunner


def ouvrir_bases():
    if set(TransactionTestCase.databases) == {"default"}:
        TransactionTestCase.databases = frozenset({"default", "commun"})


class Lanceur(DiscoverRunner):
    def setup_test_environment(self, **kwargs):
        ouvrir_bases()
        super().setup_test_environment(**kwargs)


class EspacesTestCase(TestCase):
    """Deux espaces : le principal (``default``) et « essai » (``espace_essai``), inscrits au registre."""

    databases = {"default", "commun", "espace_essai"}

    @classmethod
    def setUpTestData(cls):
        from .models import Espace

        Espace.objects.get_or_create(code="principal", defaults={"nom": "RSE", "etat": "actif"})
        Espace.objects.get_or_create(code="essai", defaults={"nom": "Achats", "etat": "actif", "rang": 1})
        super().setUpTestData()
