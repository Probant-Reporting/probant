"""Essais des statistiques du planificateur de PostgreSQL après un gros chargement (``collecte/statistiques_postgresql.py``).

``analyze_par_une_autre_connexion`` fait ce que fait l'autovacuum pendant un chargement : un ANALYZE hors de la
transaction du chargement, qui ne compte pas les lignes pas encore validées (et saute, comme lui, une table verrouillée
par un TRUNCATE ou un DROP en cours). ``verifier_lignes_notees`` contrôle qu'après l'opération le nombre de lignes noté
pour chaque table est celui de la table (à l'échantillon près)."""
from django.db import connections

POSTGRES = connections["default"].vendor == "postgresql"


def analyze_par_une_autre_connexion(tables, alias="default", sauter_verrouillees=False):
    autre = connections.create_connection(alias)
    try:
        with autre.cursor() as c:
            c.execute("ANALYZE " + ("(SKIP_LOCKED) " if sauter_verrouillees else "") + ", ".join(tables))
    finally:
        autre.close()


def lignes_notees(table, alias="default"):
    """(lignes notées par le planificateur, lignes réelles) ; -1 notées : aucune statistique (table neuve ou vidée)."""
    with connections[alias].cursor() as c:
        c.execute(f"SELECT reltuples, (SELECT count(*) FROM {table}) FROM pg_class WHERE oid = %s::regclass", [table])
        return c.fetchone()


def verifier_lignes_notees(test, tables, minimum, alias="default"):
    for table in tables:
        notees, reelles = lignes_notees(table, alias)
        test.assertGreaterEqual(reelles, minimum, table)
        # au-delà de 30 000 lignes, ANALYZE estime d'après un échantillon : à 10 % près
        test.assertGreaterEqual(notees, 0.9 * reelles, f"{table} : {notees} lignes notées pour {reelles}")


def analyzes_prevus(rappels):
    """Rappels « après validation » (``captureOnCommitCallbacks``) qui sont l'ANALYZE de ``statistiques_a_jour``."""
    return [f for f in rappels if getattr(f, "statistiques_a_jour", False)]
