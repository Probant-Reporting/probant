"""Droits des fichiers de l'installation après une mise à jour automatique (``auto-update.sh``, qui pose ``umask 077``
pour ses propres fichiers, puis lance ``update.sh``) : les fichiers de la nouvelle version ont les droits que leur donne
``get.sh`` (0644, scripts en 0755) et gardent le propriétaire d'avant (tâche lancée par root, installation d'un membre
du groupe docker) ; ce qui doit rester privé le reste (``.env``, dossier de travail de la mise à jour automatique, son
journal). Sinon un membre non root du groupe docker ne peut plus lancer ``docker compose`` dans le dossier."""
import os
import stat
import unittest

from django.test import SimpleTestCase

from parametres.aides_tests.mise_a_jour_auto import AidesMiseAJourAuto, fichier

PUBLICS = ("docker-compose.yml", ".env.example", "docker/Caddyfile")
SCRIPTS = ("install.sh", "update.sh", "check.sh", "auto-update.sh")
PROPRIETAIRE = (4321, 4322)  # un membre du groupe docker, pas root


def droits(chemin):
    return stat.S_IMODE(os.stat(chemin).st_mode)


class MiseAJourAutoDroitsFichiersTests(AidesMiseAJourAuto, SimpleTestCase):
    def preparer(self, proprietaire=None):
        tmp, dossier, env = self.installation()
        for f in PUBLICS:
            os.chmod(dossier / f, 0o644)
        for f in SCRIPTS:
            os.chmod(dossier / f, 0o755)
        os.chmod(dossier / ".env", 0o600)
        os.chmod(dossier, 0o755)  # comme après get.sh (umask habituel, 022) ; celui des tests est 077
        os.chmod(dossier / "docker", 0o755)
        if proprietaire:
            for racine, dossiers, fichiers in os.walk(dossier):
                for nom in [*dossiers, *fichiers]:
                    os.chown(os.path.join(racine, nom), *proprietaire)
            os.chown(dossier, *proprietaire)
        return tmp, dossier, env

    def mettre_a_jour(self, dossier, env, tmp):
        r = self.lancer_auto(dossier, env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.resultat(tmp)["state"], "updated", fichier(dossier / "auto-update.log"))
        self.assertIn("# files of version 9.9.1", fichier(dossier / "docker-compose.yml"))

    def test_droits_des_fichiers_comme_apres_get_sh(self):
        tmp, dossier, env = self.preparer()
        self.mettre_a_jour(dossier, env, tmp)
        for f in PUBLICS:
            self.assertEqual(oct(droits(dossier / f)), oct(0o644), f)
        for f in SCRIPTS:
            self.assertEqual(oct(droits(dossier / f)), oct(0o755), f)
        self.assertEqual(oct(droits(dossier / "docker")), oct(0o755))
        # ce qui reste privé
        self.assertEqual(oct(droits(dossier / ".env")), oct(0o600))
        self.assertEqual(oct(droits(dossier / ".auto-update")), oct(0o700))
        self.assertEqual(oct(droits(dossier / "auto-update.log")), oct(0o600))
        self.assertEqual(oct(droits(dossier / ".auto-update" / "previous" / ".env")), oct(0o600))

    @unittest.skipUnless(os.geteuid() == 0, "changer le propriétaire d'un fichier demande root")
    def test_proprietaire_d_avant_garde(self):
        tmp, dossier, env = self.preparer(PROPRIETAIRE)
        self.mettre_a_jour(dossier, env, tmp)
        for f in (*PUBLICS, *SCRIPTS, ".env"):
            st = os.stat(dossier / f)
            self.assertEqual((st.st_uid, st.st_gid), PROPRIETAIRE, f)
