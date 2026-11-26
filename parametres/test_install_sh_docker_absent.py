"""``install.sh`` : Docker absent, image publiée (``--image``), commit de la version.

Docker absent : le script propose de l'installer par la procédure officielle de Docker pour Debian et Ubuntu (dépôt apt
de Docker, vérifié par sa clé), jamais sans un « oui » (question au terminal, ou ``--yes``) ; il refuse proprement sur un
autre système ou sans droits d'administration. Joué avec un PATH où ``docker``, ``apt-get``, ``install``, ``dpkg``,
``curl``, ``sudo`` et ``id`` sont des faux qui notent leurs appels : aucune vraie commande d'administration ne part.
Le faux ``apt-get`` « installe » Docker en posant le faux ``docker``."""
import fcntl
import os
import pty
import shutil
import subprocess
import termios
from pathlib import Path

from django.test import SimpleTestCase

from parametres.aides_tests.scripts_installation import (
    FAUX_DOCKER, IMAGE_PUBLIQUE, RACINE, AidesScripts, chemin_sans, ecrire_executable)

ADMIN = ("docker", "apt-get", "install", "dpkg", "curl", "sudo", "id")

# chaque faux note « nom arguments » ; apt-get pose le faux docker quand il installe docker-ce
FAUX = {
    "apt-get": r"""#!/bin/sh
echo "apt-get $*" >> "$JOURNAL_ADMIN"
case "$*" in *docker-ce*) cp "$FAUX_DOCKER_SOURCE" "$(dirname "$0")/docker"; chmod 700 "$(dirname "$0")/docker" ;; esac
""",
    "install": r"""#!/bin/sh
echo "install $*" >> "$JOURNAL_ADMIN"
for a in "$@"; do case "$a" in /etc/*) ;; *docker.list) echo "list: $(cat "$a")" >> "$JOURNAL_ADMIN" ;; esac; done
exit 0
""",
    "dpkg": '#!/bin/sh\necho amd64\n',
    "curl": r"""#!/bin/sh
echo "curl $*" >> "$JOURNAL_ADMIN"
while [ $# -gt 0 ]; do [ "$1" = -o ] && { echo key > "$2"; shift; }; shift; done
""",
    "id": '#!/bin/sh\necho "${FAUX_UID:-0}"\n',
}
FAUX_SUDO = '#!/bin/sh\necho "sudo $*" >> "$JOURNAL_ADMIN"\nexec "$@"\n'

UBUNTU = 'NAME="Ubuntu"\nID=ubuntu\nID_LIKE=debian\nVERSION_CODENAME=noble\nUBUNTU_CODENAME=noble\n'
DEBIAN = 'NAME="Debian GNU/Linux"\nID=debian\nVERSION_CODENAME=bookworm\n'
FEDORA = 'NAME="Fedora Linux"\nID=fedora\nVERSION_ID=41\n'


