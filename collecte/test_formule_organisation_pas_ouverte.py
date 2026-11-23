"""Formule qui lit une autre période ([X@N-1], [X@P-1], [X@AAAA], ``Calculateur.valeur``) × organisation pas ouverte
pendant cette période.

README : une valeur gardée d'avant la date d'ouverture (après « Je confirme » sur la fiche) ne compte dans aucun total.
Avant la règle, elle entrait dans un chiffre publié par une formule d'une autre période : EV =
[EFF] - [EFF@N-1] de E3 (ouverte le 01/01/2025, 1 gardé en 2024) valait 5 - 1 = 4, et remontait au total. Règle : une
période où l'organisation n'est pas ouverte ne se lit pas : source manquante, comme pour une organisation créée cette
année (aucune valeur l'année d'avant) ou la première année d'un historique. Un paramètre hérité reste lu chez son
porteur, s'il est ouvert (le facteur de l'an dernier du pays vaut pour un site ouvert cette année). Données inventées."""
import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from referentiel.composition import composer
from referentiel.models import KPI, Niveau, Organisation, Referentiel

from . import calcul as C
from . import periodes as P
from .models import Campagne, Reponse

D = Decimal
FIN = timezone.localdate() + datetime.timedelta(days=30)


def rep(periode, kpi, org, v):
    Reponse.objects.update_or_create(periode=periode, kpi_id=kpi, organisation=org,
                                     defaults=dict(valeur=D(v), statut=Reponse.Statut.VALIDE, origine=Reponse.Origine.SAISIE))


def lue(periode, kpi, org):
    r = Reponse.objects.filter(periode=periode, kpi_id=kpi, organisation=org).first()
    return None if r is None else (r.valeur, r.statut)


class FormuleOrganisationPasOuverteTests(TestCase):
    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.p2 = Organisation.objects.create(nom="Pays 2", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.p)
        self.e3 = Organisation.objects.create(nom="E3", niveau_id=Niveau.ENTITY, parent=self.p2)
        KPI.objects.create(code="EFF", libelle="Eff", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY, methode_agregation="Somme")
        KPI.objects.create(code="FE", libelle="FE", type_saisie_id="FE", granularite_id=Niveau.COUNTRY, methode_agregation="Aucune")
        KPI.objects.create(code="EV", libelle="Ev", type_saisie_id="Calculé", granularite_id=Niveau.ENTITY,
                           methode_agregation="Somme", formule="[EFF]-[EFF@N-1]")
        KPI.objects.create(code="CO2", libelle="CO2", type_saisie_id="Calculé", granularite_id=Niveau.ENTITY,
                           methode_agregation="Somme", formule="[EFF]*[FE@N-1]")
        ref = Referentiel.objects.create(code="RAP", nom="Rapport", ordre=1)
        composer({"EFF": ["S"], "FE": ["S"], "EV": ["S"], "CO2": ["S"]}, ref)
        self.c24, _ = P.campagne(ref, datetime.date(2024, 1, 1), statut=Campagne.Statut.OUVERTE, date_fin_saisie=FIN)
        self.c25, _ = P.campagne(ref, datetime.date(2025, 1, 1), statut=Campagne.Statut.OUVERTE, date_fin_saisie=FIN)
        for o in (self.e1, self.e3):
            rep(self.c24.periode, "EFF", o, 1)
            rep(self.c25.periode, "EFF", o, 5)
        for o in (self.p, self.p2):
            rep(self.c24.periode, "FE", o, 2)
            rep(self.c25.periode, "FE", o, 3)
        # date d'ouverture posée après coup (« Je confirme ») : la valeur 2024 de E3 reste en base
        Organisation.objects.filter(pk=self.e3.pk).update(date_ouverture=datetime.date(2025, 1, 1))

    def test_valeur_gardee_d_avant_l_ouverture_ne_se_lit_pas(self):
        C.recalculer(self.c24)
        C.recalculer(self.c25)
        self.assertEqual(lue(self.c25.periode, "EV", self.e3)[1], Reponse.Statut.INCOMPLET)  # avant : 4 (5 - 1)
        self.assertIn("EFF", Reponse.objects.get(periode=self.c25.periode, kpi_id="EV", organisation=self.e3).message_calcul)
        self.assertEqual(lue(self.c25.periode, "EV", self.p2)[1], Reponse.Statut.INCOMPLET)  # avant : 4
        self.assertEqual(lue(self.c25.periode, "EV", self.e1), (D(4), Reponse.Statut.CALCULE))  # E1 : inchangée
        self.assertIsNone(C.Calculateur(self.c25).valeur("EV", self.e3.id))  # même règle à la lecture

    def test_comme_une_organisation_creee_cette_annee(self):
        """Même effet qu'une organisation sans valeur l'année d'avant : incomplet."""
        e4 = Organisation.objects.create(nom="E4", niveau_id=Niveau.ENTITY, parent=self.p)
        rep(self.c25.periode, "EFF", e4, 5)
        C.recalculer(self.c25)
        self.assertEqual(lue(self.c25.periode, "EV", e4)[1], Reponse.Statut.INCOMPLET)

    def test_parametre_herite_lu_chez_le_porteur_ouvert(self):
        """Le facteur de l'an dernier du pays (ouvert en 2024) vaut pour E3, ouverte en 2025 : CO2 = 5 × 2."""
        C.recalculer(self.c25)
        self.assertEqual(lue(self.c25.periode, "CO2", self.e3), (D(10), Reponse.Statut.CALCULE))
