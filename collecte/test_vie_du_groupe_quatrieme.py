"""Vie d'un groupe fictif, quatrième année (``qa/group_life/year4.py``), en taille « micro » : le premier exercice, le second
espace, puis les événements que les trois premiers exercices ne jouent pas (départ et remplacement d'une personne,
changements de rôle, dernier administrateur, mot de passe provisoire, e-mail changé, compte dans deux espaces, saisie en
plusieurs langues, organisation renommée, niveau ajouté, fusion, cession, unité, format, KPI retiré puis remis,
facultatif, formule, KPI sensible, liste et tableau, exercice décalé, deux exercices ouverts, dates, clôture avec des
brouillons, langue par défaut, espace archivé).

Les anomalies « règle à trancher » trouvées ont chacune leur test minimal marqué ``expectedFailure`` dans
``test_vie_du_groupe_anomalies.py`` ; leurs codes sont tolérés ici. La version complète (trois exercices d'abord) se joue
hors de la suite : ``qa/group_life/run4.py --years 3``.
"""
import shutil
import tempfile

from django.test import override_settings

from espaces.essais import EspacesTestCase

from .test_vie_du_groupe import CONNUES as CONNUES_TROIS_ANS

CONNUES = CONNUES_TROIS_ANS  # « unit_changed_with_values » et « reader_keeps_assignments » : tranchées


class VieDuGroupeQuatriemeAnneeTests(EspacesTestCase):
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

    def test_quatrieme_annee_sans_anomalie_nouvelle(self):
        from qa.group_life import year4

        log = year4.play4(size="micro", seed=1, years=1, spaces=True, second_space="essai", quick=True)
        nouvelles = [a for a in log.anomalies if a["code"] not in CONNUES]
        self.assertEqual(nouvelles, [], "\n".join(f"{a['code']} [{a['step']}] {a['detail'][:300]}" for a in nouvelles))
        joues = [p["event"] for p in log.played if p["status"] == "played"]
        self.assertGreaterEqual(len(joues), 20, log.played)  # les événements ont bien été joués
        for evenement in ("contributor leaves and is replaced", "level Region inserted, entity moved in an open campaign",
                          "list value used in a table removed", "two years open at the same time"):
            self.assertIn(evenement, joues)
