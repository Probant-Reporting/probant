"""Après une modification, les contrôles de cohérence ne tournent que dans les campagnes en cours (ouvertes ou en revue)
de la période (``saisie.campagnes_des(..., en_cours=True)``, appelé par ``signals.apres_modification``) : une campagne
clôturée garde ses alertes telles qu'à la clôture."""
from unittest import mock

from . import saisie as S
from . import signals as SG
from .models import Campagne
from .aides_tests.saisie import Base


class CampagnesEnCoursTests(Base):
    def test_seules_les_campagnes_ouvertes_ou_en_revue(self):
        self.assertEqual(S.campagnes_des(self.c0.periode, ["EFF"]), [self.c0])  # sans filtre : la campagne clôturée aussi
        self.assertEqual(S.campagnes_des(self.c0.periode, ["EFF"], en_cours=True), [])
        self.assertEqual(S.campagnes_des(self.c.periode, ["EFF"], en_cours=True), [self.c])
        Campagne.objects.filter(pk=self.c.pk).update(statut=Campagne.Statut.REVUE)
        self.assertEqual([c.pk for c in S.campagnes_des(self.c.periode, ["EFF"], en_cours=True)], [self.c.pk])

    def test_controles_de_coherence_seulement_dans_la_campagne_en_cours(self):
        with mock.patch("collecte.coherence.controler") as controler:
            SG.apres_modification(self.c0.periode, ["EFF"], {self.e1.id})  # exercice clôturé : aucune alerte refaite
            self.assertEqual(controler.call_count, 0)
            SG.apres_modification(self.c.periode, ["EFF"], {self.e1.id})  # campagne ouverte : alertes refaites
            self.assertEqual([(appel.args[0].pk, appel.args[1]) for appel in controler.call_args_list], [(self.c.pk, ["EFF"])])
