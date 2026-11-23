"""Vie d'un groupe fictif sur trois exercices (``qa/group_life``), en petite taille, et anomalies qu'elle a trouvées.

``VieDuGroupeTests`` joue le scénario complet en taille « micro » (4 sites, 3 exercices, mois, second espace) par les
pages de l'outil, puis vérifie qu'aucune anomalie autre que celles déjà connues n'apparaît. Les anomalies connues ont
chacune leur test minimal plus bas, marqué ``expectedFailure`` tant qu'elles ne sont pas corrigées (la suite reste
verte) : quand une correction arrive, son test passe, ``expectedFailure`` doit être retiré, et le code de l'anomalie
sort de ``CONNUES``. La grande taille se joue hors de la suite : ``qa/group_life/run.py --size large``.
"""
import shutil
import tempfile

from django.test import override_settings

from espaces.essais import EspacesTestCase

# Codes d'anomalie du scénario déjà signalés (un test minimal chacun dans test_vie_du_groupe_anomalies.py) : tolérés par
# le scénario complet.
# Les trois anomalies de la réouverture d'un exercice passé (past_total_becomes_incomplete, past_figure_changes,
# past_year_gets_new_cells) sont sorties : date d'ouverture des organisations, choix à la réouverture,
# périmètre des périodes ; le scénario rouvre chaque exercice dans les deux modes.
CONNUES = set()


class VieDuGroupeTests(EspacesTestCase):
    @classmethod
    def setUpClass(cls):
        cls._media = tempfile.mkdtemp()
        cls._reglages = override_settings(MEDIA_ROOT=cls._media, EMAIL_HOST="smtp.exemple.test", IMPORT_ARRIERE_PLAN_LIGNES=0,
                                          EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
        cls._reglages.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._reglages.disable()
        shutil.rmtree(cls._media, ignore_errors=True)

    def test_trois_exercices_sans_anomalie_nouvelle(self):
        from qa.group_life import scenario

        log = scenario.play(size="micro", seed=1, years=3, spaces=True, second_space="essai", quick=True)
        nouvelles = [a for a in log.anomalies if a["code"] not in CONNUES]
        self.assertEqual(nouvelles, [], "\n".join(f"{a['code']} [{a['step']}] {a['detail'][:300]}" for a in nouvelles))
        self.assertGreater(len(log.events), 20)  # le scénario a bien joué (campagnes, imports, relances, espaces)
        # l'assistant (serveur MCP) a lu et changé une case, comparée à la même saisie faite dans le panneau
        self.assertTrue(any("assistant: get_value and save_value" in e for e in log.events))
