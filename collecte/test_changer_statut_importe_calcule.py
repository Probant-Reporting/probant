"""« Le calcul doit être à jour » : un chiffre importé tel quel sur une case calculée devient le
chiffre officiel à la clôture de sa période ; les périodes ouvertes qui le lisent ([X@N-1], cumul des mois, [X@P-1]) sont
recalculées à ce moment, sans attendre un recalcul ultérieur, et sans toucher aux chiffres de la période clôturée.
Une valeur forcée (panneau ou import confirmé) est, elle, propagée dès le forçage : la clôture ne change rien."""
import datetime
from decimal import Decimal as D

from referentiel.models import KPI, Niveau

from . import forcage as FO
from . import saisie as S
from .administration import changer_statut
from .calcul import recalculer
from .models import Campagne, Periode, Reponse
from .test_importer_forcer_calcule import ForcerParImportBase


class ClotureEtChiffreImporteTests(ForcerParImportBase):
    """DBL = [EFF] * 2 (somme au-dessus), W = [DBL@N-1] ; 2025 (c0) et 2026 (c) ouverts ; E1 : DBL 2025 calculé 20."""

    def test_valeur_forcee_propagee_des_le_forcage_et_rien_a_la_cloture(self):
        FO.demander(self.admin, self.c0, self.calc, self.e1, "99", False, "Chiffre publié")
        self.assertEqual(self.v("W", self.e1), D(99))  # 2026 lit la valeur forcée de 2025 tout de suite
        changer_statut(self.admin, self.c0, "cloturer")
        self.assertEqual(self.v("W", self.e1), D(99))
        recalculer(self.c)
        self.assertEqual((self.v("W", self.e1), self.v("W", self.p)), (D(99), D(109)))

    def test_chiffre_importe_officiel_a_la_cloture_periodes_ouvertes_a_jour(self):
        # chiffre importé d'avant la règle du 18/11 (« en sommeil ») : le calcul de 2025 ouverte ne l'utilise pas
        Reponse.objects.filter(periode=self.c0.periode, kpi_id="DBL", organisation=self.e1).update(
            origine=Reponse.Origine.IMPORT, statut=Reponse.Statut.VALIDE, valeur=D(99))
        recalculer(self.c)
        self.assertEqual(self.v("W", self.e1), D(20))
        total_2025 = self.v("DBL", self.p, self.c0)
        changer_statut(self.admin, self.c0, "cloturer")
        # le chiffre devient officiel : 2026, ouverte, le lit aussitôt (avant : 20 jusqu'au prochain recalcul, puis 99)
        self.assertEqual(self.v("W", self.e1), D(99))
        self.assertEqual(self.v("W", self.p), D(109))  # somme des W affichés : 99 + 5 × 2
        self.assertEqual(self.v("DBL", self.p, self.c0), total_2025)  # chiffres de 2025 clôturée : rien n'est réécrit
        self.assertEqual(self.r("DBL", self.e1, self.c0).origine, Reponse.Origine.IMPORT)
        recalculer(self.c)  # plus aucun saut sans changement de données
        self.assertEqual((self.v("W", self.e1), self.v("W", self.p)), (D(99), D(109)))

    def test_cloture_sans_chiffre_importe_ne_recalcule_rien(self):
        from unittest import mock

        from . import calcul as C

        with mock.patch.object(C, "recalculer", wraps=C.recalculer) as appel:
            changer_statut(self.admin, self.c0, "cloturer")
        self.assertEqual(appel.call_count, 0)

    def test_kpi_fige_par_une_campagne_cloturee_a_cote_d_une_ouverte(self):
        # règle « Figer ses chiffres » : la période 2025 garde une campagne ouverte, mais DBL est figé dès la clôture
        from referentiel.models import ElementReferentiel, Referentiel

        from .calcul import kpis_figes

        for k in (self.eff, self.calc):
            ElementReferentiel.objects.create(referentiel=self.c0.referentiel, kpi=k)
        autre = Referentiel.objects.create(code="AUTRE", nom="Cadre voisin", ordre=99)
        ElementReferentiel.objects.create(referentiel=autre, kpi=self.taux)
        Campagne.objects.create(referentiel=autre, periode=self.c0.periode, exercice=2025, statut=Campagne.Statut.OUVERTE)
        Reponse.objects.filter(periode=self.c0.periode, kpi_id="DBL", organisation=self.e1).update(
            origine=Reponse.Origine.IMPORT, statut=Reponse.Statut.VALIDE, valeur=D(99))
        changer_statut(self.admin, self.c0, "cloturer")
        self.assertIn("DBL", kpis_figes(self.c0.periode))
        self.assertEqual(self.v("W", self.e1), D(99))

    def test_periode_close_qui_lit_n_est_pas_touchee(self):
        # 2026 clôturée elle aussi : ses chiffres publiés ne bougent pas à la clôture de 2025
        Reponse.objects.filter(periode=self.c0.periode, kpi_id="DBL", organisation=self.e1).update(
            origine=Reponse.Origine.IMPORT, statut=Reponse.Statut.VALIDE, valeur=D(99))
        changer_statut(self.admin, self.c, "cloturer")
        changer_statut(self.admin, self.c0, "cloturer")
        self.assertEqual(self.v("W", self.e1), D(20))


