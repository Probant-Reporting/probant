"""Restauration d'un espace sous PostgreSQL (ordinaire et « restore --rebuild ») : les lignes de l'archive sont rechargées
avec leur numéro ; aucune séquence ne doit rester en dessous du plus grand numéro de sa table, sans quoi la création
suivante chez un client reprendrait un numéro déjà pris (IntegrityError). Garde-fou vérifié lors de l'enquête sur
``collecte_reglageexport_pkey`` : le défaut était dans l'isolation des tests, pas dans la restauration."""
import io
import unittest

from django.conf import settings
from django.core.management import call_command
from django.db import connection
from django.test import TransactionTestCase

from . import sauvegardes as SV
from .aides_tests.hebergement import DossiersTemporaires
from collecte.aides_tests import jeu_trois_niveaux as J
from collecte.exports import creer_modeles_fournis
from collecte.models import ReglageExport
from collecte.outils_tests import tables_en_retard

POSTGRES = settings.DATABASES["default"]["ENGINE"].endswith("postgresql")
FUTURE = ("collecte", "9999_version_plus_recente")


@unittest.skipUnless(POSTGRES, "séquences : PostgreSQL seulement")
class SequencesApresRestauration(DossiersTemporaires, TransactionTestCase):

    def setUp(self):
        super().setUp()
        J.charger()
        creer_modeles_fournis()
        self.archive = SV.creer("essai", "json")
        self.assertTrue(ReglageExport.objects.exists())

    def verifier(self):
        self.assertEqual(tables_en_retard(connection), [])
        r = ReglageExport.objects.create(nom="Après la restauration", parametres={}, ordre=99)
        self.assertGreater(r.pk, max(ReglageExport.objects.exclude(pk=r.pk).values_list("pk", flat=True)))

    def test_restauration_ordinaire(self):
        SV.restaurer(self.archive.chemin, sauvegarder_avant=False)
        self.verifier()

    def test_reconstruction(self):
        with connection.cursor() as c:  # base mise à jour depuis par une version plus récente : une migration de plus
            c.execute("INSERT INTO django_migrations (app, name, applied) VALUES (%s, %s, CURRENT_TIMESTAMP)", FUTURE)
        self.addCleanup(self.defaire)
        call_command("restore", self.archive.nom, "--yes", "--rebuild", stdout=io.StringIO())
        self.assertNotIn(list(FUTURE), SV.migrations_appliquees())
        self.verifier()

    def defaire(self):
        with connection.cursor() as c:
            c.execute("DELETE FROM django_migrations WHERE app = %s AND name = %s", FUTURE)
