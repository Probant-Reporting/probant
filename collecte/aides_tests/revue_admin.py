"""Aides des tests des pages d'administration, d'échanges et de référentiels : administrateur connecté, deux entités, campagne, KPI."""
from decimal import Decimal

from django.test import TestCase

from collecte.models import Campagne
from referentiel.models import KPI, Niveau, Organisation, Utilisateur


class Base(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        self.contrib = Utilisateur.objects.create(username="contrib", email="contrib@exemple.test")
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.g)
        self.e2 = Organisation.objects.create(nom="E2", niveau_id=Niveau.ENTITY, parent=self.g)
        self.c = Campagne.objects.create(exercice=2025, statut=Campagne.Statut.OUVERTE, seuil_ecart=Decimal("0.2"))
        self.kpi = KPI.objects.create(code="EFF", libelle="Effectif", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY)
        self.client.force_login(self.admin)