class ClotureDUnMoisTests(ForcerParImportBase):
    """Périodes mensuelles : M = [EFF] * 3 calculé dans le référentiel mensuel ; S = [M@P-1] (un KPI calculé ne se cumule
    pas dans le temps : l'année refait sa formule sur ses sources cumulées, elle ne lit pas le M des mois)."""

    def setUp(self):
        super().setUp()
        from referentiel.models import ElementReferentiel, Referentiel

        mensuel = Referentiel.objects.create(nom="Mensuel", code="MENS", ordre=2, frequence="mois")
        self.m = KPI.objects.create(code="M", libelle="Triple", type_saisie_id="Calculé", formule="[EFF] * 3",
                                    granularite_id=Niveau.ENTITY, methode_agregation="Somme")
        self.s = KPI.objects.create(code="S", libelle="Triple du mois d'avant", type_saisie_id="Calculé", formule="[M@P-1]",
                                    granularite_id=Niveau.ENTITY, methode_agregation="Somme")
        for i, k in enumerate((self.eff, self.m, self.s)):
            ElementReferentiel.objects.create(referentiel=mensuel, kpi=k, ordre=i)
        from . import periodes as P

        self.jan, _ = P.campagne(mensuel, datetime.date(2026, 1, 1), statut=Campagne.Statut.OUVERTE)
        self.fev, _ = P.campagne(mensuel, datetime.date(2026, 2, 1), statut=Campagne.Statut.OUVERTE)
        for camp in (self.jan, self.fev):
            S.enregistrer(self.admin, camp, self.eff, self.e1, "1", False, "")
            S.enregistrer(self.admin, camp, self.eff, self.e2, "1", False, "")
        for camp in (self.jan, self.fev, self.c):
            recalculer(camp)

    def val(self, periode, code, org):
        r = Reponse.objects.filter(periode=periode, kpi_id=code, organisation=org).first()
        return None if r is None else r.valeur

    def test_cloture_du_mois_met_a_jour_le_mois_suivant(self):
        annee = Periode.objects.get(pk=self.c.periode_id)
        self.assertEqual(self.val(self.fev.periode, "S", self.e1), D(3))
        annuel = self.val(annee, "M", self.e1)
        Reponse.objects.filter(periode=self.jan.periode, kpi_id="M", organisation=self.e1).update(
            origine=Reponse.Origine.IMPORT, statut=Reponse.Statut.VALIDE, valeur=D(50))
        changer_statut(self.admin, self.jan, "cloturer")
        self.assertEqual(self.val(self.fev.periode, "S", self.e1), D(50))  # [M@P-1] de février
        self.assertEqual(self.val(annee, "M", self.e1), annuel)  # l'année refait [EFF] * 3 sur son effectif
        self.assertEqual(self.val(self.jan.periode, "M", self.p), D(6))  # total de janvier clôturé : inchangé
