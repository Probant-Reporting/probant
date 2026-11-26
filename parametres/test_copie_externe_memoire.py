"""Grosse archive : la copie externe l'envoie par morceaux, avec une mémoire bornée (un morceau de 16 Mo à la fois au plus
pour S3, des blocs de 32 Ko pour SFTP), jamais l'archive entière en mémoire. Le client tourne dans un processus à lui
(le faux serveur reste dans celui du test) : son pic de mémoire est mesuré avant et après le dépôt d'une archive de 96 Mo.
Mesure à la main sur 1 Go (rapport du lot) : environ +17 Mo pour S3, +19 Mo pour SFTP."""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, override_settings

from parametres.aides_tests.faux_s3 import ID, SECRET, FauxS3

TAILLE_MO = 96
CLIENT = r"""
import os, resource, sys
sys.path.insert(0, os.environ["RACINE"])
from django.conf import settings
settings.configure(COPIE_EXTERNE_LOCAL=True)
from parametres import copie_externe as CE, copie_s3
chemin = os.environ["ARCHIVE"]
avant = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
sha = CE.sha256_fichier(chemin)
with copie_s3.ClientS3(os.environ["ADRESSE"], "", "sauvegardes", "path", os.environ["ID"], os.environ["SECRET"], base="m/") as c:
    c.deposer("backup-20261101-023000-auto.zip", chemin, os.path.getsize(chemin), sha)
print((resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - avant) // 1024)
"""


@override_settings(COPIE_EXTERNE_LOCAL=True)
class MemoireBorneeTests(SimpleTestCase):
    def test_s3_grosse_archive_memoire_bornee(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        archive = tmp / "backup-20261101-023000-auto.zip"
        bloc = os.urandom(1 << 20)
        with open(archive, "wb") as f:
            for _ in range(TAILLE_MO):
                f.write(bloc)
        faux = FauxS3()
        faux.garder = False
        self.addCleanup(faux.fermer)
        env = {k: v for k, v in os.environ.items() if not k.lower().endswith("_proxy")}
        env.update(RACINE=str(settings.BASE_DIR), ARCHIVE=str(archive), ADRESSE=faux.adresse, ID=ID, SECRET=SECRET)
        r = subprocess.run([sys.executable, "-c", CLIENT], env=env, capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        hausse = int(r.stdout.strip().splitlines()[-1])
        self.assertLess(hausse, 48, f"pic de mémoire +{hausse} Mo pour {TAILLE_MO} Mo envoyés")
        o = faux.objets["m/backup-20261101-023000-auto.zip"]
        self.assertEqual(o.taille, TAILLE_MO << 20)
        parts = [x for x in faux.requetes if x[0] == "PUT" and "partNumber" in x[2]]
        self.assertEqual(len(parts), TAILLE_MO // 16)
