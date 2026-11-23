"""Organisation désactivée sans date de désactivation (pas ouverte dans la période) : ``save_value`` refuse, comme
l'écran et l'import (même fonction ``saisie.enregistrer``).

Données inventées uniquement."""
from collecte.models import Reponse
from referentiel.models import Organisation

from .aides_tests import MODERNE, BaseMCP


class AssistantOrganisationDesactiveeTests(BaseMCP):
    def test_save_value_refuse(self):
        Organisation.objects.filter(pk=self.e2.pk).update(actif=False, date_desactivation=None)
        _, _, v = self.outil("admin", "get_value", self.case(org=self.e2), MODERNE)
        self.assertFalse(v["rights"]["can_change"])
        _, res, d = self.outil("admin", "save_value", {**self.case(org=self.e2), "value": "41", "version": v["version"]}, MODERNE)
        self.assertTrue(res["isError"])
        self.assertIn("E2", d["error"]["message"])
        self.assertEqual(Reponse.objects.get(periode=self.c.periode, kpi=self.eff, organisation=self.e2).valeur, 40)
