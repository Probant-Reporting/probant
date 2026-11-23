"""Valeur pour une organisation qui n'est pas ouverte pendant la période : refusée aussi par le serveur MCP
(règle du projet ; ``save_value`` appelle ``saisie.enregistrer``), avec le même motif que l'écran.

Données inventées uniquement."""
import datetime

from collecte.models import Reponse
from referentiel.models import Organisation

from .aides_tests import MODERNE, BaseMCP


class AssistantOrganisationPasOuverteTests(BaseMCP):
    """Même refus par le serveur MCP (``save_value`` appelle ``saisie.enregistrer``), avec le même motif."""

    def test_save_value_refuse(self):
        Organisation.objects.filter(pk=self.p.pk).update(date_ouverture=datetime.date(2027, 1, 1))
        _, _, v = self.outil("admin", "get_value", self.case(org=self.e2), MODERNE)
        self.assertFalse(v["rights"]["can_change"])
        _, res, d = self.outil("admin", "save_value", {**self.case(org=self.e2), "value": "41", "version": v["version"]}, MODERNE)
        self.assertTrue(res["isError"])
        self.assertIn("01/01/2027", d["error"]["message"])
        self.assertEqual(Reponse.objects.get(periode=self.c.periode, kpi=self.eff, organisation=self.e2).valeur, 40)
