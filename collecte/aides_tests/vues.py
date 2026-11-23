"""Aides des tests de l'API des vues : base."""
import json

from django.urls import reverse

from collecte.models import Alerte, Journal, Reponse, VueVisu
from collecte.aides_tests.visuels import AvecKpis
from referentiel.models import Utilisateur


VISUELS = [{"id": "a1", "type": "organisations", "kpis": ["EFF"]}, {"id": "a2", "type": "chiffre", "kpis": ["EFF"]}]


class Base(AvecKpis):
    def setUp(self):
        super().setUp()
        self.lecteur = Utilisateur.objects.create(username="lecteur", email="lecteur@exemple.test", role=Utilisateur.Role.LECTEUR)
        self.auditeur = Utilisateur.objects.create(username="auditeur", email="auditeur@exemple.test", role=Utilisateur.Role.AUDITEUR)
        self.partagee = VueVisu.objects.create(nom="Comité", proprietaire=self.admin, partage=True, visuels=VISUELS)

    def post(self, nom, donnees=None, args=(), client=None):
        return (client or self.client).post(reverse(f"collecte:{nom}", args=args), json.dumps(donnees or {}),
                                            content_type="application/json")

    def compter(self):
        return Reponse.objects.count(), Journal.objects.count(), Alerte.objects.count()
