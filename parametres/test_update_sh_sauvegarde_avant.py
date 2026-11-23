"""``update.sh`` : la sauvegarde « before-update » d'un outil arrêté.

Constaté à l'essai (Docker, PostgreSQL) : outil arrêté, la sauvegarde se fait par « docker compose run » ; elle doit
démarrer la base. Le script ne cherche ni volume ni image sous un autre nom que celui du projet : il ne s'arrête jamais
sur des volumes existants, et la sauvegarde d'un outil arrêté se fait avec l'image du projet (ou l'image publiée réglée).

Le test remplace ``docker`` par un faux qui note chaque appel et l'image demandée (variable ``IMAGE``)."""
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

RACINE = Path(settings.BASE_DIR)

FAUX_DOCKER = r"""#!/bin/sh
# faux docker : note l'appel (image demandée | arguments) et simule une installation arrêtée
echo "IMAGE=${IMAGE:-}|$*" >> "$JOURNAL"
case "$*" in
  "volume inspect"*) exit 0 ;;                                   # tout volume demandé existe
  "image inspect probant:local"*) [ -n "$IMAGE_ACTUELLE" ] && exit 0 || exit 1 ;;
  "image inspect"*) exit 0 ;;                                    # toute autre image existe
  "compose ps"*) exit 0 ;;                                       # aucun service en marche
  *"cat /app/VERSION"*) echo "0.9.0" ;;
esac
exit 0
"""


class SauvegardeAvantMiseAJourTests(SimpleTestCase):
    def lancer(self, image_actuelle, env_fichier="IMAGE=\n"):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        shutil.copy(RACINE / "update.sh", tmp / "update.sh")
        (tmp / ".env").write_text(env_fichier, encoding="utf-8")
        bin_ = tmp / "bin"
        bin_.mkdir()
        (bin_ / "docker").write_text(FAUX_DOCKER, encoding="utf-8")
        (bin_ / "docker").chmod(stat.S_IRWXU)
        journal = tmp / "journal.txt"
        env = {**os.environ, "PATH": f"{bin_}{os.pathsep}{os.environ['PATH']}", "JOURNAL": str(journal),
               "IMAGE_ACTUELLE": "1" if image_actuelle else ""}
        env.pop("IMAGE", None)
        r = subprocess.run(["sh", str(tmp / "update.sh")], cwd=tmp, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return journal.read_text(encoding="utf-8").splitlines()

    @staticmethod
    def sauvegardes(appels):
        return [a for a in appels if "compose run" in a and "manage.py backup" in a]

    def test_ne_cherche_aucun_volume_ni_image_d_un_autre_nom(self):
        """Volumes et images présents sous tous les noms : la mise à jour passe, sans s'arrêter et sans demander une
        autre image que celle du projet."""
        appels = self.lancer(image_actuelle=False)
        self.assertFalse([a for a in appels if "volume inspect" in a], appels)
        self.assertEqual(len(self.sauvegardes(appels)), 1, appels)
        self.assertTrue(self.sauvegardes(appels)[0].startswith("IMAGE=|"), appels)

    def test_outil_arrete_avec_postgresql_la_base_demarre_pour_la_sauvegarde(self):
        """Constaté avec PostgreSQL (profil « postgres ») : outil arrêté, « docker compose run --no-deps » ne démarrait
        pas le service « db » ; la sauvegarde échouait (« failed to resolve host 'db' ») et update.sh s'arrêtait à chaque
        essai. Sans « --no-deps », Docker Compose démarre la base (dépendance facultative du service « web » : rien avec
        SQLite) et attend qu'elle réponde."""
        for actuelle in (False, True):
            appels = self.lancer(image_actuelle=actuelle)
            with self.subTest(image_actuelle=actuelle):
                self.assertNotIn("--no-deps", self.sauvegardes(appels)[0])

    def test_image_actuelle_presente_rien_ne_change(self):
        appels = self.lancer(image_actuelle=True)
        self.assertTrue(self.sauvegardes(appels)[0].startswith("IMAGE=|"), appels)

    def test_image_publiee_reglee_rien_ne_change(self):
        appels = self.lancer(image_actuelle=False, env_fichier="IMAGE=ghcr.io/exemple/outil:0.9.0\n")
        self.assertTrue(self.sauvegardes(appels)[0].startswith("IMAGE=|"), appels)
