"""Workflows GitHub du dépôt public (``.github/workflows/``) : ce qu'ils appellent existe, et ils restent sûrs.

Les workflows ne tournent que sur GitHub : une faute (script renommé, commande de l'outil qui n'existe pas, test du
navigateur que le motif ne trouve pas) ne se voit qu'après l'envoi. Ce test la trouve avant, sans réseau ni Docker.
Lecture du texte (pas d'analyseur YAML dans les dépendances) : chaque tâche est le bloc indenté de deux espaces sous
``jobs:``."""
import os
import re
from pathlib import Path

from django.conf import settings
from django.core.management import get_commands
from django.test import SimpleTestCase

RACINE = Path(settings.BASE_DIR)
WORKFLOWS = RACINE / ".github" / "workflows"


def texte(nom):
    return (WORKFLOWS / nom).read_text(encoding="utf-8")


def tache(nom_fichier, tache_id):
    """Le bloc de la tâche ``tache_id`` (de sa ligne ``  <id>:`` à la tâche suivante)."""
    t = texte(nom_fichier)
    m = re.search(rf"^  {re.escape(tache_id)}:\n(.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)", t, re.M | re.S)
    if not m:
        raise AssertionError(f"tâche {tache_id} absente de {nom_fichier}")
    return m.group(1)


class TacheDockerTests(SimpleTestCase):
    def setUp(self):
        self.bloc = tache("tests.yml", "docker")

    def test_nom_et_deux_bases(self):
        self.assertIn("name: Docker (install, update, backup, restore)", self.bloc)
        self.assertRegex(self.bloc, r"database: \[sqlite, postgresql\]")
        self.assertIn("fail-fast: false", self.bloc)

    def test_scripts_appeles_existent(self):
        scripts = set(re.findall(r"(?:^|\s)\./([\w./-]+\.sh)\b", self.bloc)) | set(re.findall(r"bash ([\w./-]+\.sh)\b", self.bloc))
        self.assertTrue({"install.sh", "update.sh", "docker/check_sign_in.sh"} <= scripts, scripts)
        for s in scripts:
            chemin = RACINE / s
            self.assertTrue(chemin.is_file(), s)
        for s in ("install.sh", "update.sh"):
            self.assertTrue(os.access(RACINE / s, os.X_OK), f"{s} doit être exécutable (./{s})")

    def test_etapes_dans_l_ordre(self):
        etapes = ["./install.sh", "/sante/", "cat /app/VERSION", "manage.py load_demo", "check_sign_in.sh",
                  "manage.py backup", "manage.py restore", "./update.sh"]
        etapes_seules = self.bloc[self.bloc.index("steps:"):]
        positions = [etapes_seules.find(e) for e in etapes]
        self.assertNotIn(-1, positions, dict(zip(etapes, positions)))
        self.assertEqual(positions, sorted(positions))
        self.assertIn("if: failure()", self.bloc)
        self.assertIn("docker compose logs", self.bloc)

    def test_commandes_de_l_outil_existent(self):
        connues = set(get_commands())
        appelees = set(re.findall(r"manage\.py ([a-z_]+)", self.bloc))
        self.assertTrue(appelees)
        self.assertEqual(appelees - connues, set())

    def test_demo_chargee_par_la_commande_du_readme_public(self):
        # le README lu est celui que le public voit : à la racine d'une version publiée, sinon sa source
        source = RACINE / "publication" / "public" / "README.md"
        readme = (source if source.exists() else RACINE / "README.md").read_text(encoding="utf-8")
        commande = re.search(r"^\s*(docker compose exec web python manage\.py load_demo)\s*$", readme, re.M)
        self.assertIsNotNone(commande, "commande de la démo absente du README public")
        # même commande, avec -T : pas de terminal sur GitHub
        self.assertIn(commande.group(1).replace("exec web", "exec -T web"), self.bloc)

    def test_options_des_commandes_existent(self):
        aide_restore = (RACINE / "parametres" / "management" / "commands" / "restauration.py").read_text(encoding="utf-8")
        aide_backup = (RACINE / "parametres" / "management" / "commands" / "sauvegarde.py").read_text(encoding="utf-8")
        self.assertIn('"--yes"', aide_restore)
        self.assertIn('"--reason"', aide_backup)


