"""Aides des tests de calcul : arbre France > E1, E2 (exercice 2025 clôturé, 2026 ouvert) et petit fichier CSV."""
import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from collecte.models import Campagne, Reponse
from referentiel.models import KPI, Niveau, Organisation, Utilisateur


D = Decimal


class Arbre(TestCase):
    """France › E1, E2 ; exercice 2025 clôturé, 2026 ouvert."""

    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.fr = Organisation.objects.create(nom="France", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.fr)
        self.e2 = Organisation.objects.create(nom="E2", niveau_id=Niveau.ENTITY, parent=self.fr)
        self.c0 = Campagne.objects.create(exercice=2025, statut=Campagne.Statut.CLOTUREE)
        self.c = Campagne.objects.create(exercice=2026, statut=Campagne.Statut.OUVERTE,
                                         date_fin_saisie=timezone.localdate() + datetime.timedelta(days=30))
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)

    def kpi(self, code, t="Saisi", f="", agg="Somme", **autres):
        return KPI.objects.create(code=code, libelle=code, type_saisie_id=t, formule=f, granularite_id=Niveau.ENTITY,
                                  methode_agregation=agg, **autres)

    def saisir(self, kpi, org, v=None, na=False, camp=None):
        return Reponse.objects.create(periode=(camp or self.c).periode, kpi_id=kpi, organisation=org, valeur=None if na else D(v),
                                      non_applicable=na, commentaire="Non concerné." if na else "", origine=Reponse.Origine.IMPORT,
                                      statut=Reponse.Statut.VALIDE)

    def cellule(self, kpi, org, camp=None):
        return Reponse.objects.get(periode=(camp or self.c).periode, kpi_id=kpi, organisation=org)


# ---------------------------------------------------------------- 3. paramètre hérité sans ancêtre de son niveau (CALC-09)
def csv_(lignes, nom="valeurs.csv"):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile(nom, ("\n".join(";".join(map(str, l)) for l in lignes) + "\n").encode())
