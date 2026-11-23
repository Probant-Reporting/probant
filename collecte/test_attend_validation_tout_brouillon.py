"""Règle « Tout brouillon compte » (règle du projet) : Visualisation des valeurs validées
(``visualisation.CalculateurValide.attend_validation``, aussi le serveur MCP pour un lecteur) × site fermé pendant la
période. Dès que le site fermé a, sur la période, une valeur pas encore validée, quel que soit le KPI, il compte dans
le total, qui n'a alors pas de valeur validée (« en attente de validation »), comme la Saisie dit « Incomplet ». Avant
 seul un brouillon du KPI affiché ou d'une source de sa formule le faisait compter ; avec un
brouillon d'un autre KPI, le total des valeurs validées était un chiffre (10) là où la Saisie disait « Incomplet ».

Le moteur de l'outil (valeurs enregistrées) ne change pas. Groupe > Pays > E1 (active), E2 (fermée le 30/06/2025).
Données inventées."""
import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from referentiel.composition import composer
from referentiel.models import KPI, Frequence, Niveau, Organisation, Referentiel, Utilisateur

from . import calcul as C
from . import periodes as P
from . import visualisation as V
from .models import Campagne, Reponse

FIN = timezone.localdate() + datetime.timedelta(days=30)


class ToutBrouillonCompteTests(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create(username="admin", email="a@exemple.test", role=Utilisateur.Role.ADMIN)
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.p)
        self.e2 = Organisation.objects.create(nom="E2", niveau_id=Niveau.ENTITY, parent=self.p, actif=False,
                                              date_desactivation=datetime.date(2025, 6, 30))
        for code in ("X", "Y", "M", "N"):
            KPI.objects.create(code=code, libelle=code, type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                               methode_agregation="Somme")
        self.annuel = Referentiel.objects.create(code="A", nom="Annuel", ordre=1, frequence=Frequence.ANNEE)
        composer({"X": ["S"], "Y": ["S"], "M": ["S"]}, self.annuel)
        self.mensuel = Referentiel.objects.create(code="MOIS", nom="Mensuel", ordre=2, frequence=Frequence.MOIS)
        composer({"M": ["S"], "N": ["S"]}, self.mensuel)  # M se cumule des mois dans l'année
        self.c, _ = P.campagne(self.annuel, datetime.date(2025, 1, 1), statut=Campagne.Statut.OUVERTE, date_fin_saisie=FIN)
        self.c24, _ = P.campagne(self.annuel, datetime.date(2024, 1, 1), statut=Campagne.Statut.OUVERTE,
                                 date_fin_saisie=FIN)
        self.mois = [P.campagne(self.mensuel, datetime.date(2025, m, 1), statut=Campagne.Statut.OUVERTE,
                                date_fin_saisie=FIN)[0] for m in range(1, 13)]

    def saisir(self, c, kpi, org, statut, v=10):
        Reponse.objects.create(periode=c.periode, kpi_id=kpi, organisation=org, valeur=Decimal(v), statut=statut,
                               origine=Reponse.Origine.SAISIE)

    def valide(self, code, org, codes):
        return V.CalculateurValide(codes).valeur(code, org.id, self.c.periode)

    def recalculer(self):
        for c in self.mois + [self.c24, self.c]:
            C.recalculer(c)

    def test_brouillon_d_un_autre_kpi(self):
        self.saisir(self.c, "X", self.e1, Reponse.Statut.VALIDE)
        self.saisir(self.c, "Y", self.e2, Reponse.Statut.BROUILLON)
        self.recalculer()
        total = Reponse.objects.get(periode=self.c.periode, kpi_id="X", organisation=self.p)
        self.assertEqual(total.statut, Reponse.Statut.INCOMPLET)  # la Saisie : « Incomplet »
        for codes in (None, ["X"]):
            with self.subTest(codes=codes):
                self.assertIsNone(self.valide("X", self.p, codes))  # avant : 10
                self.assertIsNone(self.valide("X", self.g, codes))

    def test_brouillon_d_un_autre_kpi_dans_les_mois_d_un_kpi_cumule(self):
        """M se cumule des mois : un brouillon de N dans un mois fait compter E2 dans l'année de M."""
        for c in self.mois:
            self.saisir(c, "M", self.e1, Reponse.Statut.VALIDE, 1)
        self.saisir(self.mois[2], "N", self.e2, Reponse.Statut.BROUILLON)
        self.recalculer()
        self.assertEqual(Reponse.objects.get(periode=self.c.periode, kpi_id="M", organisation=self.p).statut,
                         Reponse.Statut.INCOMPLET)
        for codes in (None, ["M"]):
            with self.subTest(codes=codes):
                self.assertEqual(V.CalculateurValide(codes).valeur("M", self.e1.id, self.c.periode), Decimal(12))
                self.assertIsNone(self.valide("M", self.p, codes))  # avant : 12

    def test_temoin_brouillon_d_une_autre_periode(self):
        """Témoin : un brouillon de E2 en 2024 seulement ne la fait pas compter en 2025 (elle n'y a aucune valeur)."""
        self.saisir(self.c, "X", self.e1, Reponse.Statut.VALIDE)
        self.saisir(self.c24, "Y", self.e2, Reponse.Statut.BROUILLON)
        self.recalculer()
        for codes in (None, ["X"]):
            with self.subTest(codes=codes):
                self.assertEqual(self.valide("X", self.p, codes), Decimal(10))

    def test_temoin_valeur_validee_du_site_ferme(self):
        """Témoin : E2 a une valeur validée de X : elle compte avec elle, le brouillon de Y n'empêche pas le total."""
        self.saisir(self.c, "X", self.e1, Reponse.Statut.VALIDE)
        self.saisir(self.c, "X", self.e2, Reponse.Statut.VALIDE, 20)
        self.saisir(self.c, "Y", self.e2, Reponse.Statut.BROUILLON)
        self.recalculer()
        for codes in (None, ["X"]):
            with self.subTest(codes=codes):
                self.assertEqual(self.valide("X", self.p, codes), Decimal(30))

    def test_moteur_de_l_outil_inchange(self):
        self.saisir(self.c, "X", self.e1, Reponse.Statut.VALIDE)
        self.saisir(self.c, "Y", self.e2, Reponse.Statut.BROUILLON)
        calc = C.Calculateur(self.c)
        self.assertFalse(calc.attend_validation(calc.kpis["X"], self.e2, self.c.periode))