class DockerAbsentTests(AidesScripts, SimpleTestCase):
    def preparer(self, systeme=UBUNTU, sudo=True, uid="0"):
        tmp = self.dossier()
        for f in ("install.sh", ".env.example", "docker-compose.yml"):
            shutil.copy(RACINE / f, tmp / f)
        faux = tmp / "faux-admin"
        faux.mkdir()
        for nom, texte in FAUX.items():
            ecrire_executable(faux / nom, texte)
        if sudo:
            ecrire_executable(faux / "sudo", FAUX_SUDO)
        source_docker = tmp / "docker-installe"
        source_docker.write_text(FAUX_DOCKER, encoding="utf-8")
        (tmp / "os-release").write_text(systeme, encoding="utf-8")
        chemin = f"{faux}{os.pathsep}{chemin_sans(tmp / 'systeme', ADMIN)}"
        env = self.environnement(tmp, chemin=chemin, JOURNAL_ADMIN=str(tmp / "admin.txt"), FAUX_UID=uid,
                                 FAUX_DOCKER_SOURCE=str(source_docker), PROBANT_TEST_OS_RELEASE=str(tmp / "os-release"))
        (tmp / "admin.txt").touch()
        return tmp, env

    def admin(self, tmp):
        return (tmp / "admin.txt").read_text(encoding="utf-8").splitlines()

    def test_le_path_des_tests_n_a_pas_docker(self):
        tmp, env = self.preparer()
        r = self.lancer(["sh", "-c", "command -v docker || echo absent"], cwd=tmp, env=env)
        self.assertEqual(r.stdout.strip(), "absent")

    def test_sans_terminal_ni_yes_rien_n_est_installe(self):
        tmp, env = self.preparer()
        r = self.lancer(["sh", "install.sh"], cwd=tmp, env=env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("Docker is not installed.", r.stdout)
        self.assertIn("--yes", r.stdout)
        self.assertEqual(self.admin(tmp), [])
        self.assertFalse((tmp / ".env").exists())

    def test_avec_yes_procedure_officielle_dans_l_ordre(self):
        tmp, env = self.preparer()
        r = self.lancer(["sh", "install.sh", "--yes", "--image", f"{IMAGE_PUBLIQUE}:9.9.1"], cwd=tmp, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.admin(tmp), [
            "apt-get update",
            "apt-get install -y ca-certificates curl",
            f"curl -fsSL --proto =https https://download.docker.com/linux/ubuntu/gpg -o {self.fichier_cle(tmp)}",
            "install -m 0755 -d /etc/apt/keyrings",
            f"install -m 0644 {self.fichier_cle(tmp)} /etc/apt/keyrings/docker.asc",
            f"install -m 0644 {self.fichier_cle(tmp)[:-len('docker.asc')]}docker.list /etc/apt/sources.list.d/docker.list",
            "list: deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu noble stable",
            "apt-get update",
            "apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin",
        ])
        # puis l'installation continue avec le Docker installé
        appels = [a.split("|", 1)[1] for a in self.appels(tmp)]
        self.assertIn("compose pull web", appels)
        self.assertIn("compose up -d", appels)

    def fichier_cle(self, tmp):
        ligne = next(x for x in self.admin(tmp) if x.startswith("curl "))
        return ligne.rsplit(" -o ", 1)[1]

    def test_debian(self):
        tmp, env = self.preparer(systeme=DEBIAN)
        r = self.lancer(["sh", "install.sh", "--yes"], cwd=tmp, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("list: deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable",
                      self.admin(tmp))

    def test_autre_systeme_refuse(self):
        tmp, env = self.preparer(systeme=FEDORA)
        r = self.lancer(["sh", "install.sh", "--yes"], cwd=tmp, env=env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("Debian and Ubuntu only", r.stdout)
        self.assertEqual(self.admin(tmp), [])

    def test_sans_droits_refuse(self):
        tmp, env = self.preparer(sudo=False, uid="1000")
        r = self.lancer(["sh", "install.sh", "--yes"], cwd=tmp, env=env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("administrator rights", r.stdout)
        self.assertEqual(self.admin(tmp), [])

    def test_compte_ordinaire_par_sudo(self):
        tmp, env = self.preparer(uid="1000")
        r = self.lancer(["sh", "install.sh", "--yes"], cwd=tmp, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        privilegiees = [x for x in self.admin(tmp) if x.startswith(("apt-get", "install"))]
        sudo = [x[len("sudo "):] for x in self.admin(tmp) if x.startswith("sudo ")]
        self.assertEqual(sudo, privilegiees)  # chaque commande d'administration passe par sudo, et elles seules
        self.assertEqual(len(sudo), 7)

    def repondre_au_terminal(self, tmp, env, reponse):
        """Lance install.sh avec un vrai terminal (pseudo-terminal de contrôle) et y tape ``reponse``."""
        maitre, esclave = pty.openpty()

        def terminal_de_controle():
            os.setsid()
            fcntl.ioctl(esclave, termios.TIOCSCTTY, 0)

        p = subprocess.Popen(["sh", "install.sh"], cwd=tmp, env=env, stdin=subprocess.DEVNULL, stdout=esclave,
                             stderr=esclave, preexec_fn=terminal_de_controle, pass_fds=(esclave,))
        os.close(esclave)
        sortie = b""
        try:
            while b"[y/N]" not in sortie:
                sortie += os.read(maitre, 1024)
            os.write(maitre, reponse.encode() + b"\n")
            p.wait(timeout=60)
            while True:
                try:
                    morceau = os.read(maitre, 1024)
                except OSError:
                    break
                if not morceau:
                    break
                sortie += morceau
        finally:
            if p.poll() is None:
                p.kill()
            os.close(maitre)
        return p.returncode, sortie.decode("utf-8", "replace")

    def test_question_non(self):
        tmp, env = self.preparer()
        code, sortie = self.repondre_au_terminal(tmp, env, "n")
        self.assertEqual(code, 1, sortie)
        self.assertIn("Docker not installed.", sortie)
        self.assertEqual(self.admin(tmp), [])

    def test_question_entree_seule_vaut_non(self):
        tmp, env = self.preparer()
        code, sortie = self.repondre_au_terminal(tmp, env, "")
        self.assertEqual(code, 1, sortie)
        self.assertEqual(self.admin(tmp), [])

    def test_question_oui(self):
        tmp, env = self.preparer()
        code, sortie = self.repondre_au_terminal(tmp, env, "y")
        self.assertEqual(code, 0, sortie)
        self.assertIn("apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin",
                      self.admin(tmp))


class ImageEtCommitTests(AidesScripts, SimpleTestCase):
    def preparer(self, git=False):
        tmp = self.dossier()
        for f in ("install.sh", ".env.example", "docker-compose.yml"):
            shutil.copy(RACINE / f, tmp / f)
        env = self.environnement(tmp)
        if git:
            ident = ["-c", "user.name=Essai", "-c", "user.email=essai@example.test"]
            for commande in (["init", "-q"], ["add", "."], [*ident, "commit", "-q", "-m", "essai"]):
                subprocess.run(["git", *commande], cwd=tmp, check=True, capture_output=True)
        return tmp, env

    def test_image_publiee_telechargee_jamais_construite(self):
        tmp, env = self.preparer()
        r = self.lancer(["sh", "install.sh", "--image", f"{IMAGE_PUBLIQUE}:9.9.1"], cwd=tmp, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.valeur(tmp / ".env", "IMAGE"), f"{IMAGE_PUBLIQUE}:9.9.1")
        appels = [a.split("|", 1)[1] for a in self.appels(tmp)]
        self.assertIn("compose pull web", appels)
        self.assertFalse([a for a in appels if "build" in a])

    def test_sans_git_aucune_ligne_vide_de_commit(self):
        """Avant : « VERSION_COMMIT= » (vide) écrit dans .env sans Git ; le fichier passant tout entier à l'outil, la valeur
        vide cachait le commit inscrit dans l'image publiée (dossier sans Git, IMAGE= réglé dans .env)."""
        tmp, env = self.preparer()
        (tmp / ".env").write_text(f"IMAGE={IMAGE_PUBLIQUE}:9.9.1\n", encoding="utf-8")
        r = self.lancer(["sh", "install.sh"], cwd=tmp, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIsNone(self.valeur(tmp / ".env", "VERSION_COMMIT"))

    def test_clone_git_commit_ecrit_comme_avant_et_image_construite(self):
        tmp, env = self.preparer(git=True)
        r = self.lancer(["sh", "install.sh"], cwd=tmp, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp, capture_output=True, text=True).stdout.strip()
        self.assertEqual(self.valeur(tmp / ".env", "VERSION_COMMIT"), commit)
        self.assertIn("compose build web", [a.split("|", 1)[1] for a in self.appels(tmp)])

    def test_env_existant_garde_seule_l_image_change(self):
        tmp, env = self.preparer()
        (tmp / ".env").write_text("DOMAIN=garde.example.com\nIMAGE=\n", encoding="utf-8")
        r = self.lancer(["sh", "install.sh", "--image", f"{IMAGE_PUBLIQUE}:9.9.1"], cwd=tmp, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(Path(tmp / ".env").read_text(encoding="utf-8"),
                         f"DOMAIN=garde.example.com\nIMAGE={IMAGE_PUBLIQUE}:9.9.1\n")
