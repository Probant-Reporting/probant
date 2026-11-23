"""Aides des tests de périodes, de cohérence et de calcul : Groupe > Pays > E1, E2, avec fabrique de KPI et de valeurs."""
from decimal import Decimal as D

from django.test import TestCase

from collecte.models import Reponse
from referentiel.models import KPI, Niveau, Organisation


class Base(TestCase):
    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.p)
        self.e2 = Organisation.objects.create(nom="E2", niveau_id=Niveau.ENTITY, parent=self.p)

    def kpi(self, code, t="Saisi", f="", gran=Niveau.ENTITY, agg="Somme", **autres):
        return KPI.objects.create(code=code, type_saisie_id=t, formule=f, granularite_id=gran, methode_agregation=agg, **autres)

    def mettre(self, kpi, org, periode, v, origine=Reponse.Origine.SAISIE, **autres):
        return Reponse.objects.create(periode=periode, kpi_id=kpi, organisation=org, valeur=None if v is None else D(v),
                                      origine=origine, **autres)

    def lire(self, kpi, org, periode):
        return Reponse.objects.get(periode=periode, kpi_id=kpi, organisation=org)
