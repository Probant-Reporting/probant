"""Démarrage : un espace dont la base est en défaut est marqué indisponible (page 503) sans bloquer les autres."""
import io
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.management import call_command
from django.test import override_settings

from . import contexte as E
from .essais import EspacesTestCase
from .models import Espace, Installation, MarqueEspace
from .aides_tests import creer
from .aides_tests import oublier_alias

SQLITE = settings.DATABASES["default"]["ENGINE"].endswith("sqlite3")


@unittest.skipUnless(SQLITE, "base illisible simulée par un fichier SQLite abîmé")
class DemarrageTests(EspacesTestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        reglages = override_settings(DOSSIER_DONNEES=tmp, MEDIA_ROOT=tmp / "media", SAUVEGARDES_DIR=tmp / "sauvegardes",
                                     ESPACES_DOSSIER=tmp / "espaces-donnees")
        reglages.enable()
        self.addCleanup(reglages.disable)
        self.addCleanup(oublier_alias, "espace_casse")
        self.enterContext(mock.patch.object(type(self), "databases", frozenset(self.databases) | {"espace_casse"}))
        (tmp / "espaces-donnees" / "casse").mkdir(parents=True)
        (tmp / "espaces-donnees" / "casse" / "database.sqlite3").write_bytes(b"ceci n'est pas une base" * 100)
        Espace.objects.create(code="casse", nom="Cassé", etat="actif", rang=5)
        Installation.objects.create(identifiant="ici")
        MarqueEspace.objects.create(code="principal", installation="ici")
        MarqueEspace.objects.using("espace_essai").create(code="essai", installation="ici")
        self.enterContext(self.assertLogs("reporting.espaces", "ERROR"))  # l'espace cassé est signalé, puis ignoré
        self.admin = creer("admin@exemple.example", "admin")

    def test_espace_en_defaut_sans_bloquer_les_autres(self):
        sortie, erreurs = io.StringIO(), io.StringIO()
        call_command("demarrage", attente=1, stdout=sortie, stderr=erreurs)
        self.assertTrue(E.indisponible("casse"))
        self.assertFalse(E.indisponible("essai"))
        self.assertIn('Space "Cassé" (casse): UNAVAILABLE', sortie.getvalue())
        self.assertIn('Space "Achats" (essai): ready', sortie.getvalue())
        from referentiel.models import Utilisateur

        self.client.force_login(Utilisateur.objects.get(pk=self.admin.pk))
        self.assertEqual(self.client.get("/espace/casse/").status_code, 503)
        self.assertEqual(self.client.get("/mon-compte/").status_code, 200)
        u = Utilisateur.objects.get(pk=self.admin.pk)  # les comptes s'enregistrent toujours (espace cassé ignoré)
        u.first_name = "Encore"
        u.save()

    def test_marque_d_un_autre_espace(self):
        MarqueEspace.objects.using("espace_essai").update(code="autre")
        sortie = io.StringIO()
        (Path(settings.ESPACES_DOSSIER) / "casse" / "database.sqlite3").unlink()
        Espace.objects.filter(code="casse").delete()
        call_command("demarrage", attente=1, stdout=sortie, stderr=io.StringIO())
        self.assertTrue(E.indisponible("essai"))
        self.assertIn("different mark", sortie.getvalue())
        E.marquer_indisponible("essai", "")

    def test_base_d_un_autre_espace_jamais_modifiee(self):
        """Base d'un autre espace posée à la place de celle d'« essai » (erreur de l'IT) : ni migrée ni réconciliée
        (un compte en conflit n'y est pas désactivé), l'espace est indisponible."""
        from referentiel.models import Utilisateur

        MarqueEspace.objects.using("espace_essai").update(code="autre")
        Utilisateur.objects.using("espace_essai").bulk_create([
            Utilisateur(pk=self.admin.pk, username="intrus", email="intrus@exemple.example", role="admin")])
        (Path(settings.ESPACES_DOSSIER) / "casse" / "database.sqlite3").unlink()
        Espace.objects.filter(code="casse").delete()
        erreurs = io.StringIO()
        call_command("migrate", verbosity=0, stdout=io.StringIO(), stderr=erreurs)
        self.assertTrue(E.indisponible("essai"))
        self.assertIn("different mark", erreurs.getvalue())
        self.assertTrue(Utilisateur.objects.using("espace_essai").get(pk=self.admin.pk).is_active)
        E.marquer_indisponible("essai", "")
