"""Aides des tests de calcul : arbre d'organisations et KPI de base."""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from collecte.models import Campagne, Reponse
from referentiel.models import KPI, Niveau, Organisation, Utilisateur


D = Decimal
FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}


class Arbre(TestCase):
    """Groupe > Pays > E1, E2 ; Groupe > Pays 2 > E3 ; exercices 2025 (clôturé) et 2026 (ouvert)."""

    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.p2 = Organisation.objects.create(nom="Pays 2", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.p)
        self.e2 = Organisation.objects.create(nom="E2", niveau_id=Niveau.ENTITY, parent=self.p)
        self.e3 = Organisation.objects.create(nom="E3", niveau_id=Niveau.ENTITY, parent=self.p2)
        self.c0 = Campagne.objects.create(exercice=2025, statut=Campagne.Statut.CLOTUREE)
        self.c = Campagne.objects.create(exercice=2026, statut=Campagne.Statut.OUVERTE)
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)

    def kpi(self, code, t="Saisi", f="", gran=Niveau.ENTITY, agg="Somme", **autres):
        return KPI.objects.create(code=code, type_saisie_id=t, formule=f, granularite_id=gran, methode_agregation=agg, **autres)

    def saisir(self, kpi, org, v=None, camp=None, na=False, texte="", origine=Reponse.Origine.IMPORT):
        return Reponse.objects.create(periode=(camp or self.c).periode, kpi_id=kpi, organisation=org,
                                      valeur=None if na or v is None else D(v), texte=texte, non_applicable=na, origine=origine)

    def cellule(self, kpi, org, camp=None):
        return Reponse.objects.get(periode=(camp or self.c).periode, kpi_id=kpi, organisation=org)

    def post(self, vue, args=None, **donnees):
        self.client.force_login(self.admin)
        return self.client.post(reverse(f"collecte:{vue}", args=args), donnees, **FETCH).json()
