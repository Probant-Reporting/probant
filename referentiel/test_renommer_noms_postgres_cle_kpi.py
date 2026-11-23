"""referentiel/0021 (PostgreSQL) : l'index « _like » de la clé des KPI et les clés étrangères vers elle reprennent le nom
qu'ils ont dans une base neuve, retrouvés par leur table et leur rôle (une base mise à jour gardait des noms tirés de
l'ancien nom de la colonne). Idempotente. Les noms « d'avant » des tests sont des noms quelconques."""
import importlib
import unittest

from django.apps import apps
from django.conf import settings
from django.db import connection
from django.test import TestCase

POSTGRES = settings.DATABASES["default"]["ENGINE"].endswith("postgresql")
MIGRATION = importlib.import_module("referentiel.migrations.0021_noms_postgres_cle_kpi")


def objets():
    """{(genre, table): nom} : index de motif de la clé des KPI, clés étrangères vers elle."""
    with connection.cursor() as cur:
        cur.execute("""SELECT 'index', 'referentiel_kpi', ic.relname FROM pg_index i
                       JOIN pg_class ic ON ic.oid = i.indexrelid JOIN pg_opclass o ON o.oid = i.indclass[0]
                       JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = i.indkey[0]
                       WHERE i.indrelid = 'referentiel_kpi'::regclass AND o.opcname = 'varchar_pattern_ops'
                         AND a.attname = 'code'
                       UNION ALL
                       SELECT 'fk', cl.relname || '.' || a.attname, con.conname FROM pg_constraint con
                       JOIN pg_class cl ON cl.oid = con.conrelid
                       JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = con.conkey[1]
                       WHERE con.contype = 'f' AND con.confrelid = 'referentiel_kpi'::regclass""")
        return {(g, t): n for g, t, n in cur.fetchall()}


@unittest.skipUnless(POSTGRES, "noms d'index et de contraintes : PostgreSQL seulement")
class NomsCleKpiTests(TestCase):
    def renommer(self):
        with connection.schema_editor() as editeur:
            MIGRATION.renommer(apps, editeur)

    def test_noms_d_une_base_neuve_retrouves(self):
        neufs = objets()
        self.assertIn(("fk", "referentiel_attribution.kpi_id"), neufs)
        self.assertTrue(any(g == "index" for g, t in neufs))
        with connection.cursor() as cur:  # base mise à jour : d'autres noms
            for (genre, table), nom in neufs.items():
                if genre == "index":
                    cur.execute(f'ALTER INDEX "{nom}" RENAME TO "referentiel_kpi_ancien_like"')
                else:
                    t = table.split(".")[0]
                    cur.execute(f'ALTER TABLE "{t}" RENAME CONSTRAINT "{nom}" TO "{t[:20]}_ancien_fk"')
        self.assertFalse(set(objets().values()) & set(neufs.values()))
        self.renommer()
        self.assertEqual(objets(), neufs)
        self.renommer()  # idempotente
        self.assertEqual(objets(), neufs)
