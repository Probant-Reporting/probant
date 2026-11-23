"""Visualisation des valeurs validées (``visualisation.CalculateurValide``) × valeur de l'année en brouillon d'un KPI
qui se cumule aussi depuis des périodes plus courtes.

Quatrième passe du calcul (``qa/calculation_fuzz.py --pages``, graines 10110 et 10129) : un KPI demandé par un
référentiel annuel et par un référentiel semestriel ; l'entité saisit l'année (brouillon, 31) alors que ses deux
semestres sont validés (10 et 5). La Saisie montre 31 : la valeur saisie de l'année remplace le cumul des semestres
(README, « Aggregation over time »). La Visualisation des valeurs validées ignorait le brouillon et retombait sur le
cumul des semestres validés : elle montrait 15 comme valeur validée de l'entité et de ses totaux, un chiffre que la
Saisie ne montre nulle part. Règle du module : un total dont une valeur n'est pas encore validée est « en attente de
validation ». Données inventées."""
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


class CalculateurValideBrouillonSurCumulTests(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create(username="admin", email="a@exemple.test", role=Utilisateur.Role.ADMIN)
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.g)
        KPI.objects.create(code="X", libelle="X", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                           methode_agregation="Somme")
        annuel = Referentiel.objects.create(code="A", nom="Annuel", ordre=1, frequence=Frequence.ANNEE)
        semestriel = Referentiel.objects.create(code="S", nom="Semestriel", ordre=2, frequence=Frequence.SEMESTRE)
        composer({"X": ["T"]}, annuel)
        composer({"X": ["T"]}, semestriel)
        self.c, _ = P.campagne(annuel, datetime.date(2025, 1, 1), statut=Campagne.Statut.OUVERTE, date_fin_saisie=FIN)
        semestres = [P.campagne(semestriel, datetime.date(2025, m, 1), statut=Campagne.Statut.OUVERTE,
                                date_fin_saisie=FIN)[0] for m in (1, 7)]
        for c, v in zip(semestres, (10, 5)):
            Reponse.objects.create(periode=c.periode, kpi_id="X", organisation=self.e1, valeur=Decimal(v),
                                   statut=Reponse.Statut.VALIDE, origine=Reponse.Origine.SAISIE)
        self.annee = Reponse.objects.update_or_create(
            periode=self.c.periode, kpi_id="X", organisation=self.e1,
            defaults=dict(valeur=Decimal(31), statut=Reponse.Statut.BROUILLON, origine=Reponse.Origine.SAISIE))[0]
        for c in semestres + [self.c]:
            C.recalculer(c)

    def test_brouillon_de_l_annee_attend_sa_validation(self):
        total = Reponse.objects.get(periode=self.c.periode, kpi_id="X", organisation=self.g)
        self.assertEqual(total.valeur, Decimal(31))  # la Saisie : la valeur saisie de l'année remplace le cumul
        for codes in (None, ["X"]):
            for org in (self.e1, self.g):
                with self.subTest(codes=codes, org=org.nom):
                    # avant : 15, le cumul des semestres validés
                    self.assertIsNone(V.CalculateurValide(codes).valeur("X", org.id, self.c.periode))
                    self.assertIsNone(V.Source(self.admin, codes=codes).point("X", org, self.c.periode).valeur)

    def test_temoin_valeur_de_l_annee_validee(self):
        """Témoin : la valeur de l'année validée, la Visualisation la montre (31), comme la Saisie."""
        self.annee.statut = Reponse.Statut.VALIDE
        self.annee.save()
        for org in (self.e1, self.g):
            with self.subTest(org=org.nom):
                self.assertEqual(V.CalculateurValide().valeur("X", org.id, self.c.periode), Decimal(31))

    def test_temoin_sans_valeur_de_l_annee(self):
        """Témoin : sans valeur de l'année, le cumul des semestres validés reste la valeur validée (15)."""
        self.annee.delete()
        C.recalculer(self.c)
        for org in (self.e1, self.g):
            with self.subTest(org=org.nom):
                self.assertEqual(V.CalculateurValide().valeur("X", org.id, self.c.periode), Decimal(15))
