"""Conservation des preuves sensibles (``conservation.a_supprimer``) : un KPI commun à deux campagnes d'une même période n'est
proposé que lorsque toutes les campagnes qui le contiennent sont clôturées (une seule ouverte : la preuve sert encore)."""
import datetime

from collecte import conservation as CV
from collecte.models import Campagne
from referentiel.models import ElementReferentiel, Referentiel

from .test_conservation_preuves import AUJOURDHUI, ConservationBase


class DeuxCampagnesMemePeriodeTests(ConservationBase):
    def setUp(self):
        super().setUp()
        self.sensible()
        self.voisin = Referentiel.objects.create(code="VOIS", nom="Cadre voisin", ordre=98)
        ElementReferentiel.objects.create(referentiel=self.voisin, kpi=self.eff)
        self.voisine = Campagne.objects.create(referentiel=self.voisin, periode=self.c0.periode, exercice=self.c0.exercice,
                                               statut=Campagne.Statut.OUVERTE)

    def ids_dus(self):
        return [l["preuve"].pk for l in CV.a_supprimer(mois=1, aujourdhui=AUJOURDHUI)]

    def test_une_campagne_voisine_ouverte_garde_la_preuve(self):
        self.assertEqual(Campagne.objects.get(pk=self.c0.pk).statut, Campagne.Statut.CLOTUREE)
        self.assertEqual(self.ids_dus(), [])

    def test_les_deux_campagnes_cloturees_proposent_la_preuve(self):
        Campagne.objects.filter(pk=self.voisine.pk).update(statut=Campagne.Statut.CLOTUREE)
        self.assertEqual(self.ids_dus(), [self.preuve.pk])

    def test_voisine_ouverte_sans_ce_kpi_ne_retient_rien(self):
        ElementReferentiel.objects.filter(referentiel=self.voisin, kpi=self.eff).delete()
        ElementReferentiel.objects.create(referentiel=self.voisin, kpi=self.taux)
        self.assertEqual(self.ids_dus(), [self.preuve.pk])
        self.assertLess(self.c0.periode.fin, datetime.date(2026, 1, 1))
