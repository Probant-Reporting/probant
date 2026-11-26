"""Contrôle « on peut sauter des versions » (qa/update_from_published.py) : retrouver le code d'une version publiée, par
son étiquette ``vX.Y.Z`` (dépôt public) ou, à défaut, par l'historique du fichier VERSION (atelier). Dépôt d'essai
temporaire, sans réseau."""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from qa import update_from_published as UP

ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@exemple.test", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@exemple.test", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}


class SourceDeVersion(SimpleTestCase):

    def setUp(self):
        self.depot = Path(tempfile.mkdtemp(prefix="source-version-"))
        self.addCleanup(shutil.rmtree, self.depot, True)
        self.numero = 0
        self.git("init", "-q", "-b", "main")

    def git(self, *args):
        r = subprocess.run(["git", "-C", str(self.depot), "-c", "commit.gpgsign=false", *args], env=ENV, capture_output=True,
                           text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def commit(self, version=None, code="x"):
        """Un commit : le fichier de code change, et VERSION si ``version`` est donné. Renvoie le commit."""
        self.numero += 1
        (self.depot / "code.txt").write_text(f"{code} {self.numero}", encoding="utf-8")
        if version:
            (self.depot / "VERSION").write_text(version + "\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", f"commit {code}")
        return self.git("rev-parse", "HEAD")

    def test_dernier_commit_qui_portait_le_numero(self):
        a = self.commit("3.0.0")
        b = self.commit()  # du code de plus sous le même numéro
        self.commit("3.1.0")
        self.commit()
        self.assertEqual(UP.source_de("3.0.0", self.depot)[0], b)
        self.assertNotEqual(b, a)

    def test_numero_du_commit_courant(self):
        self.commit("3.0.0")
        tete = self.commit("3.1.0")
        self.assertEqual(UP.source_de("3.1.0", self.depot), (tete, "current commit (its VERSION file)"))

    def test_numero_quitte_par_un_commit_plus_recent(self):
        self.commit("3.0.0")
        dernier = self.commit()
        self.commit("3.1.0")
        self.commit("3.2.0")
        self.assertEqual(UP.source_de("3.0.0", self.depot)[0], dernier)
        self.assertEqual(UP.source_de("3.1.0", self.depot)[1], "last commit with this VERSION")

    def test_l_etiquette_passe_avant_l_historique(self):
        premier = self.commit("3.0.0")
        self.commit()
        self.commit("3.1.0")
        self.git("tag", "v3.0.0", premier)
        self.assertEqual(UP.source_de("3.0.0", self.depot), (premier, "tag v3.0.0"))

    def test_etiquette_en_majuscule_comme_dans_le_depot_public(self):
        """Dans le dépôt public, une étiquette a été posée avec un V majuscule (VX.Y.Z) : elle est acceptée, après vX.Y.Z,
        comme le font les scripts d'installation."""
        v1 = self.commit("3.0.0")
        self.git("tag", "v3.0.0")
        v2 = self.commit("3.0.1")
        self.git("tag", "V3.0.1")
        self.commit("3.1.0")
        self.assertEqual(UP.source_de("3.0.0", self.depot), (v1, "tag v3.0.0"))
        self.assertEqual(UP.source_de("3.0.1", self.depot), (v2, "tag V3.0.1"))

    def test_l_etiquette_en_minuscule_passe_avant_la_majuscule(self):
        premier = self.commit("3.0.0")
        second = self.commit()
        self.git("tag", "V3.0.0", premier)
        self.git("tag", "v3.0.0", second)
        self.commit("3.1.0")
        self.assertEqual(UP.source_de("3.0.0", self.depot), (second, "tag v3.0.0"))

    def test_depot_public_un_commit_par_version_avec_etiquettes(self):
        v1 = self.commit("3.0.0")
        self.git("tag", "v3.0.0")
        self.commit("3.0.1")
        self.git("tag", "v3.0.1")
        tete = self.commit("3.1.0")  # pas encore d'étiquette : c'est le commit courant
        self.assertEqual(UP.source_de("3.0.0", self.depot)[0], v1)
        self.assertEqual(UP.source_de("3.1.0", self.depot)[0], tete)

    def test_version_sans_code(self):
        self.commit("3.0.0")
        self.commit("3.1.0")
        self.assertIsNone(UP.source_de("9.9.9", self.depot))

    def test_extraire_code_ne_prend_que_le_commit(self):
        a = self.commit("3.0.0", code="ancien")
        self.commit("3.1.0", code="nouveau")
        cible = self.depot.parent / (self.depot.name + "-sortie")
        self.addCleanup(shutil.rmtree, cible, True)
        # extraire_code travaille dans le dépôt de l'outil : on essaie sur le dépôt d'essai en changeant la racine
        ancienne, UP.RACINE = UP.RACINE, self.depot
        try:
            UP.extraire_code(a, cible / "code")
        finally:
            UP.RACINE = ancienne
        self.assertEqual((cible / "code" / "VERSION").read_text().strip(), "3.0.0")
        self.assertTrue((cible / "code" / "code.txt").read_text().startswith("ancien"))
