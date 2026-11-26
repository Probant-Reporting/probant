"""``startup`` (démarrage) sur la base de la démo : le résumé pour l'IT le dit (ses comptes ont un mot de passe public).
Cas d'un dossier des données de la version tout-en-un, préparé avec la démo, posé sur un serveur (docs/from_pc_to_server.md)."""
import io
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase, override_settings

from collecte.management.commands import charger_demo as CD
from collecte.models import Journal
from parametres.models import Instance
from referentiel.models import Utilisateur

AVERTISSEMENT = "demo database"


class DemarrageBaseDeDemoTests(TestCase):
    databases = {"default", "commun"}

    def demarrer(self):
        with tempfile.TemporaryDirectory() as tmp, override_settings(
                DOSSIER_DONNEES=Path(tmp), MEDIA_ROOT=Path(tmp) / "media", SAUVEGARDES_DIR=Path(tmp) / "sauvegardes"):
            sortie = io.StringIO()
            call_command("demarrage", stdout=sortie, stderr=io.StringIO())
            return sortie.getvalue()

    def test_base_reelle_sans_avertissement(self):
        Utilisateur.objects.create_user("alex", email="alex@exemple.test", password="Un-vrai-mot-de-passe-2026")
        self.assertNotIn(AVERTISSEMENT, self.demarrer())

    def test_base_de_demo_signalee(self):
        Journal.ecrire(None, CD.MARQUEUR, Instance.courante(), "client", "", "exemplia")
        sortie = self.demarrer()
        self.assertIn(AVERTISSEMENT, sortie)
        self.assertIn("public password", sortie)
