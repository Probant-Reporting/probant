"""Aides des tests de l'hébergement : dossiers temporaires, mot de passe d'essai, environnement propre, réglages."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from django.conf import settings
from django.test import override_settings



RACINE = Path(settings.BASE_DIR)


MDP = "Essai-hebergement-2026"


class DossiersTemporaires:
    """MEDIA_ROOT et SAUVEGARDES_DIR dans un dossier temporaire, supprimé à la fin."""

    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp())
        self.reglages = override_settings(MEDIA_ROOT=self.tmp / "media", SAUVEGARDES_DIR=self.tmp / "sauvegardes")
        self.reglages.enable()
        (self.tmp / "media").mkdir()

    def tearDown(self):
        self.reglages.disable()
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()


def environnement_propre():
    """Environnement du processus de test sans aucune variable de réglage de l'outil (noms anglais et anciens noms français :
    liste de ``config.settings``), pour que le sous-processus ne dépende pas de l'environnement qui lance les tests."""
    from config.settings import ANCIENS_NOMS

    noms = set(ANCIENS_NOMS) | set(ANCIENS_NOMS.values()) | {
        "BACKGROUND_IMPORT_ROWS", "DEFAULT_LANGUAGE", "DISK_ALERT_MB", "MEDIA_ROOT", "DATABASE_URL", "POSTGRESQL_ADDON_URI",
        "VERSION_COMMIT", "TIME_ZONE"}
    return {k: v for k, v in os.environ.items() if k not in noms and not k.startswith(("DJANGO_", "POSTGRES_", "SQLITE_", "SMTP_"))}


def reglages(env, code):
    """Évalue ``code`` (qui affiche un JSON) avec les réglages chargés dans un autre processus, sous ``env``."""
    base = environnement_propre()
    r = subprocess.run([sys.executable, "-c", "import json, django, os; os.environ.setdefault('DJANGO_SETTINGS_MODULE', "
                        "'config.settings'); django.setup(); from django.conf import settings as s; " + code],
                       cwd=RACINE, env={**base, **env}, capture_output=True, text=True, timeout=60)
    if r.returncode:
        raise AssertionError(r.stderr)
    return json.loads(r.stdout.strip().splitlines()[-1])
