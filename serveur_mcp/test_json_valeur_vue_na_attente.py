"""Lecteur par un assistant (réglage « un lecteur peut lire par un assistant ») : une case calculée se montre refaite sur
les seules valeurs validées (``outils.json_valeur_vue``). Quand ce calcul donne N/A alors que la case enregistrée porte
encore une valeur (total pas encore refait, par exemple au milieu d'un import en lot), le lecteur reçoit N/A
(« not_applicable » vrai, sans valeur), jamais la valeur enregistrée.

Données inventées uniquement."""
from collecte.models import Reponse

from .aides_tests import MODERNE, BaseMCP
from .models import ReglageMCP


class NonApplicableValideTests(BaseMCP):
    def setUp(self):
        super().setUp()
        ReglageMCP.objects.filter(pk=1).update(lecteur_lit=True)

    def test_total_na_sur_les_valeurs_validees(self):
        # E1 et E2 : N/A validés ; le total du pays enregistré vaut encore 40 (pas encore refait)
        Reponse.objects.filter(periode=self.c.periode, kpi=self.eff, organisation__in=[self.e1, self.e2]).update(
            valeur=None, non_applicable=True, statut=Reponse.Statut.VALIDE)
        Reponse.objects.filter(periode=self.c.periode, kpi=self.eff, organisation=self.p).update(
            valeur=40, non_applicable=False, statut=Reponse.Statut.CALCULE, origine=Reponse.Origine.AGREGATION)
        _, res, d = self.outil("lecteur", "get_value", self.case(org=self.p), MODERNE)
        self.assertFalse(res["isError"], d)
        self.assertEqual((d["value"], d["display"], d["not_applicable"]), (None, "N/A", True))
        self.assertNotIn("awaiting_validation", d)
        _, _, d = self.outil("auditeur", "get_value", self.case(org=self.p), MODERNE)  # témoin : l'auditeur voit l'enregistré
        self.assertEqual((d["value"], d["not_applicable"]), ("40", False))
