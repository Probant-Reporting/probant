"""Installation de modèles de la bibliothèque sous PostgreSQL : les statistiques du planificateur décrivent les KPI, les
descriptions, les thèmes et les places installés dès la fin de l'installation (``statistiques_postgresql``).

Chaque modèle s'installe en une seule transaction (``paquets.application``) : plusieurs centaines de KPI et des
milliers de descriptions pour les onze ESRS, sur des tables presque vides dans une installation neuve. Un ANALYZE de
l'autovacuum lancé pendant ce temps note ces tables vides (``reltuples = 0``) ; jusqu'à son passage suivant, le
planificateur compte une ligne par table (plans catastrophiques, voir ``test_charger_demo_statistiques_postgresql``).
L'essai reproduit l'autovacuum : un ANALYZE par une autre connexion au milieu de chaque installation. Le même chemin sert
à la mise à jour d'un modèle et à l'import d'un fichier référentiel (``_appliquer``)."""
from unittest import mock, skipUnless

from django.test import TestCase

from referentiel.models import KPI

from . import paquets as P
from .aides_tests.statistiques import (POSTGRES, analyze_par_une_autre_connexion, analyzes_prevus,
                                         verifier_lignes_notees)
from .paquets import application as APP

TABLES = ("referentiel_kpi", "referentiel_description", "referentiel_theme", "referentiel_elementreferentiel")


@skipUnless(POSTGRES, "statistiques du planificateur de PostgreSQL")
class StatistiquesApresInstallationTests(TestCase):
    def test_deux_modeles_esrs_analyze_pendant_l_installation(self):
        vraie = APP.reconstruire_toutes_dependances

        def reconstruire():  # KPI et descriptions écrits, transaction pas encore validée
            analyze_par_une_autre_connexion(TABLES)
            return vraie()

        with self.captureOnCommitCallbacks(execute=True) as rappels, mock.patch.object(APP, "reconstruire_toutes_dependances",
                                                                                       reconstruire):
            for f in ("esrs_2.json", "esrs_s1.json"):
                a = P.analyser(P.fourni(f).paquet, fourni=True)
                self.assertFalse(a.erreur)
                P.appliquer(None, a)
        self.assertEqual(len(analyzes_prevus(rappels)), 1)  # ici, une seule transaction (celle de l'essai) : un seul ANALYZE, après elle
        self.assertGreater(KPI.objects.count(), 100)
        verifier_lignes_notees(self, TABLES, minimum=20)
