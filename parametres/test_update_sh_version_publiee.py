"""``update.sh`` dans un dossier installé par ``get.sh`` (sans Git, ``IMAGE=`` réglé sur une version X.Y.Z de l'image
publiée) : passage à la dernière version (ou à ``--version``), sauvegarde d'abord, ``.env`` gardé.

Un clone Git, ou un dossier sans image publiée réglée, se met à jour comme avant, sans rien télécharger. Joué avec le
vrai ``curl`` contre une copie locale du dépôt public et un faux ``docker`` qui note, à chaque appel, la version des
fichiers en place (dernière ligne de docker-compose.yml)."""
import shutil

from django.test import SimpleTestCase

from parametres.aides_tests.scripts_installation import (
    FICHIERS_VERSION, IMAGE_PUBLIQUE, RACINE, AidesScripts, version_des_fichiers)

ENV = f"DOMAIN=reporting.example.com\nIMAGE={IMAGE_PUBLIQUE}:9.9.0\nSMTP_PASSWORD=garde\n"


class MiseAJourVersionPublieeTests(AidesScripts, SimpleTestCase):
    def preparer(self, env_fichier=ENV, git=False, derniere="V9.9.1"):
        tmp = self.dossier()
        for f, contenu in version_des_fichiers("9.9.0").items():
            if f != "VERSION":
                (tmp / f).parent.mkdir(parents=True, exist_ok=True)
                (tmp / f).write_bytes(contenu)
        # update.sh de cette version-ci (celui qui tourne), même s'il est remplacé en route
        shutil.copy(RACINE / "update.sh", tmp / "update.sh")
        (tmp / ".env").write_text(env_fichier, encoding="utf-8")
        if git:
            (tmp / ".git").mkdir()
        depot = self.depot({"v9.9.0": version_des_fichiers("9.9.0"), "V9.9.1": version_des_fichiers("9.9.1"),
                            "v9.10.0": version_des_fichiers("9.10.0")}, derniere)
        return tmp, depot, self.environnement(tmp, depot)

    def update(self, tmp, env, *options):
        return self.lancer(["sh", "update.sh", *options], cwd=tmp, env=env)

    def appels(self, tmp):
        """[(version des fichiers en place, arguments)]"""
        return [tuple(a.split("|", 1)) for a in super().appels(tmp)]

    def test_vers_la_derniere_version(self):
        tmp, depot, env = self.preparer()
        r = self.update(tmp, env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((tmp / ".env").read_text(encoding="utf-8"), ENV.replace(":9.9.0", ":9.9.1"))
        for f in FICHIERS_VERSION:
            self.assertEqual((tmp / f).read_bytes(), version_des_fichiers("9.9.1")[f], f)
        appels = self.appels(tmp)
        # sauvegarde avec les fichiers et l'image de la version installée ; image suivante téléchargée, puis démarrée
        sauvegardes = [v for v, a in appels if "manage.py backup" in a]
        self.assertEqual(sauvegardes, ["# files of version 9.9.0"])
        self.assertIn(("# files of version 9.9.1", "compose pull web"), appels)
        self.assertIn(("# files of version 9.9.1", "compose up -d"), appels)
        self.assertFalse([a for v, a in appels if "build" in a])
        self.assertIn(f"Image before the update: {IMAGE_PUBLIQUE}:9.9.0", r.stdout)
        self.assertFalse(list(tmp.glob(".download*")), "dossier de téléchargement laissé")

    def test_version_demandee(self):
        """Comparaison des versions par nombres : 9.10.0 vient après 9.9.0."""
        tmp, depot, env = self.preparer()
        r = self.update(tmp, env, "--version", "9.10.0")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.valeur(tmp / ".env", "IMAGE"), f"{IMAGE_PUBLIQUE}:9.10.0")
        self.assertNotIn("/releases/latest", depot.demandes)

    def test_deja_la_derniere_redemarre_sans_rien_telecharger(self):
        tmp, depot, env = self.preparer(derniere="v9.9.0")
        r = self.update(tmp, env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Version 9.9.0 is the latest", r.stdout)
        self.assertEqual(depot.fichiers_demandes(), [])
        self.assertEqual((tmp / ".env").read_text(encoding="utf-8"), ENV)
        self.assertIn("compose pull web", [a for v, a in self.appels(tmp)])

    def test_version_plus_ancienne_refusee_avant_tout(self):
        tmp, depot, env = self.preparer()
        r = self.update(tmp, env, "--version", "9.8.5")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Going back to the previous version", r.stdout)
        self.assertEqual(self.appels(tmp), [])
        self.assertEqual((tmp / ".env").read_text(encoding="utf-8"), ENV)

    def test_telechargement_impossible_rien_ne_change(self):
        tmp, depot, env = self.preparer()
        r = self.update(tmp, env, "--version", "9.9.7")
        self.assertEqual(r.returncode, 1)
        self.assertIn("nothing was changed", r.stdout)
        self.assertEqual((tmp / ".env").read_text(encoding="utf-8"), ENV)
        for f in FICHIERS_VERSION:
            if f != "update.sh":
                self.assertEqual((tmp / f).read_bytes(), version_des_fichiers("9.9.0")[f], f)
        self.assertFalse([a for v, a in self.appels(tmp) if "pull" in a or " up " in f" {a} "])
        self.assertFalse(list(tmp.glob(".download*")))

    def test_derniere_version_introuvable_rien_ne_change(self):
        tmp, depot, env = self.preparer(derniere=None)
        r = self.update(tmp, env)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.appels(tmp), [])

    def test_clone_git_avec_image_publiee_comme_avant(self):
        tmp, depot, env = self.preparer(git=True)
        r = self.update(tmp, env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(depot.demandes, [])
        self.assertEqual((tmp / ".env").read_text(encoding="utf-8"), ENV)
        self.assertIn("compose pull web", [a for v, a in self.appels(tmp)])
        # --version n'a pas de sens dans un clone Git : refusé, rien ne change
        r = self.update(tmp, env, "--version", "9.9.1")
        self.assertEqual(r.returncode, 2)

    def test_sans_image_publiee_construction_comme_avant(self):
        for env_fichier in ("IMAGE=\n", "IMAGE=ghcr.io/exemple/outil:9.9.0\n", f"IMAGE={IMAGE_PUBLIQUE}:latest\n"):
            with self.subTest(env_fichier):
                tmp, depot, env = self.preparer(env_fichier=env_fichier)
                r = self.update(tmp, env)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertEqual(depot.demandes, [])
                attendu = "compose build web" if env_fichier == "IMAGE=\n" else "compose pull web"
                self.assertIn(attendu, [a for v, a in self.appels(tmp)])
