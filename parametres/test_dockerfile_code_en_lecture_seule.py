"""Image Docker : le code (/app) appartient à root et l'utilisateur de l'outil (probant) ne peut
pas le modifier ; seul le dossier des données (/data) lui appartient. Avant : « COPY --chown=probant:probant . . » donnait tout le
code à l'utilisateur de l'outil (une faille dans l'outil pouvait réécrire son propre code, qui serait exécuté au
démarrage suivant). Les notes des assistants de développement (.claude, .impeccable) n'entrent plus dans l'image.

Contrôle du Dockerfile et de .dockerignore ici ; essai réel dans ``docker/test_installation.sh`` (TESTER_DOCKER=1)."""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from .test_dockerignore_copies import ecarte

RACINE = Path(settings.BASE_DIR)


def instructions():
    """Instructions du Dockerfile (lignes continuées réunies), sans les commentaires."""
    texte = (RACINE / "Dockerfile").read_text(encoding="utf-8")
    lignes = [ligne for ligne in texte.splitlines() if not ligne.lstrip().startswith("#")]
    return [i.strip() for i in re.sub(r"\\\n", " ", "\n".join(lignes)).splitlines() if i.strip()]


class DockerfileTests(SimpleTestCase):
    def test_code_a_root_donnees_a_l_outil(self):
        ins = instructions()
        copies = [i for i in ins if i.startswith("COPY")]
        self.assertTrue(copies)
        for i in copies:
            self.assertNotIn("--chown", i)  # le code reste à root
        user = next(n for n, i in enumerate(ins) if i.startswith("USER "))
        self.assertEqual(ins[user], "USER probant")
        # rien n'est copié ni construit dans /app après le passage à l'utilisateur de l'outil
        self.assertFalse([i for i in ins[user:] if i.startswith(("COPY", "ADD", "RUN"))])
        avant = " ".join(ins[:user])
        self.assertIn("chown probant:probant /data", avant)  # seul le dossier des données lui appartient
        self.assertRegex(avant, r"chmod -R a\+rX,go-w /app")  # code lisible par tous, modifiable par root seul
        self.assertIn("collectstatic", avant)  # fichiers statiques construits dans l'image, jamais au démarrage
        # pas de fichiers .pyc écrits à côté du code (il ne le pourrait d'ailleurs plus)
        self.assertIn("PYTHONDONTWRITEBYTECODE=1", " ".join(i for i in ins if i.startswith("ENV")))

    def test_notes_des_assistants_hors_de_l_image(self):
        for chemin in (".claude/regles_agents.md", ".claude/skills/library-template/SKILL.md",
                       ".claude/worktrees/autre/manage.py", ".impeccable/design.json", ".impeccable/critique/x.md"):
            self.assertTrue(ecarte(chemin), chemin)
        for chemin in ("manage.py", "docs/guides/administrator.md", "static/css/outil.css", "libelles/admin.en.json"):
            self.assertFalse(ecarte(chemin), chemin)

    def test_le_demarrage_n_ecrit_pas_dans_le_code(self):
        """Point d'entrée : ni collectstatic, ni compilation, ni fichier écrit sous /app au démarrage."""
        entree = (RACINE / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
        self.assertNotIn("collectstatic", entree)
        self.assertNotIn("compilemessages", entree)
        self.assertIn("umask 077", entree)
