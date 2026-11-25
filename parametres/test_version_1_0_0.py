"""Numéro de version (depuis la 1.0.0, première version publique) : le numéro affiché suit le fichier ``VERSION``, qui est
celui de la dernière entrée de ``CHANGELOG.md`` (l'entrée la plus récente est en tête), et une sauvegarde
faite par une autre version (0.9.0 ici, un numéro fictif d'avant) puis ouverte pour être restaurée cite les deux versions
(l'outil ne fait qu'une égalité entre numéros, jamais de comparaison d'ordre)."""
import re

from django.conf import settings
from django.test import TransactionTestCase, override_settings
from django.urls import reverse

from referentiel.models import Utilisateur

from . import sauvegardes as SV
from .aides_tests.hebergement import MDP, RACINE, DossiersTemporaires


class Version100Tests(DossiersTemporaires, TransactionTestCase):  # la copie SQLite se fait hors transaction
    def setUp(self):
        super().setUp()
        self.admin = Utilisateur.objects.create_user("admin", email="admin@exemple.test", password=MDP, role=Utilisateur.Role.ADMIN)
        self.client.force_login(self.admin)

    def test_numero(self):
        version = (RACINE / "VERSION").read_text().strip()
        derniere = re.search(r"^## (\d+\.\d+\.\d+) — ", (RACINE / "CHANGELOG.md").read_text(encoding="utf-8"), re.M)
        self.assertEqual(version, derniere.group(1))
        self.assertEqual(settings.VERSION, version)
        self.assertContains(self.client.get(reverse("parametres:hebergement")), version)

    def test_sauvegarde_d_une_autre_version_ouverte(self):
        with override_settings(VERSION="0.9.0"):
            a = SV.creer("manuelle")
        self.assertEqual(SV.lire_descriptif(a.chemin)["version"], "0.9.0")
        rep = self.client.get(reverse("parametres:sauvegarde_restaurer", args=[a.nom]))
        self.assertContains(rep, "version 0.9.0")  # l'archive
        self.assertContains(rep, f"Faite avec la version 0.9.0 de l'outil ; la version {settings.VERSION} est installée.")
        self.assertContains(rep, f"version {settings.VERSION}")  # l'outil installé (pied de page)
