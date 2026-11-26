"""Contrôle du schéma et des objets interdits d'une base SQLite restaurée (``controler_base_sqlite``,
``schema_base``) : pour TOUTE restauration, écran et ligne de commande (version 1.1.1), avant tout
changement quand la copie a les migrations de la base.

Avant : une base forgée au schéma différent (colonne retirée, CHECK ajouté) passait « quick_check » et la liste des
migrations ; la base de l'espace était remplacée, puis tout échouait (« no such column ») : plus personne n'entrait.
Un déclencheur dont le type avait été réécrit en majuscules (« writable_schema ») échappait au contrôle des pièges."""
import io
import shutil
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TransactionTestCase

from espaces.aides_tests import creer
from espaces.models import Compte, Espace
from referentiel.models import Utilisateur

from . import sauvegardes as SV
from . import schema_base as SB
from .aides_tests.autre_installation import archive_d_ailleurs, compte
from .aides_tests.hebergement import DossiersTemporaires

SQLITE = settings.DATABASES["default"]["ENGINE"].endswith("sqlite3")
TABLE = "referentiel_utilisateur"
PIEGES = {
    "colonne retirée": f'ALTER TABLE "{TABLE}" DROP COLUMN first_name;',
    "CHECK ajouté": "PRAGMA writable_schema=ON; "
                    f"UPDATE sqlite_master SET sql = replace(sql, '\"role\" varchar(20) NOT NULL', "
                    f"'\"role\" varchar(20) NOT NULL CHECK (role != ''lecteur'')') WHERE name = '{TABLE}';",
    "index UNIQUE ajouté": f'CREATE UNIQUE INDEX piege ON "{TABLE}" (first_name);',
    "déclencheur en majuscules": f'CREATE TRIGGER t AFTER UPDATE ON "{TABLE}" BEGIN UPDATE "{TABLE}" SET is_superuser = 1; END; '
                                 "PRAGMA writable_schema=ON; UPDATE sqlite_master SET type = 'TRIGGER' WHERE name = 't';",
    "déclencheur déguisé en index": f'CREATE TRIGGER t2 AFTER UPDATE ON "{TABLE}" BEGIN SELECT 1; END; '
                                    "PRAGMA writable_schema=ON; UPDATE sqlite_master SET type = 'index' WHERE name = 't2';",
}


