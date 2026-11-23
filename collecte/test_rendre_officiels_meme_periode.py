"""« Le calcul doit être à jour » dans la période elle-même (``calcul.rendre_officiels``) : la clôture d'une campagne A fige
partiellement un KPI X dont un chiffre importé devient officiel ; une campagne B OUVERTE de la même période demande un
KPI Y qui cite X : Y lit le chiffre officiel aussitôt, sans attendre un recalcul ultérieur, et X, figé, n'est pas
réécrit."""
from decimal import Decimal as D

from referentiel.models import KPI, ElementReferentiel, Niveau, Referentiel

from .administration import changer_statut
from .calcul import kpis_figes, recalculer
from .models import Campagne, Reponse
from .test_importer_forcer_calcule import ForcerParImportBase


class MemePeriodeTests(ForcerParImportBase):
    """DBL = [EFF] * 2 dans le référentiel de c0 (2025) ; Y = [DBL] * 10 dans un référentiel voisin, campagne ouverte de la
    même période ; E1 : DBL calculé 20, chiffre importé 99 (pas encore officiel tant que DBL n'est pas figé)."""

    def setUp(self):
        super().setUp()
        for k in (self.eff, self.calc):
            ElementReferentiel.objects.create(referentiel=self.c0.referentiel, kpi=k)
        self.y = KPI.objects.create(code="Y", libelle="Dix fois DBL", type_saisie_id="Calculé", formule="[DBL] * 10",
                                    granularite_id=Niveau.ENTITY, methode_agregation="Somme")
        autre = Referentiel.objects.create(code="AUTRE", nom="Cadre voisin", ordre=99)
        ElementReferentiel.objects.create(referentiel=autre, kpi=self.y)
        self.b = Campagne.objects.create(referentiel=autre, periode=self.c0.periode, exercice=2025,
                                         statut=Campagne.Statut.OUVERTE)
        Reponse.objects.filter(periode=self.c0.periode, kpi_id="DBL", organisation=self.e1).update(
            origine=Reponse.Origine.IMPORT, statut=Reponse.Statut.VALIDE, valeur=D(99))
        recalculer(self.b)

    def test_kpi_d_une_campagne_ouverte_qui_cite_le_kpi_fige(self):
        self.assertEqual(self.v("Y", self.e1, self.c0), D(200))  # le chiffre importé n'est pas encore officiel
        changer_statut(self.admin, self.c0, "cloturer")
        self.assertIn("DBL", kpis_figes(self.c0.periode))
        self.assertEqual(self.v("Y", self.e1, self.c0), D(990))  # lu aussitôt (avant : 200 jusqu'au prochain recalcul)
        self.assertEqual(self.v("DBL", self.e1, self.c0), D(99))  # figé : le chiffre importé reste tel quel
        self.assertEqual(self.r("DBL", self.e1, self.c0).origine, Reponse.Origine.IMPORT)
        total_dbl = self.v("DBL", self.p, self.c0)
        recalculer(self.b)  # plus aucun saut sans changement de données
        self.assertEqual(self.v("Y", self.e1, self.c0), D(990))
        self.assertEqual(self.v("DBL", self.p, self.c0), total_dbl)  # total figé : jamais réécrit
