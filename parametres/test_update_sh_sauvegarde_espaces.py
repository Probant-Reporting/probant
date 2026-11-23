"""``update.sh`` sauvegarde chaque espace avec la version installée avant la mise à jour.

Avant : seul l'espace principal avait une archive « before-update » faite par l'ancienne version ; pour les autres
espaces, seules existaient les archives faites au démarrage par la NOUVELLE version, qu'une version ancienne ne sait
pas toujours lire : un retour arrière ne pouvait pas rendre tous les espaces. Après : un ``backup`` par espace
(``SPACE=<code>``), dans le service en marche ou dans l'image de la version installée, avant toute construction ; un
échec arrête la mise à jour avant tout changement.

Le test remplace ``docker`` par un faux qui note chaque appel (image demandée, arguments) et répond à
``spaces --list`` comme la version installée."""
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
echo "IMAGE=${IMAGE:-}|$*" >> "$JOURNAL"
case "$*" in
  "volume inspect"*) exit 1 ;;
  "image inspect"*) exit 0 ;;
  "compose ps"*) [ -n "$EN_MARCHE" ] && echo web; exit 0 ;;
  *"manage.py spaces --list"*)
    echo "principal            Espace principal               /                        active       12 account(s)"
    echo "achats               Achats et fournisseurs du groupe /espace/achats/        active       4 account(s)"
    echo "rh                   RH                             /espace/rh/              archived     2 account(s)"
    echo "warning              une ligne de journal sans adresse d'espace"
    exit 0 ;;
  *"SPACE=$ECHEC"*"manage.py backup"*) [ -n "$ECHEC" ] && exit 1 ;;
  *"cat /app/VERSION"*) echo "0.9.0" ;;
esac
exit 0
"""


class SauvegardeDeChaqueEspace(SimpleTestCase):
    def lancer(self, en_marche=False, echec=""):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        shutil.copy(RACINE / "update.sh", tmp / "update.sh")
        (tmp / ".env").write_text("IMAGE=\n", encoding="utf-8")
        bin_ = tmp / "bin"
        bin_.mkdir()
        (bin_ / "docker").write_text(FAUX_DOCKER, encoding="utf-8")
        (bin_ / "docker").chmod(stat.S_IRWXU)
        journal = tmp / "journal.txt"
        env = {**os.environ, "PATH": f"{bin_}{os.pathsep}{os.environ['PATH']}", "JOURNAL": str(journal),
               "EN_MARCHE": "1" if en_marche else "", "ECHEC": echec}
        env.pop("IMAGE", None)
        r = subprocess.run(["sh", str(tmp / "update.sh")], cwd=tmp, env=env, capture_output=True, text=True, timeout=60)
        return r, journal.read_text(encoding="utf-8").splitlines()

    @staticmethod
    def sauvegardes(appels):
        return [a.split("|", 1)[1] for a in appels if "manage.py backup" in a]

    def test_outil_arrete_chaque_espace_avec_l_image_installee(self):
        r, appels = self.lancer()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        s = self.sauvegardes(appels)
        self.assertEqual(len(s), 3, appels)
        self.assertTrue(all(a.startswith("compose run --rm -T ") for a in s), s)
        self.assertNotIn("SPACE=", s[0])  # l'espace principal d'abord
        self.assertIn("-e SPACE=achats web python manage.py backup --reason before-update", s[1])
        self.assertIn("-e SPACE=rh web python manage.py backup --reason before-update", s[2])
        # toutes avant la nouvelle version
        construction = next(i for i, a in enumerate(appels) if "compose build" in a)
        self.assertTrue(all(i < construction for i, a in enumerate(appels) if "manage.py backup" in a))

    def test_outil_en_marche_dans_le_service(self):
        r, appels = self.lancer(en_marche=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        s = self.sauvegardes(appels)
        self.assertEqual([a.split(" web ")[0] for a in s],
                         ["compose exec -T", "compose exec -T -e SPACE=achats", "compose exec -T -e SPACE=rh"])

    def test_echec_d_un_espace_arrete_la_mise_a_jour(self):
        r, appels = self.lancer(echec="achats")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('The backup of the space "achats" failed', r.stdout)
        self.assertFalse([a for a in appels if "compose build" in a or "compose up" in a or "compose pull" in a], appels)
