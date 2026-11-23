"""Image Docker : aucune copie de sauvegarde ni de base posée dans le dossier de l'outil n'entre dans l'image.

Constaté à l'essai de l'installation, en suivant le guide à la lettre : « docker compose cp
web:/data/backups ./backups-copy » écrivait les archives (base complète, empreintes des mots de passe) dans le dossier de
l'outil ; le « ./update.sh » suivant reconstruisait l'image avec ce dossier (contexte de construction « . »), et les
archives se retrouvaient dans l'image, dans /app/backups-copy. Même risque pour une archive téléchargée posée là avant
« docker compose cp archive.zip web:/data/backups/ », et pour « pg_dump … > failed-update.dump » (guide, section 6).

Contrôles : le guide (anglais et français) copie les sauvegardes hors du dossier de l'outil, et ``.dockerignore`` écarte
toute archive ``.zip`` et tout ``.dump``, où qu'ils soient, sans écarter un fichier suivi par git."""
import re
import subprocess
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

RACINE = Path(settings.BASE_DIR)


def motifs():
    lignes = (RACINE / ".dockerignore").read_text(encoding="utf-8").splitlines()
    return [ligne.strip() for ligne in lignes if ligne.strip() and not ligne.strip().startswith("#")]


def _regex(motif):
    """Motif de .dockerignore (syntaxe de Go filepath.Match, plus « ** ») en expression régulière sur un chemin relatif."""
    motif = motif.strip("/")
    sortie, i = "", 0
    while i < len(motif):
        if motif.startswith("**/", i):
            sortie, i = sortie + "(?:.*/)?", i + 3
        elif motif.startswith("**", i):
            sortie, i = sortie + ".*", i + 2
        elif motif[i] == "*":
            sortie, i = sortie + "[^/]*", i + 1
        elif motif[i] == "?":
            sortie, i = sortie + "[^/]", i + 1
        else:
            sortie, i = sortie + re.escape(motif[i]), i + 1
    return re.compile(sortie + r"\Z")


def ecarte(chemin):
    """Vrai si ``chemin`` (relatif au dossier de l'outil) n'entre pas dans l'image : un motif qui écarte un dossier écarte
    tout ce qu'il contient ; le dernier motif qui s'applique l'emporte (« ! » réintègre)."""
    parties = chemin.split("/")
    prefixes = ["/".join(parties[: n + 1]) for n in range(len(parties))]
    resultat = False
    for m in motifs():
        negation = m.startswith("!")
        r = _regex(m[1:] if negation else m)
        if any(r.match(p) for p in prefixes):
            resultat = not negation
    return resultat


class DockerignoreCopiesTests(SimpleTestCase):
    def test_archives_et_vidages_poses_dans_le_dossier_ecartes(self):
        for chemin in ("backups-copy/backup-20261116-023000-auto.zip", "backups-copy/shared/registry-20261116-023000.zip",
                       "copie-sauvegardes/spaces/achats/backup-20261116-023000-auto.zip", "archive.zip",
                       "backup-20261026-023000-auto.zip", "failed-update.dump", "sauvegardes/x.dump"):
            with self.subTest(chemin=chemin):
                self.assertTrue(ecarte(chemin), f"{chemin} entrerait dans l'image")

    def test_aucun_fichier_suivi_ecarte_sauf_les_reglages_de_developpement(self):
        try:
            suivis = subprocess.run(["git", "ls-files"], cwd=RACINE, capture_output=True, text=True, check=True).stdout.split()
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("git indisponible")
        # dossiers déjà écartés exprès avant ce test (.git, .github, .devcontainer), et désormais les notes
        # des assistants (.claude, .impeccable : test_dockerfile_code_en_lecture_seule)
        ecartes = [p for p in suivis if ecarte(p)
                   and not p.startswith((".github/", ".devcontainer/", ".claude/", ".impeccable/"))]
        self.assertEqual(ecartes, [])
        self.assertFalse(ecarte(".env.example"))

    def test_le_guide_copie_les_sauvegardes_hors_du_dossier_de_l_outil(self):
        for guide in ("docs/installation.md", "docs/fr/installation.md"):
            texte = (RACINE / guide).read_text(encoding="utf-8")
            copies = re.findall(r"docker compose cp web:/data/backups\S*\s+(\S+?)`", texte)
            with self.subTest(guide=guide):
                self.assertTrue(copies, "commande de copie des sauvegardes introuvable")
                for destination in copies:
                    self.assertTrue(destination.startswith(("../", "/")), destination)
