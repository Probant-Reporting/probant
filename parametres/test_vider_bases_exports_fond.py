"""Version tout-en-un construite avec le dossier des données (``portable/build_package.py --data``, ``vider_bases``) : les
gros exports « prêts » de chaque base copiée passent « expirés » (leur fichier, dans files/exports, n'est jamais copié),
avec le motif que la page donne au clic (``collecte.exports_arriere_plan.FICHIER_ABSENT``). La base d'origine ne change
pas. Données inventées."""
import shutil
import sqlite3
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from collecte import exports_arriere_plan as EAP
from collecte.models import TacheExport

from .test_build_package_donnees import module


class ViderBasesExportsTests(SimpleTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def base(self, chemin):
        chemin.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(chemin)
        con.execute(f'CREATE TABLE "{TacheExport._meta.db_table}" (id INTEGER PRIMARY KEY, statut TEXT, erreur TEXT)')
        con.executemany(f'INSERT INTO "{TacheExport._meta.db_table}" (statut, erreur) VALUES (?, ?)',
                        [("pret", ""), ("attente", ""), ("expire", "droits")])
        con.commit()
        con.close()

    def lignes(self, chemin):
        con = sqlite3.connect(chemin)
        try:
            return con.execute(f'SELECT statut, erreur FROM "{TacheExport._meta.db_table}" ORDER BY id').fetchall()
        finally:
            con.close()

    def test_prets_expires_dans_la_copie(self):
        bp = module()
        self.assertEqual((bp.EXPORTS_FOND, bp.FICHIER_ABSENT), (TacheExport._meta.db_table, EAP.FICHIER_ABSENT))
        copie = self.tmp / "copie" / "db.sqlite3"
        self.base(copie)
        self.base(self.tmp / "copie" / "spaces-data" / "rh" / "database.sqlite3")
        bp.vider_bases(self.tmp / "copie")
        attendu = [("expire", EAP.FICHIER_ABSENT), ("attente", ""), ("expire", "droits")]
        self.assertEqual(self.lignes(copie), attendu)
        self.assertEqual(self.lignes(self.tmp / "copie" / "spaces-data" / "rh" / "database.sqlite3"), attendu)

    def test_base_sans_la_table(self):
        chemin = self.tmp / "vieille" / "db.sqlite3"
        chemin.parent.mkdir(parents=True)
        sqlite3.connect(chemin).close()
        self.assertEqual(module().vider_bases(self.tmp / "vieille"), [chemin])