class TacheNavigateurTests(SimpleTestCase):
    def test_tous_les_fichiers_du_navigateur(self):
        bloc = tache("tests.yml", "browser")
        self.assertIn('--pattern "test_navigateur_*.py"', bloc)
        self.assertIn('REQUIRE_BROWSER_TESTS: "1"', bloc)
        self.assertIn("AXE_JS:", bloc)
        self.assertNotRegex(bloc, r"collecte\.test_navigateur_\w+", "liste de fichiers : le motif les trouve tous")

    def test_chaque_test_du_navigateur_suit_le_motif(self):
        """Un fichier qui lance Chromium s'appelle test_navigateur_*.py, sinon la tâche ne le jouerait pas."""
        marques = ("aides_tests.navigateur", "aides_tests import navigateur", "sync_playwright", "navigateur_indisponible")
        hors_motif = []
        for p in RACINE.glob("*/test_*.py"):
            if p.name.startswith("test_navigateur_") or p.name == Path(__file__).name:
                continue
            t = p.read_text(encoding="utf-8")
            if any(m in t for m in marques):
                hors_motif.append(p.relative_to(RACINE).as_posix())
        self.assertEqual(hors_motif, [])
        self.assertTrue(list(RACINE.glob("*/test_navigateur_*.py")))


class VersionToutEnUnTests(SimpleTestCase):
    def test_archives_jointes_a_la_release_avec_des_noms_stables(self):
        t = texte("portable.yml")
        self.assertRegex(t, r"release:\n\s+types: \[published\]")
        self.assertIn("workflow_dispatch:", t)
        # chaque archive est fabriquée et essayée sur son système (Windows, Mac), puis jointe à la release
        for archive in ("probant-windows.zip", "probant-mac.zip"):
            self.assertIn(f'gh release upload "$TAG" {archive} --clobber', t)
        self.assertRegex(t, r"(?m)^  windows:\n    runs-on: windows-latest$")
        self.assertRegex(t, r"(?m)^  mac:\n    runs-on: macos-latest$")
        self.assertIn("zip -r -y", t, "archive Mac : liens et droits d'exécution gardés")
        # dossiers fabriqués par build_package.py, mis dans les archives
        recette = (RACINE / "portable" / "build_package.py").read_text(encoding="utf-8")
        for dossier in ("Probant-windows", "Probant-mac"):
            self.assertIn(f'"{dossier}"', recette)
            self.assertIn(dossier, t)

    def test_le_readme_du_paquet_dit_essai(self):
        lisez_moi = (RACINE / "portable" / "README.txt").read_text(encoding="utf-8")
        self.assertIn("TRIAL VERSION", lisez_moi)
        self.assertIn("Not for use by several people", lisez_moi)


class SecuriteDesWorkflowsTests(SimpleTestCase):
    def test_permissions_et_actions(self):
        for p in sorted(WORKFLOWS.glob("*.yml")):
            t = p.read_text(encoding="utf-8")
            with self.subTest(p.name):
                self.assertRegex(t, r"(?m)^permissions:\n  contents: read$", "droits par défaut en lecture seule")
                self.assertNotRegex(t, r"pull_request_target", "pull_request_target donnerait les secrets aux forks")
                self.assertRegex(t, r"(?m)^concurrency:", "une exécution à la fois par branche ou par version")
                for action in re.findall(r"uses: ([^\s]+)", t):
                    self.assertRegex(action, r"@v\d+$", f"{action} : version majeure fixée, jamais une branche")
                # les entrées d'une exécution à la demande ne vont jamais telles quelles dans un script
                for ligne in t.splitlines():
                    if "${{ inputs." in ligne or "${{ github.event.release." in ligne:
                        self.assertNotRegex(ligne.strip(), r"^(run:|[^:]*\$\(|gh |echo )", ligne)

    def test_secret_des_noms_interdits_seulement_pour_les_suites(self):
        t = texte("tests.yml")
        self.assertNotRegex(t, r"(?m)^env:\n(?:  .*\n)*  PROBANT_FORBIDDEN", "secret au niveau du workflow : donné à toutes les tâches")
        for tache_id in ("sqlite", "postgresql"):
            self.assertIn("PROBANT_FORBIDDEN: ${{ secrets.PROBANT_FORBIDDEN }}", tache("tests.yml", tache_id))
        for tache_id in ("browser", "docker", "lint", "audit"):
            self.assertNotIn("secrets.", tache("tests.yml", tache_id))
