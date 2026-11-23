"""Aides des tests de l'onglet Cohérence : base (arbre, historique de 5 exercices, KPI, comptes) et aides du panneau de saisie."""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from parametres.referentiel import unite_depuis_symbole as U
from referentiel.models import KPI, Attribution, Niveau, Organisation, Utilisateur

from collecte import saisie as S
from collecte.models import Alerte, Campagne, Reponse

D = Decimal
FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}


class BaseCoherence(TestCase):
    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.p)
        self.e2 = Organisation.objects.create(nom="E2", niveau_id=Niveau.ENTITY, parent=self.p)
        self.anciennes = [Campagne.objects.create(exercice=ex, statut=Campagne.Statut.CLOTUREE) for ex in range(2021, 2026)]
        self.c = Campagne.objects.create(exercice=2026, statut=Campagne.Statut.OUVERTE, seuil_ecart=D("0.2"))
        self.eff = KPI.objects.create(code="EFF", libelle="Effectif", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY, unite=U("employees"))
        self.form = KPI.objects.create(code="FORM", libelle="Formés", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY, unite=U("employees"))
        self.fe = KPI.objects.create(code="FE1", libelle="Facteur", type_saisie_id="FE", granularite_id=Niveau.ENTITY, unite=U("kgCO2eq/L"),
                                     methode_agregation="Aucune")
        self.contrib = Utilisateur.objects.create(username="contrib", email="contrib@exemple.test")
        self.autre = Utilisateur.objects.create(username="autre", email="autre@exemple.test")
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        for k in (self.eff, self.form, self.fe):
            Attribution.objects.create(kpi=k, organisation=self.e1, utilisateur=self.contrib)
        for c in self.anciennes:  # historique stable : 100 salariés, FE 2,5
            for k, v in ((self.eff, 100), (self.fe, D("2.5")), (self.form, 50)):
                Reponse.objects.create(periode=c.periode, kpi=k, organisation=self.e1, valeur=D(v), statut=Reponse.Statut.VALIDE,
                                       origine=Reponse.Origine.IMPORT)

    def saisir(self, kpi, v, com="", na=False):
        return S.enregistrer(self.contrib, self.c, kpi, self.e1, str(v), na, com)

    def alertes(self, **filtre):
        return Alerte.objects.filter(campagne=self.c, **filtre)


class BasePanneau(BaseCoherence):
    def url(self, kpi=None, org=None):
        return reverse("collecte:cellule", args=[self.c.pk, (kpi or self.eff).pk, (org or self.e1).pk])

    def historique(self, v=260):
        """Valeur hors historique (sans seuil d'écart avec N-1) : une alerte « valeur inhabituelle » à justifier."""
        self.c.seuil_ecart = None
        self.c.save()
        self.saisir(self.eff, v)
        return self.alertes(controle="historique").get()

    def justifier(self, a, texte, utilisateur=None, kpi=None, org=None):
        self.client.force_login(utilisateur or self.contrib)
        return self.client.post(self.url(kpi, org), {"action": "justifier", "alerte": a.pk, "justification": texte}, **FETCH)
