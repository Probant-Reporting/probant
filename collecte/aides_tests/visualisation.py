"""Aides des tests de la visualisation : base avec thème."""


from collecte.aides_tests.echanges import Base
from referentiel.models import ElementReferentiel, Theme


class AvecTheme(Base):
    """Un thème « Social » et son sous-thème « Effectifs » rangent les trois KPI de la base."""

    def setUp(self):
        super().setUp()
        ref = self.c.referentiel
        self.theme = Theme.objects.create(referentiel=ref, code="SOC", nom="Social")
        sous = Theme.objects.create(referentiel=ref, code="EFF", nom="Effectifs", parent=self.theme)
        for i, k in enumerate((self.eff, self.taux, self.calc)):
            ElementReferentiel.objects.update_or_create(referentiel=ref, kpi=k, defaults={"theme": sous, "ordre": i})
