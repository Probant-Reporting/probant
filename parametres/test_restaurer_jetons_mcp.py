"""Jetons des assistants (MCP) et sauvegardes : aucune archive ne contient de jeton (copie SQLite comprise), et après toute
restauration, quel que soit le format et l'ancienneté de l'archive, l'espace n'a plus aucun jeton : un jeton révoqué
après la sauvegarde ne redevient jamais valide (docs/mcp.md, 1.4)."""
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import TransactionTestCase

from collecte.models import Journal
from referentiel.models import Utilisateur
from serveur_mcp import jetons as JT
from serveur_mcp.models import JetonMCP, ReglageMCP

from . import sauvegardes as SV
from .aides_tests.hebergement import MDP, DossiersTemporaires

SQLITE = settings.DATABASES["default"]["ENGINE"].endswith("sqlite3")


def lignes_de_la_copie(archive, table):
    """Nombre de lignes de ``table`` dans la base SQLite de l'archive."""
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(archive.chemin) as z:
        z.extract(SV.BASE_SQLITE, tmp)
        c = sqlite3.connect(Path(tmp) / SV.BASE_SQLITE)
        try:
            return c.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        finally:
            c.close()


class JetonsEtRestauration(DossiersTemporaires, TransactionTestCase):
    def setUp(self):
        super().setUp()
        ReglageMCP.objects.update_or_create(pk=1, defaults={"actif": True})
        self.u = Utilisateur.objects.create_user("jeton", email="jeton@exemple.test", password=MDP,
                                                 role=Utilisateur.Role.CONTRIBUTEUR)
        self.clair, self.j = JT.creer(self.u, "Portable", 30)

    def revoquer_puis_restaurer(self, archive, n=1):
        """``n`` : jetons de l'archive (lignes du journal restauré) retirés après la restauration."""
        JT.authentifier(self.clair)  # valide avant
        JT.revoquer(self.u, self.j.pk)
        with self.assertRaises(JT.JetonRefuse):
            JT.authentifier(self.clair)
        autre, _ = JT.creer(self.u, "Créé après la sauvegarde", 7)
        SV.restaurer(archive.chemin)
        for jeton in (self.clair, autre):
            with self.assertRaises(JT.JetonRefuse):
                JT.authentifier(jeton)
        self.assertFalse(JetonMCP.objects.exists())
        trace = Journal.objects.filter(action="jeton_mcp", champ="mcp_jetons_restauration").latest("pk")
        self.assertEqual(trace.avant, str(n))

    @unittest.skipUnless(SQLITE, "copie SQLite : base SQLite seulement")
    def test_archive_sqlite_sans_jeton_base_vivante_intacte(self):
        a = SV.creer("essai", "sqlite")
        self.assertEqual(lignes_de_la_copie(a, JetonMCP._meta.db_table), 0)
        self.assertEqual(JetonMCP.objects.count(), 1)  # vidé dans la copie, jamais dans la base vivante
        JT.authentifier(self.clair)

    @unittest.skipUnless(SQLITE, "copie SQLite : base SQLite seulement")
    def test_restauration_sqlite_ne_rend_pas_valide_un_jeton_revoque(self):
        self.revoquer_puis_restaurer(SV.creer("essai", "sqlite"))

    @unittest.skipUnless(SQLITE, "copie SQLite : base SQLite seulement")
    def test_archive_sqlite_ancienne_avec_jetons(self):
        """Archive faite avant cette correction (copie entière, jetons compris) : après sa restauration, aucun jeton."""
        with mock.patch.object(SV, "TABLES_VIDEES_DANS_LA_COPIE", []):
            a = SV.creer("ancienne", "sqlite")
        self.assertEqual(lignes_de_la_copie(a, JetonMCP._meta.db_table), 1)
        self.revoquer_puis_restaurer(a, n=2)  # celui de l'archive (révoqué depuis) et celui créé après la sauvegarde

    def test_archive_json_sans_jeton(self):
        a = SV.creer("essai", "json")
        with zipfile.ZipFile(a.chemin) as z:
            self.assertNotIn(b"serveur_mcp.jetonmcp", z.read(SV.BASE_JSON))
            self.assertNotIn(self.j.empreinte.encode(), z.read(SV.BASE_JSON))
        self.revoquer_puis_restaurer(a)
