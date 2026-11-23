"""``sensibles.alerte_sensible`` : une alerte est sensible si elle porte sur un KPI caché par sa case, par les KPI de sa règle
notés à la détection (``kpis_concernes``) ou par les KPI que sa règle cite aujourd'hui (règle modifiée depuis la détection).
Une seule définition pour les assistants (MCP) et la prise IA."""
from collecte.models import Alerte, RegleCoherence
from referentiel.models import Niveau
from collecte.sensibles import alerte_sensible, kpis_regle

from .aides_tests.lecture_seule import Base


class AlerteSensibleTests(Base):
    def alerte(self, **kw):
        return Alerte.objects.create(campagne=self.c, organisation=self.e1, controle=Alerte.Controle.FORMAT,
                                     gravite=Alerte.Gravite.ALERTE, message="x", **kw)

    def test_sa_propre_case(self):
        self.assertTrue(alerte_sensible(self.alerte(kpi=self.eff), {"EFF"}))
        self.assertFalse(alerte_sensible(self.alerte(kpi=self.taux), {"EFF"}))

    def test_aucun_kpi_cache_rien_n_est_sensible(self):
        self.assertFalse(alerte_sensible(self.alerte(kpi=self.eff, kpis_concernes="EFF"), frozenset()))

    def test_kpi_de_la_regle_note_a_la_detection(self):
        a = self.alerte(kpi=self.taux, kpis_concernes="TX EFF")
        self.assertTrue(alerte_sensible(a, {"EFF"}))
        self.assertFalse(alerte_sensible(a, {"DBL"}))

    def test_kpi_cite_aujourd_hui_par_la_regle(self):
        regle = RegleCoherence.objects.create(nom="Règle", gauche="[TX]", operateur=">=", droite="[EFF] * 2", niveau_id=Niveau.ENTITY)
        self.assertEqual(kpis_regle(regle), {"TX", "EFF"})
        a = self.alerte(kpi=self.taux, regle=regle)  # rien noté à la détection : la règle d'aujourd'hui décide
        self.assertTrue(alerte_sensible(a, {"EFF"}))
        self.assertFalse(alerte_sensible(a, {"DBL"}))
