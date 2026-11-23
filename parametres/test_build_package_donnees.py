"""Version tout-en-un construite avec le dossier des données d'une installation (``portable/build_package.py --data``) :
jamais la clé secrète (nouveau et ancien nom), ni les clés de la prise IA, ni les gros exports ; table des jetons des
assistants (MCP) vidée dans chaque base copiée, comme dans la copie d'une sauvegarde."""
import importlib.util
import shutil
import sqlite3
import tempfile
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from . import sauvegardes as SV


def module():
    chemin = Path(settings.BASE_DIR) / "portable" / "build_package.py"
    spec = importlib.util.spec_from_file_location("build_package_essai", chemin)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def base(chemin, jetons=1):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(chemin)
    con.execute("CREATE TABLE serveur_mcp_jetonmcp (id INTEGER PRIMARY KEY, empreinte TEXT)")
    con.execute("CREATE TABLE collecte_reponse (id INTEGER PRIMARY KEY, valeur TEXT)")
    for n in range(jetons):
        con.execute("INSERT INTO serveur_mcp_jetonmcp (empreinte) VALUES (?)", (f"empreinte-secrete-{n}",))
    con.execute("INSERT INTO collecte_reponse (valeur) VALUES ('42')")
    con.commit()
    con.close()


class DonneesDuPaquetTests(SimpleTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        d = self.tmp / "data"
        for rel, contenu in ((".secret_key", "secret"), (".cle_secrete", "ancien secret"), ("ai-keys/principal.key", "sk-x"),
                             ("files/exports/gros.xlsx", "export"), ("files/evidence/preuve.pdf", "%PDF"),
                             ("spaces-data/rh/files/exports/gros.csv", "export"),
                             ("spaces-data/rh/files/evidence/p.pdf", "%PDF"),
                             ("backups/backup-20261101-000000-initial.zip", "zip")):
            (d / rel).parent.mkdir(parents=True, exist_ok=True)
            (d / rel).write_text(contenu)
        base(d / "db.sqlite3", 2)
        base(d / "spaces-data" / "rh" / "database.sqlite3")
        for nom in ("app", "libs", "python"):
            (self.tmp / nom).mkdir()
        self.d = d

    def test_ni_secrets_ni_exports_ni_jetons(self):
        bp = module()
        racine = bp.construire("Probant-essai", self.tmp / "out", self.tmp / "app", {"python": self.tmp / "python"},
                               self.tmp / "libs", [], {"mode": "data"}, self.d)
        data = racine / "data"
        for jamais in (".secret_key", ".cle_secrete", "ai-keys", "files/exports/gros.xlsx",
                       "spaces-data/rh/files/exports/gros.csv"):
            self.assertFalse((data / jamais).exists(), jamais)
        for garde in ("files/evidence/preuve.pdf", "spaces-data/rh/files/evidence/p.pdf",
                      "backups/backup-20261101-000000-initial.zip"):
            self.assertTrue((data / garde).exists(), garde)
        for f in (data / "db.sqlite3", data / "spaces-data" / "rh" / "database.sqlite3"):
            con = sqlite3.connect(f)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM serveur_mcp_jetonmcp").fetchone()[0], 0, f)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM collecte_reponse").fetchone()[0], 1, f)  # le reste reste
            con.close()
            self.assertNotIn(b"empreinte-secrete", f.read_bytes())  # effacé dans le fichier (secure_delete)
        con = sqlite3.connect(self.d / "db.sqlite3")  # la base d'origine n'est jamais touchée
        self.assertEqual(con.execute("SELECT COUNT(*) FROM serveur_mcp_jetonmcp").fetchone()[0], 2)
        con.close()

    def test_memes_tables_que_la_copie_d_une_sauvegarde(self):
        self.assertEqual(sorted(module().TABLES_VIDEES), sorted(SV._tables(SV.TABLES_VIDEES_DANS_LA_COPIE)))
