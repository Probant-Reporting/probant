"""``statistiques_a_jour`` (``collecte/statistiques_postgresql.py``) : jamais dans la transaction du chargement (après
sa validation), une seule fois par transaction, sur la base de l'espace courant, sans effet sous SQLite ; un échec de
l'ANALYZE est journalisé et n'annule rien."""
from unittest import mock, skipUnless

from django.db import connection, connections
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from espaces import contexte as E
from espaces.essais import EspacesTestCase
from referentiel.models import KPI, Niveau

from . import statistiques_postgresql as ST
from .aides_tests.statistiques import POSTGRES, analyzes_prevus, lignes_notees


def analyzes(requetes):
    return [q["sql"] for q in requetes.captured_queries if q["sql"].lstrip().upper().startswith("ANALYZE")]


class StatistiquesAJourTests(TestCase):
    def test_jamais_dans_la_transaction_une_seule_fois(self):
        with self.captureOnCommitCallbacks() as rappels, CaptureQueriesContext(connection) as requetes:
            for _ in range(3):
                ST.statistiques_a_jour()
        self.assertEqual(analyzes(requetes), [])  # rien pendant la transaction
        self.assertEqual(len(analyzes_prevus(rappels)), 1 if POSTGRES else 0)  # SQLite : rien du tout

    @skipUnless(POSTGRES, "PostgreSQL")
    def test_apres_validation_toutes_les_tables_de_l_espace(self):
        KPI.objects.create(code="K1", libelle="K1", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY)
        # le rappel s'exécute à la sortie de captureOnCommitCallbacks : requêtes relevées autour
        with CaptureQueriesContext(connection) as requetes, self.captureOnCommitCallbacks(execute=True):
            ST.statistiques_a_jour()
        (sql,) = analyzes(requetes)
        self.assertIn("referentiel_kpi", sql)
        self.assertNotIn('"commun".', sql)  # registre commun : autre schéma, jamais touché
        self.assertGreaterEqual(lignes_notees("referentiel_kpi")[0], 1)

    @skipUnless(POSTGRES, "PostgreSQL")
    def test_echec_journalise_et_rien_n_est_annule(self):
        k = KPI.objects.create(code="K1", libelle="K1", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY)
        with mock.patch.object(ST, "_tables_de_l_espace", return_value=["table_inexistante"]), \
                self.assertLogs("reporting.statistiques", "WARNING") as journal, \
                self.captureOnCommitCallbacks(execute=True):
            ST.statistiques_a_jour()
        self.assertIn("ANALYZE after a large load failed", journal.output[0])
        self.assertTrue(KPI.objects.filter(pk=k.pk).exists())  # la base reste utilisable, la ligne est là

    @skipUnless(POSTGRES, "PostgreSQL")
    def test_hors_transaction_tout_de_suite(self):
        with mock.patch.object(connections["default"], "in_atomic_block", False), mock.patch.object(ST, "analyser") as analyser:
            ST.statistiques_a_jour()
        analyser.assert_called_once_with("default")


@skipUnless(POSTGRES, "PostgreSQL")
class StatistiquesAJourEspacesTests(EspacesTestCase):
    def test_base_de_l_espace_courant(self):
        with CaptureQueriesContext(connections["espace_essai"]) as requetes, \
                self.captureOnCommitCallbacks(using="default") as principal, \
                self.captureOnCommitCallbacks(using="espace_essai", execute=True) as essai, E.activer("essai"):
            ST.statistiques_a_jour()
        self.assertEqual(analyzes_prevus(principal), [])
        self.assertEqual(len(analyzes_prevus(essai)), 1)
        self.assertEqual(len(analyzes(requetes)), 1)
