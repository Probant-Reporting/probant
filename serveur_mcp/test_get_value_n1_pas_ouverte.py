"""``get_value`` : pas de comparaison avec N-1 pour une organisation qui n'était pas ouverte l'exercice comparé (date
d'ouverture posée après coup), comme la saisie et le calcul (``saisie.cases_comparables``).
Avant, l'outil annonçait l'écart avec la valeur gardée d'avant l'ouverture, pour tous les rôles."""
import datetime

from referentiel.models import Organisation

from .aides_tests import BaseMCP


class GetValueN1PasOuverteTests(BaseMCP):
    def test_temoin_comparaison_annoncee(self):
        _, res, d = self.outil("admin", "get_value", self.case())
        self.assertFalse(res["isError"], d)
        self.assertEqual(d["comparison"]["variance"], 0.1)  # 110 contre 100

    def test_pas_ouverte_en_n_1(self):
        Organisation.objects.filter(pk=self.e1.pk).update(date_ouverture=datetime.date(2026, 1, 1))
        for role in ("admin", "contributeur"):
            _, res, d = self.outil(role, "get_value", self.case())
            self.assertFalse(res["isError"], d)
            self.assertIsNone(d["comparison"]["value"], role)
            self.assertIsNone(d["comparison"]["variance"], role)
