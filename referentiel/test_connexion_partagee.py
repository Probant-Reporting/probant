"""Compteur des essais de connexion partagé entre les processus du serveur (``CACHES["connexion"]``) : avec le vrai
réglage (hors tests : des fichiers dans le dossier des données), des échecs notés par deux processus différents
s'additionnent, et un troisième processus (un redémarrage) voit le blocage. Avant, chaque processus gunicorn comptait
pour lui seul (5 essais par processus) et tout repartait de zéro au redémarrage."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

RACINE = Path(settings.BASE_DIR)

# un processus du serveur : Django avec le vrai réglage (pas en mode test), le dossier des données donné
PROCESSUS = """
import json, os, sys
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
import django
django.setup()
from django.conf import settings
from referentiel import connexion as C
for _ in range(int(sys.argv[1])):
    C.noter_echec("contrib@exemple.test", None)
print(json.dumps({"cache": settings.CACHES["connexion"], "bloquee": C.bloquee("contrib@exemple.test", None)}))
"""


class CompteurPartageEntreProcessus(SimpleTestCase):
    def processus(self, dossier, echecs):
        env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL",)}
        env["DATA_DIR"] = dossier
        r = subprocess.run([sys.executable, "-c", PROCESSUS, str(echecs)], cwd=RACINE, env=env, capture_output=True,
                           text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_echecs_de_deux_processus_additionnes_et_gardes_au_redemarrage(self):
        with tempfile.TemporaryDirectory(prefix="connexion-") as dossier:
            premier = self.processus(dossier, 3)
            self.assertEqual(premier["cache"]["BACKEND"], "django.core.cache.backends.filebased.FileBasedCache")
            self.assertEqual(Path(premier["cache"]["LOCATION"]), Path(dossier) / "sign-in-attempts")
            self.assertFalse(premier["bloquee"])  # 3 essais sur 5
            self.assertTrue(self.processus(dossier, 2)["bloquee"])  # autre processus : 3 + 2 = 5, bloqué
            self.assertTrue(self.processus(dossier, 0)["bloquee"])  # redémarrage : toujours bloqué
        with tempfile.TemporaryDirectory(prefix="connexion-") as autre:
            self.assertFalse(self.processus(autre, 4)["bloquee"])  # autre installation : rien de partagé

    def test_en_test_le_cache_dedie_reste_en_memoire(self):
        # tests en parallèle (--parallel) : chaque processus de test a son compteur, ils ne se gênent pas
        self.assertEqual(settings.CACHES["connexion"]["BACKEND"], "django.core.cache.backends.locmem.LocMemCache")
        self.assertEqual(settings.CACHES["default"]["BACKEND"], "django.core.cache.backends.locmem.LocMemCache")
