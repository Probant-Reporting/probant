"""Droits des fichiers : bases, archives, exports, preuves et journaux en 0600, dossiers en
0700, quel que soit le masque du processus qui lance l'outil (« docker compose exec web python manage.py backup » créait
l'archive en 0666, constaté à l'essai Docker) ; au démarrage, ce qu'une version antérieure a créé est
resserré (``parametres.droits_fichiers.resserrer``)."""
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from django.core.files.base import ContentFile
from django.test import SimpleTestCase, TestCase, override_settings

from collecte.aides_tests import jeu_trois_niveaux as J
from collecte.models import Preuve, Reponse

from . import droits_fichiers as DF
from .aides_tests.hebergement import RACINE, DossiersTemporaires, environnement_propre

POSIX = os.name == "posix"


def mode(p):
    return stat.S_IMODE(os.lstat(p).st_mode)


@unittest.skipUnless(POSIX, "droits POSIX")
class CommandesAvecMasqueOuvert(SimpleTestCase):
    def test_migrate_puis_backup_lances_avec_le_masque_000(self):
        """Comme « docker compose exec … » : le processus arrive avec un masque qui laisse tout le monde lire et écrire.
        Bases, clé, archive et dossiers sont quand même créés pour l'utilisateur de l'outil seul."""
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        env = {**environnement_propre(), "DATA_DIR": str(tmp / "donnees")}
        (tmp / "donnees").mkdir()  # le volume des données (/data dans l'image) existe déjà

        def lancer(*args):
            r = subprocess.run([sys.executable, "manage.py", *args], cwd=RACINE, env=env, capture_output=True, text=True,
                               timeout=300, preexec_fn=lambda: os.umask(0))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            return r.stdout

        lancer("migrate", "-v", "0")
        lancer("backup", "--reason", "essai")
        d = tmp / "donnees"
        archives = list((d / "backups").glob("backup-*-essai.zip"))
        self.assertEqual(len(archives), 1)
        for f in [d / "db.sqlite3", d / "shared.sqlite3", d / ".secret_key", archives[0]]:
            self.assertEqual(oct(mode(f)), "0o600", f.name)
        dossiers = [p for p in d.rglob("*") if p.is_dir()]
        self.assertIn(d / "backups", dossiers)
        for dossier in dossiers:
            self.assertEqual(oct(mode(dossier)), "0o700", dossier.name)
        for f in [p for p in d.rglob("*") if p.is_file()]:  # tout le reste aussi (cache des essais de connexion…)
            self.assertEqual(oct(mode(f) & 0o077), "0o0", f.name)


@unittest.skipUnless(POSIX, "droits POSIX")
class PreuveDeposee(DossiersTemporaires, TestCase):
    def test_preuve_et_son_dossier(self):
        J.charger()
        r = Reponse.objects.exclude(valeur=None).first()
        p = Preuve.objects.create(reponse=r, fichier=ContentFile(b"%PDF-1.4 preuve fictive", name="facture.pdf"))
        chemin = Path(p.fichier.path)
        self.assertEqual(oct(mode(chemin)), "0o600")
        self.assertEqual(oct(mode(chemin.parent)), "0o700")


@unittest.skipUnless(POSIX, "droits POSIX")
class Resserrer(SimpleTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        d = self.d = self.tmp / "donnees"
        self.reglages = override_settings(DOSSIER_DONNEES=d, MEDIA_ROOT=d / "files", SAUVEGARDES_DIR=d / "backups",
                                          ESPACES_DOSSIER=d / "spaces-data", IA_CLES_DIR=d / "ai-keys")
        self.reglages.enable()
        self.addCleanup(self.reglages.disable)

    def poser(self, chemin, m, contenu=b"x"):
        chemin.parent.mkdir(parents=True, exist_ok=True)
        if contenu is None:
            chemin.mkdir(exist_ok=True)
        else:
            chemin.write_bytes(contenu)
        os.chmod(chemin, m)
        return chemin

    def test_fichiers_d_une_version_anterieure(self):
        d = self.d
        os.makedirs(d, exist_ok=True)
        os.chmod(d, 0o755)
        outil = {
            self.poser(d / "db.sqlite3", 0o644): "0o600",
            self.poser(d / "db.sqlite3-wal", 0o644): "0o600",
            self.poser(d / "README.txt", 0o644): "0o600",
            self.poser(d / "backups" / "backup-20261116-120000.zip", 0o666): "0o600",
            self.poser(d / "backups" / "restores.jsonl", 0o644): "0o600",
            self.poser(d / "backups" / "shared" / "registry-20261116-120000.zip", 0o644): "0o600",
            self.poser(d / "files" / "evidence" / "2026" / "f.pdf", 0o640): "0o600",
            self.poser(d / "files" / "evidence", 0o755, None): "0o700",
            self.poser(d / "spaces-data" / "achats" / "database.sqlite3", 0o644): "0o600",
            self.poser(d / "sign-in-attempts" / "a.djcache", 0o664): "0o600",
            self.poser(d / "backups" / "script.sh", 0o755): "0o700",  # droits du propriétaire gardés
            d: "0o700",
        }
        autre = self.poser(d / "autre-logiciel" / "notes.txt", 0o644)  # dossier inconnu : pas touché
        dehors = self.poser(self.tmp / "dehors.txt", 0o644)
        os.symlink(dehors, d / "files" / "lien.txt")  # lien : jamais suivi
        n = DF.resserrer()
        for chemin, attendu in outil.items():
            self.assertEqual(oct(mode(chemin)), attendu, chemin)
        self.assertEqual(oct(mode(autre)), "0o644")
        self.assertEqual(oct(mode(dehors)), "0o644")
        self.assertGreaterEqual(n, len(outil))
        self.assertEqual(DF.resserrer(), 0)  # rien de plus au démarrage suivant
