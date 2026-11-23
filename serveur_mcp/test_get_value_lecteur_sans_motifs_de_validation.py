"""Assistants (``get_value``) : ce qui bloque la validation d'une case saisie n'est jamais donné à un lecteur (le motif
citerait des brouillons : écart, règle bloquante), alors que l'auditeur, qui lit les brouillons, le reçoit."""
from referentiel.models import KPI

from .aides_tests import MODERNE, BaseMCP
from .models import ReglageMCP


class MotifsDeValidationTests(BaseMCP):
    def setUp(self):
        super().setUp()
        ReglageMCP.objects.filter(pk=1).update(lecteur_lit=True)
        KPI.objects.filter(code="EFF").update(preuve_obligatoire=True)  # la case de e1 est un brouillon sans preuve

    def blocs(self, role):
        _, res, d = self.outil(role, "get_value", self.case(), MODERNE)
        self.assertFalse(res["isError"], d)
        return d["blocks_validation"]

    def test_l_auditeur_et_l_admin_les_recoivent(self):
        for role in ("auditeur", "admin"):
            self.assertTrue(self.blocs(role), role)

    def test_le_lecteur_n_en_recoit_aucun(self):
        self.assertEqual(self.blocs("lecteur"), [])
