"""Le contrôle du serveur (``check.sh``) dans ``install.sh`` et ``get.sh``.

- ``./install.sh --check`` : le contrôle seul, avec les options de l'installation ; rien ne change.
- Une installation neuve commence par le contrôle et s'arrête, sans rien installer, sur un point à corriger ;
  ``--skip-check`` passe outre ; une installation existante (``.env`` présent) ne le refait pas.
- ``get.sh --check`` : le contrôle de la version, depuis un dossier temporaire supprimé à la fin ; aucun dossier créé.

Faux programmes du contrôle : ``parametres/aides_tests/faux_diagnostic.py`` ; faux ``docker`` des installations :
``scripts_installation.FAUX_DOCKER``."""
import shutil

from django.test import SimpleTestCase

from parametres.aides_tests.faux_diagnostic import FAUX, journal_reseau, preparer_faux
from parametres.aides_tests.scripts_installation import (
    FAUX_DOCKER, FICHIERS_VERSION, IMAGE_PUBLIQUE, RACINE, AidesScripts, ecrire_executable, version_des_fichiers)


class InstallShDiagnosticTests(AidesScripts, SimpleTestCase):
    def preparer(self, **valeurs):
        tmp = self.dossier()
        for f in ("install.sh", "check.sh", ".env.example", "docker-compose.yml"):
            shutil.copy(RACINE / f, tmp / f)
        chemin, variables = preparer_faux(tmp)
        # docker : réponses du contrôle (faux du diagnostic), puis le faux docker de l'installation qui note ses appels
        ecrire_executable(tmp / "faux-diagnostic" / "docker", r"""#!/bin/sh
case "$*" in
  "version --format"*|"info --format"*|"compose version"*) exec "$FAUX_DOCKER_DIAGNOSTIC" "$@" ;;
esac
exec "$FAUX_DOCKER_INSTALLATION" "$@"
""")
        ecrire_executable(tmp / "docker-diagnostic", FAUX["docker"])
        ecrire_executable(tmp / "docker-installation", FAUX_DOCKER)
        variables.update(FAUX_DOCKER_DIAGNOSTIC=str(tmp / "docker-diagnostic"),
                         FAUX_DOCKER_INSTALLATION=str(tmp / "docker-installation"), **valeurs)
        return tmp, self.environnement(tmp, chemin=chemin, diagnostic=True, **variables)

    def install(self, tmp, env, *options):
        return self.lancer(["sh", "install.sh", *options], cwd=tmp, env=env)

    def appels_docker(self, tmp):
        return [a.split("|", 1)[1] for a in self.appels(tmp)]

    def test_check_seul_ne_change_rien(self):
        tmp, env = self.preparer()
        r = self.install(tmp, env, "--check", "--image", f"{IMAGE_PUBLIQUE}:9.9.1", "--port", "8090")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Port 8090: free", r.stdout)
        self.assertIn("ghcr.io (image)", r.stdout)
        self.assertFalse((tmp / ".env").exists())
        self.assertEqual(self.appels_docker(tmp), [])

    def test_check_seul_code_de_sortie(self):
        tmp, env = self.preparer(F_MEMOIRE="400")
        r = self.install(tmp, env, "--check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Here is what is missing:", r.stdout)
        self.assertIn("registry-1.docker.io", r.stdout)  # sans image : construction sur le serveur
        self.assertFalse((tmp / ".env").exists())

    def test_installation_neuve_arretee_sur_un_point_bloquant(self):
        tmp, env = self.preparer(F_ECOUTE="8000")
        r = self.install(tmp, env, "--image", f"{IMAGE_PUBLIQUE}:9.9.1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Port 8000: used by another program", r.stdout)
        self.assertIn("Nothing was installed.", r.stdout)
        self.assertIn("--skip-check", r.stdout)
        self.assertFalse((tmp / ".env").exists())
        self.assertEqual(self.appels_docker(tmp), [])

    def test_installation_neuve_controle_puis_installation(self):
        tmp, env = self.preparer()
        r = self.install(tmp, env, "--image", f"{IMAGE_PUBLIQUE}:9.9.1", "--port", "8090")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertLess(r.stdout.index("Ready"), r.stdout.index(".env file created"))
        self.assertIn("Port 8090: free", r.stdout)
        self.assertIn("compose pull web", self.appels_docker(tmp))

    def test_skip_check_passe_outre(self):
        tmp, env = self.preparer(F_ECOUTE="8000")
        r = self.install(tmp, env, "--skip-check", "--image", f"{IMAGE_PUBLIQUE}:9.9.1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("Port 8000", r.stdout)
        self.assertIn("compose up -d", self.appels_docker(tmp))

    def test_installation_existante_pas_de_controle(self):
        """Avec un .env, l'outil tourne déjà et occupe son port : le contrôle d'avant l'installation n'a pas de sens."""
        tmp, env = self.preparer(F_ECOUTE="8000")
        (tmp / ".env").write_text(f"IMAGE={IMAGE_PUBLIQUE}:9.9.1\n", encoding="utf-8")
        r = self.install(tmp, env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("Check of the server", r.stdout)
        self.assertEqual(journal_reseau(tmp), [])

    def test_docker_absent_le_controle_laisse_l_installeur_le_proposer(self):
        tmp, env = self.preparer()
        (tmp / "faux-diagnostic" / "docker").unlink()
        r = self.install(tmp, env, "--image", f"{IMAGE_PUBLIQUE}:9.9.1")
        self.assertEqual(r.returncode, 1)  # sans terminal ni --yes : refus de l'installeur, après le contrôle
        self.assertIn("offers to install it next", r.stdout)
        self.assertLess(r.stdout.index("Ready"), r.stdout.index("Docker is not installed."))

    def test_check_sh_absent(self):
        tmp, env = self.preparer()
        (tmp / "check.sh").unlink()
        r = self.install(tmp, env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("check.sh is missing", r.stdout)
        self.assertFalse((tmp / ".env").exists())


class GetShCheckTests(AidesScripts, SimpleTestCase):
    def test_check_de_la_version_rien_n_est_cree(self):
        tmp = self.dossier()
        depot = self.depot({"V9.9.1": version_des_fichiers("9.9.1")}, "V9.9.1")
        chemin, variables = preparer_faux(tmp, garder_curl=True)
        # registre de l'image : le dépôt factice lui-même (il répond en HTTP, comme un registre sur la machine)
        registre = depot.adresse.removeprefix("http://")
        env = self.environnement(tmp, depot, chemin=chemin, diagnostic=True, PROBANT_TEST_IMAGE=f"{registre}/probant",
                                 **variables)
        avant = sorted(p.name for p in tmp.iterdir())
        r = self.lancer(["sh", str(RACINE / "get.sh"), "--check", "--port", "8090"], cwd=tmp, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Check of the server before the installation", r.stdout)
        self.assertIn(f"{registre} (image): reachable", r.stdout)
        self.assertIn("Port 8090: free", r.stdout)
        self.assertIn("Ready", r.stdout)
        self.assertEqual(sorted(p.name for p in tmp.iterdir()), avant)  # pas de dossier probant/
        self.assertIn("/raw/refs/tags/V9.9.1/check.sh", depot.demandes)
        self.assertEqual(self.appels(tmp), [])  # aucune commande docker d'installation

    def test_check_code_de_sortie_et_point_a_corriger(self):
        tmp = self.dossier()
        depot = self.depot({"V9.9.1": version_des_fichiers("9.9.1")}, "V9.9.1")
        chemin, variables = preparer_faux(tmp, garder_curl=True)
        variables["F_ARCH"] = "aarch64"
        env = self.environnement(tmp, depot, chemin=chemin, diagnostic=True,
                                 PROBANT_TEST_IMAGE=f"{depot.adresse.removeprefix('http://')}/probant", **variables)
        r = self.lancer(["sh", str(RACINE / "get.sh"), "--check"], cwd=tmp, env=env)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("published image is for x86_64 only", r.stdout)
        self.assertFalse((tmp / "probant").exists())

    def test_skip_check_transmis_a_install(self):
        tmp = self.dossier()
        depot = self.depot({"V9.9.1": version_des_fichiers("9.9.1")}, "V9.9.1")
        env = self.environnement(tmp, depot, diagnostic=True)
        r = self.lancer(["sh", str(RACINE / "get.sh"), "--skip-check"], cwd=tmp, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("Check of the server", r.stdout)
        self.assertTrue((tmp / "probant" / ".env").exists())

    def test_check_sh_fait_partie_des_fichiers_de_la_version(self):
        self.assertIn("check.sh", FICHIERS_VERSION)

    def test_version_d_avant_le_controle(self):
        """Une version publiée avant check.sh (constaté contre le vrai dépôt public : sa dernière version n'a pas ce
        fichier, et get.sh disait « check the version and the network ») : un message qui dit pourquoi, rien d'installé."""
        ancienne = version_des_fichiers("9.8.0")
        del ancienne["check.sh"]
        ancienne["install.sh"] = b'#!/usr/bin/env sh\ncase "$1" in --domain) ;; --port) ;; esac\necho "Probant is running"\n'
        for options, message in ((["--check"], "came before the check of the server"),
                                 ([], "came before this way of installing")):
            with self.subTest(options):
                tmp = self.dossier()
                depot = self.depot({"V9.8.0": ancienne}, "V9.8.0")
                env = self.environnement(tmp, depot)
                r = self.lancer(["sh", str(RACINE / "get.sh"), *options], cwd=tmp, env=env)
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertIn(message, r.stdout)
                self.assertNotIn("check the version and the network", r.stdout)
                self.assertFalse(list((tmp / "probant").iterdir()) if (tmp / "probant").exists() else [])
                self.assertEqual(self.appels(tmp), [])
