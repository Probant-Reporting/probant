"""Aides des tests du nombre de requêtes : base et compteur de requêtes."""
from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from collecte.models import Campagne, Reponse
from parametres import langues as L
from parametres.referentiel import unite_depuis_symbole as U
from referentiel.models import KPI, Niveau, Organisation, Utilisateur


D = Decimal


def requetes(fn):
    """Requêtes SQL exécutées par fn() (liste des textes), langues lues une fois comme pendant une requête."""
    with L.session(), CaptureQueriesContext(connection) as ctx:
        fn()
    return [q["sql"] for q in ctx.captured_queries]


class Base(TestCase):
    """Un pays, des entités, des KPI saisis : on ajoute des lignes et on vérifie que les requêtes ne suivent pas."""

    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.entites = [Organisation.objects.create(nom=f"E{i}", niveau_id=Niveau.ENTITY, parent=self.p) for i in range(4)]
        self.c0 = Campagne.objects.create(exercice=2025, statut=Campagne.Statut.CLOTUREE)
        self.c = Campagne.objects.create(exercice=2026, statut=Campagne.Statut.OUVERTE, seuil_ecart=D("0.2"))
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        self.auditeur = Utilisateur.objects.create(username="audit", email="audit@exemple.test", role=Utilisateur.Role.AUDITEUR)
        self.kpis = []

    def campagne(self):
        """Campagne relue (sans les périmètres déjà gardés sur l'objet)."""
        return Campagne.objects.get(pk=self.c.pk)

    def ajouter_kpis(self, n):
        """n KPI saisis, avec une valeur en 2025 et une valeur très différente en 2026 (écart N-1) dans chaque entité."""
        debut = len(self.kpis)
        for i in range(debut, debut + n):
            k = KPI.objects.create(code=f"K{i}", libelle=f"KPI {i}", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                                   methode_agregation="Somme", unite=U("employees"))
            self.kpis.append(k)
            for o in self.entites:
                Reponse.objects.create(periode=self.c0.periode, kpi=k, organisation=o, valeur=D(100), statut=Reponse.Statut.VALIDE,
                                       origine=Reponse.Origine.IMPORT)
                Reponse.objects.create(periode=self.c.periode, kpi=k, organisation=o, valeur=D(300), statut=Reponse.Statut.BROUILLON,
                                       origine=Reponse.Origine.IMPORT)
