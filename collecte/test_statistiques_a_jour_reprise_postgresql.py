"""Reprise de données sous PostgreSQL (import de valeurs tout ou rien, une seule transaction) : les statistiques du
planificateur décrivent les valeurs importées dès la fin de l'import (``statistiques_postgresql``).

La reprise des valeurs d'un autre système (``vues_reprise``, ``imports.appliquer`` sans paquets) écrit tout en une seule
transaction, souvent dans une installation neuve : un ANALYZE de l'autovacuum pendant ce temps note vide la table des
valeurs (``reltuples = 0``). L'import de la page Import / Export, lui, valide chaque paquet de lignes à part : un
ANALYZE de l'autovacuum voit les paquets déjà validés, rien à faire. L'essai reproduit l'autovacuum : un ANALYZE par
une autre connexion juste avant la fin de l'import."""
from unittest import mock, skipUnless

from referentiel.models import Niveau, Organisation

from . import imports as I
from .aides_tests import echanges as TE
from .aides_tests.statistiques import (POSTGRES, analyze_par_une_autre_connexion, analyzes_prevus,
                                         verifier_lignes_notees)
from .models import Journal, Reponse
from .outils_tests import xlsx

TABLES = ("collecte_reponse",)
N = 150


@skipUnless(POSTGRES, "statistiques du planificateur de PostgreSQL")
class StatistiquesApresRepriseTests(TE.Base):
    def setUp(self):
        super().setUp()
        for i in range(N):
            Organisation.objects.create(nom=f"Entité {i}", niveau_id=Niveau.ENTITY, parent=self.p)

    def fichier(self):
        return xlsx([["ID KPI", "Organisation", "Exercice", "Valeur", "Commentaire"],
                     *[["EFF", f"Entité {i}", 2026, i + 1, ""] for i in range(N)]])

    def importer(self, **options):
        vraie = Journal.ecrire.__func__

        def ecrire(cls, utilisateur, action, *args, **kwargs):
            if action == "import_valeurs":  # valeurs écrites, transaction de la reprise pas encore validée
                analyze_par_une_autre_connexion(TABLES)
            return vraie(cls, utilisateur, action, *args, **kwargs)

        with mock.patch.object(Journal, "ecrire", classmethod(ecrire)):
            return I.appliquer(self.admin, self.fichier(), "reprise.xlsx", **options)

    def test_reprise_tout_ou_rien(self):
        with self.captureOnCommitCallbacks(execute=True) as rappels:
            _, n, _ = self.importer()
        self.assertEqual(n, N)
        self.assertEqual(len(analyzes_prevus(rappels)), 1)
        self.assertGreaterEqual(Reponse.objects.count(), N)
        verifier_lignes_notees(self, TABLES, minimum=N)

    def test_import_par_paquets_rien_a_faire(self):
        with self.captureOnCommitCallbacks() as rappels:
            _, n, _ = self.importer(par_paquets=True)
        self.assertEqual(n, N)
        self.assertEqual(analyzes_prevus(rappels), [])
