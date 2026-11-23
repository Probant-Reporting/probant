"""Démo sous PostgreSQL : les statistiques du planificateur décrivent les données chargées dès la fin de ``load_demo``.

``load_demo`` charge toute la démo dans une seule transaction (une vingtaine de secondes, plus sous charge). Un ANALYZE
lancé par l'autovacuum pendant ce temps ne voit pas les lignes pas encore validées : il note les tables des KPI, des
descriptions… vides (``reltuples = 0``) alors qu'elles occupent déjà des pages. Jusqu'au passage suivant de l'autovacuum
(une minute ou plus), le planificateur compte une ligne par table et choisit des boucles imbriquées sans index : la
requête de l'exemple de la page Paramètres › Unités (KPI actifs ayant une description) a tourné 541 s sur la démo,
le serveur de test restait bloqué sur elle (« Page.goto: Timeout » puis délai dépassé de ``_attendre_les_requetes_recues``,
``collecte.test_navigateur_unites_niveaux_langues``, presque à chaque suite complète sous PostgreSQL).

L'essai reproduit l'autovacuum : un ANALYZE par une autre connexion pendant le chargement, juste avant les modèles ESRS.
Après la validation du chargement, le nombre de lignes noté pour chaque table doit être celui de la table (à l'échantillon près)."""
from io import StringIO
from unittest import mock, skipUnless

from django.core.management import call_command
from django.db import connection, connections
from django.test import TestCase

from collecte.management.commands import _exemplia as EXEMPLIA

TABLES = ("referentiel_kpi", "referentiel_description", "referentiel_elementreferentiel", "collecte_reponse")


def analyze_par_une_autre_connexion():
    """Ce que fait l'autovacuum : un ANALYZE hors de la transaction du chargement (les lignes de celle-ci, pas encore
    validées, ne sont pas comptées)."""
    autre = connections.create_connection("default")
    try:
        with autre.cursor() as c:
            c.execute("ANALYZE " + ", ".join(TABLES))
    finally:
        autre.close()


@skipUnless(connection.vendor == "postgresql", "statistiques du planificateur de PostgreSQL")
class StatistiquesApresChargementTests(TestCase):
    def test_statistiques_a_jour_apres_un_analyze_pendant_le_chargement(self):
        vraie = EXEMPLIA.installer_esrs

        def installer_esrs():
            analyze_par_une_autre_connexion()
            return vraie()

        # l'ANALYZE part après la validation de la transaction du chargement (``transaction.on_commit``) : dans l'essai,
        # à la sortie de ce bloc
        with self.captureOnCommitCallbacks(execute=True), mock.patch.object(EXEMPLIA, "installer_esrs", installer_esrs):
            call_command("load_demo", "--language", "fr", stdout=StringIO())
        with connection.cursor() as c:
            for table in TABLES:
                c.execute(f"SELECT reltuples, (SELECT count(*) FROM {table}) FROM pg_class WHERE relname = %s", [table])
                notees, reelles = c.fetchone()
                self.assertGreater(reelles, 100, table)
                # au-delà de 30 000 lignes, ANALYZE estime d'après un échantillon : à 10 % près
                self.assertGreaterEqual(notees, 0.9 * reelles, f"{table} : {notees} lignes notées pour {reelles}")
