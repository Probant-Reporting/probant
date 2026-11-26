"""Contenu non fiable d'une sauvegarde d'une autre installation (``controler_base_piegee``, ``assainir_copie`` et les
protections d'avant sur le nouveau chemin) : rien n'est changé quand l'archive est refusée.

Avant : une base SQLite qui portait un déclencheur passait le contrôle (« quick_check » et migrations) ; restaurée, le
déclencheur aurait remis une empreinte de mot de passe connue après nos écritures, puis agi à chaque enregistrement."""
import shutil
import stat
import tempfile
import unittest
import zipfile
from collections import namedtuple
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth import authenticate
from django.test import TransactionTestCase

from espaces.aides_tests import creer
from espaces.models import Compte, Espace
from referentiel.models import Utilisateur

from . import sauvegardes as SV
from . import sauvegardes_ailleurs as SA
from .aides_tests.autre_installation import archive_d_ailleurs, compte
from .aides_tests.hebergement import DossiersTemporaires

SQLITE = settings.DATABASES["default"]["ENGINE"].endswith("sqlite3")
PIRATE = "Pirate-connu-2026"


class ContenuNonFiable(DossiersTemporaires, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.ext = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.ext, True)
        Espace.objects.get_or_create(code="principal", defaults={"nom": "Principal", "etat": "actif"})
        self.inst = creer("inst@exemple.test", "admin")
        self.restaurateur = {"pk": self.inst.pk, "email": self.inst.email}

    def ailleurs(self, nom="a.zip", comptes=None, **options):
        return archive_d_ailleurs(self.ext / nom, comptes or [compte(self.inst.pk + 1, "alice@exemple.test", "admin")],
                                  **options)

    def etat(self):
        return sorted(Utilisateur.objects.values_list("pk", "email", "role")), sorted(Compte.objects.values_list("pk", "email"))

    def assert_refusee(self, chemin, texte):
        avant = self.etat()
        with self.assertRaises(SV.ErreurSauvegarde) as e:
            SV.restaurer(chemin, autre_installation=True, restaurateur=self.restaurateur, origine="outil")
        self.assertIn(texte, str(e.exception))
        self.assertEqual(self.etat(), avant)
        self.assertIsNone(SV.restauration_en_cours())
        self.assertFalse(SV.historique_restaurations())
        return e.exception

    @unittest.skipUnless(SQLITE, "copie SQLite : base SQLite seulement")
    def test_declencheur_vue_colonne_calculee_refuses(self):
        table = SV._table_comptes()
        pieges = {
            "declencheur": f'CREATE TRIGGER t AFTER UPDATE ON "{table}" BEGIN UPDATE "{table}" SET password = '
                           f"'md5$x$y' WHERE id = NEW.id; END;",
            "vue": f'CREATE VIEW v AS SELECT * FROM "{table}";',
            "colonne": f'ALTER TABLE "{table}" ADD COLUMN calcul TEXT GENERATED ALWAYS AS (email) VIRTUAL;',
        }
        for nom, sql in pieges.items():
            with self.subTest(nom):
                a = self.ailleurs(f"{nom}.zip", format_base="sqlite", sql_en_plus=[sql])
                self.assert_refusee(a, "ne crée jamais")

    @unittest.skipUnless(SQLITE, "copie SQLite : base SQLite seulement")
    def test_base_sans_piege_restauree_sans_empreinte(self):
        a = self.ailleurs(comptes=[compte(self.inst.pk + 1, "alice@exemple.test", "admin", mot_de_passe=PIRATE)],
                          format_base="sqlite")
        SV.restaurer(a, autre_installation=True, restaurateur=self.restaurateur, origine="outil")
        self.assertIsNone(authenticate(None, username="alice@exemple.test", password=PIRATE))

    def test_chemins_hors_du_dossier_et_lien_symbolique(self):
        lien = zipfile.ZipInfo("files/lien")
        lien.external_attr = (stat.S_IFLNK | 0o777) << 16
        a = self.ailleurs(fichiers={"files/../../evade.txt": b"x", "files//tmp/absolu.txt": b"x", "files/ok/preuve.pdf": b"%PDF"})
        with zipfile.ZipFile(a, "a") as z:  # entrée marquée lien symbolique, vers un fichier du système
            z.writestr(lien, "/etc/passwd")
        # l'entrée ajoutée casse la signature d'un autre serveur : sans importance, l'archive n'est jamais vérifiable ici
        SV.restaurer(a, autre_installation=True, restaurateur=self.restaurateur, origine="outil")
        racine = Path(settings.MEDIA_ROOT)
        self.assertFalse((self.tmp / "evade.txt").exists())
        self.assertFalse((racine.parent / "evade.txt").exists())
        self.assertFalse(Path("/tmp/absolu.txt").exists() and Path("/tmp/absolu.txt").read_bytes() == b"x")
        self.assertEqual((racine / "ok" / "preuve.pdf").read_bytes(), b"%PDF")
        self.assertFalse((racine / "lien").is_symlink())  # écrit comme un fichier ordinaire, jamais comme un lien

    def test_archive_trop_grosse_pour_le_disque(self):
        a = self.ailleurs()
        Usage = namedtuple("Usage", "total used free")
        with mock.patch.object(SV.shutil, "disk_usage", return_value=Usage(10, 10, 1024)):
            self.assert_refusee(a, "trop volumineuse")

    def test_version_plus_recente_refusee_avant_et_au_moment_de_restaurer(self):
        import json

        migrations = json.loads(json.dumps(SV.migrations_appliquees())) + [["collecte", "9999_futur"]]
        a = self.ailleurs(descriptif={"migrations": migrations, "version": "9.0.0"})
        plan, refus = SA.apercu(a, SV.lire_descriptif(a), self.restaurateur)
        self.assertIsNone(plan)
        self.assertIn("plus récente", refus)
        self.assertIn("plus récente", str(self.assert_refusee(a, "9.0.0")))

    @unittest.skipIf(SQLITE, "PostgreSQL seulement")
    def test_archive_postgresql_d_une_autre_version(self):
        a = self.ailleurs(descriptif={"migrations": SV.migrations_appliquees()[:-1]})
        self.assert_refusee(a, "migrations")

    @unittest.skipIf(SQLITE, "PostgreSQL seulement")
    def test_archive_sqlite_vers_postgresql(self):
        a = self.ailleurs()
        with zipfile.ZipFile(a, "a") as z:
            z.writestr(SV.BASE_SQLITE, b"x")
        self.assert_refusee(a, "SQLite")

    def test_pas_une_sauvegarde(self):
        faux = self.ext / "faux.zip"
        with zipfile.ZipFile(faux, "w") as z:
            z.writestr("backup.json", "{\"outil\": \"autre\"}")
        with self.assertRaises(SV.ErreurSauvegarde):
            SV.restaurer(faux, autre_installation=True, restaurateur=self.restaurateur, origine="outil")

    def test_lecture_json_objet_par_objet(self):
        """Le JSON d'une archive est lu objet par objet (jamais tout en mémoire) ; un JSON tronqué est refusé."""
        import io

        objets = list(SA._objets_json(io.BytesIO(b' [ {"model": "a", "pk": 1}, {"model": "b", "pk": 2, "fields": {"t": "]"}} ] ')))
        self.assertEqual([o["pk"] for o in objets], [1, 2])
        with self.assertRaises(ValueError):
            list(SA._objets_json(io.BytesIO(b'[{"model": "a", "pk": 1}, {"model"')))
        with self.assertRaises(ValueError):
            list(SA._objets_json(io.BytesIO(b'{"model": "a"}')))
