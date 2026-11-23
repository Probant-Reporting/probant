"""Restauration d'une archive sous PostgreSQL (``restore``, depuis l'outil ou en ligne de commande, ``--rebuild`` compris) :
les statistiques du planificateur décrivent les données restaurées dès la fin de la restauration
(``collecte/statistiques_postgresql.py``).

La restauration vide les tables (TRUNCATE) puis les recharge, en une seule transaction ; ``--rebuild`` les supprime et
les recrée. Dans les deux cas, les tables n'ont plus aucune statistique après la validation (``reltuples = -1``), et
l'autovacuum, qui saute une table verrouillée, n'a rien pu relever pendant le chargement : jusqu'à son passage suivant, le
planificateur estime les tables à l'aveugle. L'essai reproduit l'autovacuum (ANALYZE par une autre connexion, tables
verrouillées sautées) juste après le chargement, avant la validation."""
import io
from unittest import mock, skipUnless

from django.core.management import call_command
from django.db import connection
from django.test import TransactionTestCase

from . import sauvegardes as SV
from .aides_tests.hebergement import DossiersTemporaires
from collecte.aides_tests import jeu_trois_niveaux as J
from collecte.aides_tests.statistiques import POSTGRES, analyze_par_une_autre_connexion, verifier_lignes_notees

TABLES = ("collecte_reponse", "collecte_journal", "referentiel_kpi", "referentiel_organisation")
FUTURE = ("collecte", "9999_version_plus_recente")


@skipUnless(POSTGRES, "statistiques du planificateur de PostgreSQL")
class StatistiquesApresRestaurationTests(DossiersTemporaires, TransactionTestCase):

    def setUp(self):
        super().setUp()
        J.charger()  # jeu d'essai à trois niveaux : comptes, référentiels, campagnes, réponses, journal
        self.archive = SV.creer("essai", "json")

    def restaurer(self, *options):
        vraie = SV.call_command

        def call_command_espion(nom, *args, **kwargs):
            resultat = vraie(nom, *args, **kwargs)
            if nom == "loaddata":  # contenu de l'archive chargé, transaction pas encore validée
                analyze_par_une_autre_connexion(TABLES, sauter_verrouillees=True)
            return resultat

        with mock.patch.object(SV, "call_command", call_command_espion):
            call_command("restore", self.archive.nom, "--yes", *options, stdout=io.StringIO())

    def test_restauration(self):
        self.restaurer()
        verifier_lignes_notees(self, TABLES, minimum=5)

    def test_restauration_rebuild(self):
        """Base mise à jour depuis l'archive (une migration de plus) : ``restore --rebuild`` recrée les tables."""
        self.addCleanup(self.defaire)
        with connection.cursor() as c:
            c.execute("INSERT INTO django_migrations (app, name, applied) VALUES (%s, %s, CURRENT_TIMESTAMP)", FUTURE)
        self.restaurer("--rebuild")
        self.assertNotIn(list(FUTURE), SV.migrations_appliquees())  # reconstruite : migrations de l'archive
        verifier_lignes_notees(self, TABLES, minimum=5)

    def defaire(self):
        with connection.cursor() as c:
            c.execute("DELETE FROM django_migrations WHERE app = %s AND name = %s", FUTURE)
