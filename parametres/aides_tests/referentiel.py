"""Aides des tests de la fiche KPI et des référentiels : base (comptes, niveaux, unités) et adresses."""
import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from collecte import reglages as R
from collecte.models import Campagne
from parametres import referentiel as PR
from parametres.models import TypeReponse
from referentiel.models import Attribution, KPI, Niveau, Organisation, Utilisateur


FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}


URL = reverse("parametres:referentiel")


class Base(TestCase):
    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.p)
        self.e2 = Organisation.objects.create(nom="E2", niveau_id=Niveau.ENTITY, parent=self.p)
        self.c = Campagne.objects.create(exercice=2026, statut=Campagne.Statut.OUVERTE,
                                         date_fin_saisie=timezone.localdate() + datetime.timedelta(days=30))
        self.oui_non = TypeReponse.objects.create(code="OuiNon", libelle="Oui / non", format="oui_non", ordre=10)
        self.certif = TypeReponse.objects.create(code="Certif", libelle="Certification", format="liste", ordre=11,
                                                 valeurs=["Certifié", "En cours", "Non engagé"])
        self.eff = KPI.objects.create(code="EFF", libelle="Effectif", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                                      methode_agregation="Somme", unite=PR.unite_depuis_symbole("ETP"))
        self.pol = KPI.objects.create(code="POL", libelle="Politique formalisée", type_saisie_id="Saisi", type_reponse=self.oui_non,
                                      granularite_id=Niveau.ENTITY, methode_agregation="Décompte")
        self.cert = KPI.objects.create(code="CERT", libelle="Certification du site", type_saisie_id="Saisi", type_reponse=self.certif,
                                       granularite_id=Niveau.ENTITY, methode_agregation="Décompte")
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        self.contrib = Utilisateur.objects.create(username="contrib", email="contrib@exemple.test")
        for k in (self.eff, self.pol, self.cert):
            Attribution.objects.create(kpi=k, organisation=self.e1, utilisateur=self.contrib)

    def page(self, section, **donnees):
        self.client.force_login(self.admin)
        return self.client.post(f"{URL}?section={section}", donnees)

    def fiche(self, kpi, **changes):
        donnees = {c: getattr(kpi, f"{c}_id" if c in ("granularite", "type_saisie", "type_reponse", "unite") else c)
                   for c in R.CHAMPS_FICHE}
        donnees.update(changes)
        return {c: v for c, v in donnees.items() if v is not False and v is not None}

    def enregistrer_fiche(self, kpi, **changes):
        self.client.force_login(self.admin)
        url = reverse("collecte:referentiel_kpi_nouveau") if kpi._state.adding else reverse("collecte:referentiel_kpi", args=[kpi.code])
        return self.client.post(url, self.fiche(kpi, **changes), **FETCH).json()
