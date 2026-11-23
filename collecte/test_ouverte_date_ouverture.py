"""Règle du projet : date d'ouverture d'une organisation, « un site ne compte qu'à partir de cette
date » (``calcul.ouverte``, seule fonction qui porte la règle). Vide : ouverte depuis toujours, comme avant.

Données inventées uniquement."""
import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from referentiel.composition import composer
from referentiel.models import KPI, Niveau, Organisation, Referentiel, Utilisateur

from . import calcul as C
from . import periodes as P
from . import saisie as S
from .models import Campagne, Reponse

D = Decimal


class OuverteTests(TestCase):
    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.p25 = P.annuelle(2025)

    def org(self, **champs):
        return Organisation(nom="X", niveau_id=Niveau.ENTITY, parent=self.g, **champs)

    def test_sans_date_d_ouverture_rien_ne_change(self):
        self.assertTrue(C.ouverte(self.org(), self.p25))
        self.assertFalse(C.ouverte(self.org(actif=False), self.p25))
        self.assertTrue(C.ouverte(self.org(actif=False, date_desactivation=datetime.date(2025, 2, 1)), self.p25))
        self.assertFalse(C.ouverte(self.org(actif=False, date_desactivation=datetime.date(2024, 12, 31)), self.p25))

    def test_ouverte_a_partir_de_sa_date(self):
        self.assertFalse(C.ouverte(self.org(date_ouverture=datetime.date(2026, 1, 1)), self.p25))
        self.assertTrue(C.ouverte(self.org(date_ouverture=datetime.date(2025, 12, 31)), self.p25))  # dernier jour : compte
        self.assertTrue(C.ouverte(self.org(date_ouverture=datetime.date(2020, 6, 1)), self.p25))
        # ouverte puis fermée pendant la période : compte
        self.assertTrue(C.ouverte(self.org(date_ouverture=datetime.date(2025, 3, 1), actif=False,
                                           date_desactivation=datetime.date(2025, 9, 30)), self.p25))
        self.assertTrue(C.ouverte(self.org(date_ouverture=datetime.date(2030, 1, 1)), None))  # sans période : pas de date


class CalculAvecDateOuvertureTests(TestCase):
    """Groupe > E1, E2 ; E3 ouverte le 1er mars 2026 (sans valeur en 2025)."""

    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.g)
        self.e2 = Organisation.objects.create(nom="E2", niveau_id=Niveau.ENTITY, parent=self.g)
        self.e3 = Organisation.objects.create(nom="E3", niveau_id=Niveau.ENTITY, parent=self.g,
                                              date_ouverture=datetime.date(2026, 3, 1))
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        KPI.objects.create(code="EFF", libelle="Effectif", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                           methode_agregation="Somme")
        self.ref = Referentiel.objects.create(code="RAP", nom="Rapport", ordre=1)
        composer({"EFF": ["Social"]}, self.ref)
        fin = timezone.localdate() + datetime.timedelta(days=30)
        self.c25 = P.campagne(self.ref, datetime.date(2025, 1, 1), statut=Campagne.Statut.OUVERTE, date_fin_saisie=fin)[0]
        self.c26 = P.campagne(self.ref, datetime.date(2026, 1, 1), statut=Campagne.Statut.OUVERTE, date_fin_saisie=fin)[0]
        for c in (self.c25, self.c26):
            for org, v in ((self.e1, 10), (self.e2, 20)):
                Reponse.objects.create(periode=c.periode, kpi_id="EFF", organisation=org, valeur=D(v),
                                       statut=Reponse.Statut.VALIDE, origine=Reponse.Origine.SAISIE)

    def total(self, c):
        r = Reponse.objects.get(periode=c.periode, kpi_id="EFF", organisation=self.g)
        return r.valeur, r.statut

    def test_le_site_ne_compte_qu_a_partir_de_sa_date(self):
        C.recalculer(self.c25)
        C.recalculer(self.c26)
        self.assertEqual(self.total(self.c25), (D(30), Reponse.Statut.CALCULE))  # 2025 : E3 pas encore ouverte
        self.assertEqual(self.total(self.c26), (None, Reponse.Statut.INCOMPLET))  # 2026 : E3 compte, sans valeur

    def test_sans_date_le_site_compte_comme_avant(self):
        Organisation.objects.filter(pk=self.e3.pk).update(date_ouverture=None)
        C.recalculer(self.c25)
        self.assertEqual(self.total(self.c25), (None, Reponse.Statut.INCOMPLET))

    def test_cases_a_saisir_de_la_campagne(self):
        orgs25 = {o.id for k, o in S.cellules(self.admin, campagne=self.c25)}
        orgs26 = {o.id for k, o in S.cellules(self.admin, campagne=self.c26)}
        self.assertNotIn(self.e3.id, orgs25)  # rien à saisir, ni à relancer, ni dans le fichier à remplir
        self.assertIn(self.e3.id, orgs26)
        self.assertNotIn(self.e3.id, {o.id for o, *_ in S.organisations_visibles(self.admin, self.c25)})
