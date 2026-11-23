"""Aides des tests des rôles en lecture seule : base."""
from django.urls import reverse

from collecte.aides_tests.visualisation import AvecTheme
from referentiel.models import Utilisateur


class Base(AvecTheme):
    def setUp(self):
        super().setUp()
        self.lecteur = Utilisateur.objects.create(username="lecteur", email="lecteur@exemple.test", role=Utilisateur.Role.LECTEUR)
        self.auditeur = Utilisateur.objects.create(username="auditeur", email="auditeur@exemple.test", role=Utilisateur.Role.AUDITEUR)

    def cellule(self, kpi="EFF", org=None):
        return reverse("collecte:cellule", args=[self.c.pk, kpi, (org or self.e1).pk])