@unittest.skipUnless(SQLITE, "base SQLite seulement")
class SchemaBase(DossiersTemporaires, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.ext = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.ext, True)
        Espace.objects.get_or_create(code="principal", defaults={"nom": "Principal", "etat": "actif"})
        self.inst = creer("inst@exemple.test", "admin")
        self.bob = creer("bob@exemple.test", "contributeur")

    def etat(self):
        return sorted(Utilisateur.objects.values_list("pk", "email", "role")), sorted(Compte.objects.values_list("pk", "email"))

    def test_la_base_de_l_outil_n_a_aucun_ecart(self):
        from django.db import connection

        connection.ensure_connection()
        self.assertEqual(SB.ecarts(connection.connection), [])
        self.assertEqual(SB.objets_interdits(connection.connection), 0)

    def test_ecran_refuse_avant_tout_changement(self):
        for nom, sql in PIEGES.items():
            with self.subTest(nom):
                a = archive_d_ailleurs(self.ext / f"{len(nom)}.zip", [compte(900, "alice@exemple.test", "admin")],
                                       format_base="sqlite", sql_en_plus=[sql])
                avant = self.etat()
                with self.assertRaises(SV.ErreurSauvegarde) as e:
                    SV.restaurer(a, autre_installation=True, origine="outil",
                                 restaurateur={"pk": self.inst.pk, "email": self.inst.email})
                self.assertNotIsInstance(e.exception, SV.ErreurApresRemplacement)
                self.assertEqual(self.etat(), avant)
                self.assertIsNone(SV.restauration_en_cours())
                self.assertEqual(SV.archives(), [])  # refusée avant même la sauvegarde « avant »

    def test_type_entre_guillemets_qui_cache_une_contrainte(self):
        """Seconde relecture : le texte normalisé retirait les guillemets ; « "username" "varchar(150) NOT NULL UNIQUE" »
        passait pour la même colonne alors que SQLite y lit un nom de type, sans contrainte. Table refaite sans
        « writable_schema ». Structure comparée par PRAGMA : refusé, et aussi après la migration (``_verifier_lisible``)."""
        from .aides_tests.autre_installation import refaire_table

        cas = {
            "NOT NULL retiré": ("referentiel_utilisateur", '"first_name" varchar(150) NOT NULL',
                                '"first_name" "varchar(150) NOT NULL"'),
            "UNIQUE retiré": ("referentiel_utilisateur", '"email" varchar(254) NOT NULL UNIQUE',
                              '"email" "varchar(254) NOT NULL UNIQUE"'),
            "PRIMARY KEY retiré": ("referentiel_utilisateur", '"id" integer NOT NULL PRIMARY KEY AUTOINCREMENT',
                                   '"id" "integer NOT NULL PRIMARY KEY AUTOINCREMENT"'),
            "REFERENCES retiré": ("collecte_journal",
                                  '"utilisateur_id" bigint NULL REFERENCES "referentiel_utilisateur" ("id") DEFERRABLE INITIALLY DEFERRED',
                                  '"utilisateur_id" "bigint NULL REFERENCES referentiel_utilisateur (id) DEFERRABLE INITIALLY DEFERRED"'),
            "CHECK retiré": ("parametres_langue", '"ordre" integer unsigned NOT NULL CHECK ("ordre" >= 0)',
                             '"ordre" "integer unsigned NOT NULL CHECK (ordre >= 0)"'),
        }
        for nom, (table, ancien, nouveau) in cas.items():
            with self.subTest(nom):
                a = archive_d_ailleurs(self.ext / f"g{len(nom)}.zip", [compte(900, "alice@exemple.test", "admin")],
                                       format_base="sqlite", traiter_sqlite=refaire_table(table, ancien, nouveau))
                with zipfile.ZipFile(a) as z, tempfile.TemporaryDirectory() as tmp:
                    z.extract(SV.BASE_SQLITE, tmp)
                    c = sqlite3.connect(Path(tmp) / SV.BASE_SQLITE)
                    try:
                        self.assertTrue(SB.ecarts(c), nom)
                    finally:
                        c.close()
                avant = self.etat()
                with self.assertRaises(SV.ErreurSauvegarde):
                    SV.restaurer(a, autre_installation=True, origine="outil",
                                 restaurateur={"pk": self.inst.pk, "email": self.inst.email})
                self.assertEqual(self.etat(), avant)

    def test_ligne_de_commande_refuse_aussi(self):
        """Seul changement permis à la commande : une base piégée ou au schéma inattendu est refusée, avec ou sans
        --unsigned ; une sauvegarde faite par l'outil passe toujours (dernier cas)."""
        for nom in ("colonne retirée", "déclencheur en majuscules"):
            with self.subTest(nom):
                a = archive_d_ailleurs(self.ext / f"cli-{len(nom)}.zip", None, format_base="sqlite", sql_en_plus=[PIEGES[nom]])
                avant = self.etat()
                with self.assertRaises(CommandError):
                    call_command("restore", str(a), "--yes", "--unsigned", "--other-space", stdout=io.StringIO())
                self.assertEqual(self.etat(), avant)
        propre = SV.creer("manuelle", "sqlite")
        call_command("restore", propre.nom, "--yes", stdout=io.StringIO())
        self.assertEqual(self.etat()[0], sorted(Utilisateur.objects.values_list("pk", "email", "role")))

    def test_sauvegarde_de_l_outil_signee_jamais_refusee(self):
        a = SV.creer("manuelle", "sqlite")
        SV.restaurer(a.chemin, exiger_signature=True, origine="outil")
        with zipfile.ZipFile(a.chemin) as z, tempfile.TemporaryDirectory() as tmp:
            z.extract(SV.BASE_SQLITE, tmp)
            c = sqlite3.connect(Path(tmp) / SV.BASE_SQLITE)
            try:
                self.assertEqual(SB.ecarts(c), [])
            finally:
                c.close()
