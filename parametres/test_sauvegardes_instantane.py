"""Sauvegarde JSON (PostgreSQL) lue dans un seul instantané : une écriture faite par une autre connexion pendant
l'export (entre deux tables) n'apparaît pas dans l'archive, ni dans ses comptes. Sans cela, une preuve, une alerte ou
une ligne du journal pourrait pointer vers une réponse absente de l'archive, et la restauration échouerait."""
import io
import json
import unittest
import zipfile
from unittest import mock

from django.conf import settings
from django.db import connections
from django.test import TransactionTestCase

from espaces import contexte as ESP

from . import sauvegardes as SV
from .models import Instance
from .aides_tests.hebergement import DossiersTemporaires

POSTGRESQL = settings.DATABASES["default"]["ENGINE"].endswith("postgresql")


@unittest.skipUnless(POSTGRESQL, "instantané REPEATABLE READ : PostgreSQL seulement (SQLite : copie par l'API de sauvegarde)")
class SauvegardeInstantane(DossiersTemporaires, TransactionTestCase):

    def setUp(self):
        super().setUp()
        Instance.courante()  # la ligne existe avant l'export
        Instance.objects.filter(pk=1).update(nom="Avant")
        self.ecrit = False

    def ecrire_ailleurs(self):
        """Une autre connexion (une autre requête du serveur) change l'identité et ajoute une ligne du journal."""
        autre = connections.create_connection(ESP.alias_courant())
        try:
            with autre.cursor() as c:
                c.execute(f"UPDATE {Instance._meta.db_table} SET nom = %s WHERE id = 1", ["Pendant"])
        finally:
            autre.close()
        self.ecrit = True

    def modeles_avec_arret(self, *a, **k):
        """Point d'arrêt après la lecture de l'état des migrations et avant celle des tables."""
        vrais = SV_modeles(*a, **k)
        self.ecrire_ailleurs()
        return vrais

    def test_ecriture_concurrente_absente_de_l_archive(self):
        with mock.patch.object(SV, "modeles_sauvegardes", self.modeles_avec_arret):
            a = SV.creer("essai", "json")
        self.assertTrue(self.ecrit)
        with zipfile.ZipFile(a.chemin) as z:
            lignes = json.loads(z.read("database.json"))
        noms = [o["fields"]["nom"] for o in lignes if o["model"] == "parametres.instance"]
        self.assertEqual(noms, ["Avant"])
        self.assertEqual(Instance.objects.get(pk=1).nom, "Pendant")  # l'écriture a bien eu lieu

    def test_export_seul_en_lecture_seule(self):
        """exporter_json appelé seul (hors transaction) ouvre son propre instantané en lecture seule."""
        vu = {}

        def regarder(*a, **k):
            with ESP.connexion().cursor() as c:
                c.execute("SHOW transaction_isolation")
                vu["isolation"] = c.fetchone()[0]
                c.execute("SHOW transaction_read_only")
                vu["lecture_seule"] = c.fetchone()[0]
            return SV_modeles(*a, **k)
        with mock.patch.object(SV, "modeles_sauvegardes", regarder):
            SV.exporter_json(io.StringIO())
        self.assertEqual(vu, {"isolation": "repeatable read", "lecture_seule": "on"})


SV_modeles = SV.modeles_sauvegardes


class InstantaneSQLiteSansVerrou(unittest.TestCase):
    """SQLite (réglages de l'outil : transactions IMMEDIATE, WAL) : pendant l'instantané de l'export JSON, une saisie
    faite par une autre connexion passe (pas de verrou d'écriture tenu pendant tout l'export), et l'export ne la voit
    pas (instantané fixe dès la première lecture)."""

    ALIAS = "essai_instantane"

    def setUp(self):
        import tempfile
        from pathlib import Path

        from django.db.backends.sqlite3.base import DatabaseWrapper

        self.dossier = tempfile.TemporaryDirectory()
        self.addCleanup(self.dossier.cleanup)
        reglages = {"ENGINE": "django.db.backends.sqlite3", "NAME": str(Path(self.dossier.name) / "base.sqlite3"),
                    "OPTIONS": {"timeout": 1, "transaction_mode": "IMMEDIATE",
                                "init_command": "PRAGMA journal_mode=WAL;PRAGMA synchronous=NORMAL"},
                    "ATOMIC_REQUESTS": False, "AUTOCOMMIT": True, "CONN_MAX_AGE": 0, "CONN_HEALTH_CHECKS": False,
                    "TIME_ZONE": None, "USER": "", "PASSWORD": "", "HOST": "", "PORT": "", "TEST": {}}
        self.lecteur = DatabaseWrapper(dict(reglages), alias=self.ALIAS)
        self.ecrivain = DatabaseWrapper(dict(reglages), alias=self.ALIAS + "_ecrivain")
        for cx in (self.lecteur, self.ecrivain):
            self.addCleanup(cx.close)
        with self.ecrivain.cursor() as c:
            c.execute("CREATE TABLE t (v integer)")
            c.execute("INSERT INTO t VALUES (1)")
        connections[self.ALIAS] = self.lecteur
        self.addCleanup(connections.__delitem__, self.ALIAS)

    def compter(self):
        with self.lecteur.cursor() as c:
            c.execute("SELECT count(*) FROM t")
            return c.fetchone()[0]

    def test_ecriture_concurrente_acceptee_et_invisible(self):
        with mock.patch.object(ESP, "connexion", return_value=self.lecteur), SV.instantane():
            self.assertTrue(self.lecteur.in_atomic_block)
            self.assertEqual(self.compter(), 1)
            with self.ecrivain.cursor() as c:  # sans le correctif : « database is locked » après 1 s
                c.execute("INSERT INTO t VALUES (2)")
            self.assertEqual(self.compter(), 1)
        self.assertEqual(self.lecteur.transaction_mode, "IMMEDIATE")  # réglage rendu
        self.assertEqual(self.compter(), 2)
