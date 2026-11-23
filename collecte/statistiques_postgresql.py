"""PostgreSQL : statistiques du planificateur relevées dès la fin d'un gros chargement fait en une seule transaction.

Un ANALYZE de l'autovacuum lancé pendant la transaction ne voit pas ses lignes, pas encore validées : il note vides des
tables déjà pleines (``reltuples = 0``). Une table vidée par TRUNCATE (restauration) ou recréée (``restore --rebuild``)
n'a plus de statistiques du tout. Jusqu'au passage suivant de l'autovacuum (une minute ou plus), le planificateur peut
choisir des plans catastrophiques : une requête de la page Paramètres › Unités a tourné 541 s juste après le chargement
de la démo.

``statistiques_a_jour()`` lance un ANALYZE des tables de l'espace (schéma courant de sa connexion) APRÈS la validation de
la transaction en cours (``transaction.on_commit``), ou tout de suite hors transaction. Une seule fois par transaction,
même appelée plusieurs fois (onze modèles de la bibliothèque installés dans un même chargement). Un échec est journalisé
et n'annule rien : l'opération elle-même est déjà validée. SQLite : rien à faire.

Appelée par : la démo (``load_demo``), l'installation ou la mise à jour d'un modèle de la bibliothèque et l'import d'un
fichier référentiel (``paquets.application._appliquer``), l'import du fichier de configuration, la reprise de données
(import de valeurs tout ou rien), la restauration d'une archive (``--rebuild`` compris)."""
import logging
import time

from django.db import connections, transaction

from espaces import contexte as ESP

journal = logging.getLogger("reporting.statistiques")


def _tables_de_l_espace(curseur):
    """Tables (ordinaires ou partitionnées) du schéma courant de la connexion : celles de l'espace, jamais celles des
    autres espaces ni du registre commun (autres schémas de la même base)."""
    curseur.execute("SELECT format('%I.%I', n.nspname, c.relname) FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = current_schema() AND c.relkind IN ('r', 'p') ORDER BY c.relname")
    return [r[0] for r in curseur.fetchall()]


def analyser(alias):
    """ANALYZE des tables de l'espace de l'alias ``alias``. Ne lève jamais d'erreur : un échec (droit refusé, connexion
    perdue…) est journalisé. Dans un bloc atomique (essais), l'échec est annulé avec son seul point de sauvegarde."""
    debut = time.monotonic()
    try:
        connexion = connections[alias]
        with transaction.atomic(using=alias), connexion.cursor() as c:
            tables = _tables_de_l_espace(c)
            if tables:
                c.execute("ANALYZE " + ", ".join(tables))
    except Exception as e:  # noqa: BLE001 - l'opération est déjà validée : rien ne doit la faire échouer
        journal.warning("ANALYZE after a large load failed on database \"%s\" (%s: %s): the statistics of the planner "
                        "will be updated by the next autovacuum", alias, e.__class__.__name__, e)
        return False
    journal.info("ANALYZE after a large load: %s table(s) of database \"%s\" in %.2f s", len(tables), alias,
                 time.monotonic() - debut)
    return True


def statistiques_a_jour(alias=None):
    """PostgreSQL : ANALYZE des tables de l'espace ``alias`` (l'espace courant par défaut) après la validation de la
    transaction en cours, ou tout de suite hors transaction. SQLite : rien."""
    alias = alias or ESP.alias_courant()
    connexion = connections[alias]
    if connexion.vendor != "postgresql":
        return
    if not connexion.in_atomic_block:
        analyser(alias)
        return
    if any(getattr(f, "statistiques_a_jour", False) for _, f, *_ in connexion.run_on_commit):
        return  # déjà prévu pour cette transaction

    def apres_validation():
        analyser(alias)

    apres_validation.statistiques_a_jour = True
    transaction.on_commit(apres_validation, using=alias)
