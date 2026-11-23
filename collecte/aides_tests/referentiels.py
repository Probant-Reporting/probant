"""Aides des tests des référentiels multiples : base."""
import datetime

from django.test import TestCase
from django.utils import timezone

from collecte.models import Campagne
from referentiel.composition import composer
from referentiel.models import Attribution, KPI, Niveau, Organisation, Referentiel, Utilisateur


class Base(TestCase):
    """Deux référentiels : « Reporting » (Environnement › Énergie › Électricité, Social) et « Énergie »
    (Consommations), qui partagent NRJ et ELEC."""

    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.p)

        def kpi(code, libelle, **autres):
            return KPI.objects.create(code=code, libelle=libelle, type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                                      methode_agregation="Somme", **autres)
        self.eff, self.nrj, self.elec = kpi("EFF", "Effectif"), kpi("NRJ", "Énergie totale"), kpi("ELEC", "Électricité")
        self.gaz = kpi("GAZ", "Gaz")  # au catalogue, mais dans aucun référentiel
        self.rse = Referentiel.objects.create(code="RSE", nom="Reporting", ordre=1, couleur="#1F5FAD")
        self.nrg = Referentiel.objects.create(code="ENERGIE", nom="Énergie", ordre=2, couleur="#E07A1F")
        composer({"NRJ": ["Environnement", "Énergie"], "ELEC": ["Environnement", "Énergie", "Électricité"], "EFF": ["Social"]}, self.rse)
        composer({"ELEC": ["Consommations"], "NRJ": ["Consommations"]}, self.nrg)
        fin = timezone.localdate() + datetime.timedelta(days=30)
        # deux campagnes annuelles 2026 (une par référentiel) : même période, donc mêmes réponses
        self.c = Campagne.objects.create(referentiel=self.rse, exercice=2026, statut=Campagne.Statut.OUVERTE, date_fin_saisie=fin)
        self.c_nrg = Campagne.objects.create(referentiel=self.nrg, exercice=2026, statut=Campagne.Statut.OUVERTE, date_fin_saisie=fin)
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        self.contrib = Utilisateur.objects.create(username="contrib", email="contrib@exemple.test")
        for k in (self.eff, self.nrj, self.elec):
            Attribution.objects.create(kpi=k, organisation=self.e1, utilisateur=self.contrib)
        self.client.force_login(self.admin)
