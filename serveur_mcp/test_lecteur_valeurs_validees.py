"""Réglage « un lecteur peut lire par un assistant » allumé (règle du projet) : le lecteur ne reçoit
que les valeurs VALIDÉES, comme la Visualisation les lui montre : une valeur en brouillon est « en attente » (ni valeur,
ni commentaire, ni auteur), un total calculé depuis un brouillon aussi ; outil par outil (valeur, liste, historique,
alertes). L'auditeur garde ce que montrent ses pages (brouillons compris).

Données inventées uniquement."""
from collecte import calcul as C
from collecte import saisie as S
from collecte.models import Alerte, Reponse

from .aides_tests import MODERNE, BaseMCP
from .models import ReglageMCP


class LecteurValeursValideesTests(BaseMCP):
    def setUp(self):
        super().setUp()
        ReglageMCP.objects.filter(pk=1).update(lecteur_lit=True)
        C.recalculer(self.c)
        self.alerte = Alerte.objects.create(campagne=self.c, kpi=self.eff, organisation=self.e1,
                                            controle=Alerte.Controle.ECART_N1, message="écart 110 / 100")

    def valider_tout(self):
        Reponse.objects.filter(periode=self.c.periode, origine="saisie").update(statut=Reponse.Statut.VALIDE)
        C.recalculer(self.c)

    def test_get_value_brouillon_en_attente(self):
        _, res, d = self.outil("lecteur", "get_value", self.case(), MODERNE)
        self.assertFalse(res["isError"], d)
        self.assertEqual((d["value"], d["display"], d["comment"]["user_text"]), (None, None, ""))
        self.assertTrue(d["awaiting_validation"])
        self.assertEqual(d["blocks_validation"], [])
        self.assertEqual(d["comparison"]["value"], "100")  # 2025, importée et validée
        self.assertIsNone(d["comparison"]["variance"])
        self.valider_tout()
        _, _, d = self.outil("lecteur", "get_value", self.case(), MODERNE)
        self.assertEqual(d["value"], "110")
        self.assertNotIn("awaiting_validation", d)

    def test_list_values_et_total_calcule_depuis_des_brouillons(self):
        _, _, d = self.outil("lecteur", "list_values", {"campaign_id": self.c.pk}, MODERNE)
        self.assertTrue(d["values"])
        self.assertTrue(all(v["value"] is None for v in d["values"]))
        _, _, d = self.outil("lecteur", "list_values", {"campaign_id": self.c.pk, "organisation_id": self.p.pk,
                                                         "include_calculated": True}, MODERNE)
        total = next(v for v in d["values"] if v["kpi"]["code"] == "EFF")
        self.assertIsNone(total["value"])  # 110 + 40 en brouillon : en attente
        self.valider_tout()
        _, _, d = self.outil("lecteur", "list_values", {"campaign_id": self.c.pk, "organisation_id": self.p.pk,
                                                         "include_calculated": True}, MODERNE)
        self.assertEqual(next(v for v in d["values"] if v["kpi"]["code"] == "EFF")["value"], "150")

    def test_historique_sans_brouillon(self):
        _, _, d = self.outil("lecteur", "get_cell_history", self.case(campagne=self.c0), MODERNE)
        autre = next(p for p in d["other_periods"] if p["period"] == str(self.c.periode))
        self.assertIsNone(autre["value"])
        self.assertNotIn("changes", d)

    def test_alerte_sur_un_brouillon_cachee(self):
        _, _, d = self.outil("lecteur", "list_alerts", {"campaign_id": self.c.pk, "status": "all"}, MODERNE)
        self.assertNotIn(self.alerte.pk, [a["id"] for a in d["alerts"]])
        self.valider_tout()
        _, _, d = self.outil("lecteur", "list_alerts", {"campaign_id": self.c.pk, "status": "all"}, MODERNE)
        self.assertIn(self.alerte.pk, [a["id"] for a in d["alerts"]])

    def test_auditeur_inchange(self):
        _, _, d = self.outil("auditeur", "get_value", self.case(), MODERNE)
        self.assertEqual(d["value"], "110")
        self.assertEqual(S.reponse_de(self.c, self.eff, self.e1).statut, Reponse.Statut.BROUILLON)
