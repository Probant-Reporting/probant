"""Condition d'une règle de cohérence (``regles_textes.formule_normalisee``, ``condition``) : la casse est gardée.

Défaut corrigé : la condition mettait les formules en majuscules. Les codes des KPI sont sensibles à la casse dans le moteur
(``referentiel.formule`` : la référence est lue telle quelle, ``verifier_formule`` et le calcul cherchent le code exact) :
« [abc] <= [t] » et « [ABC] <= [T] » portent sur quatre KPI différents (possibles avec la commande d'import historique des
KPI ou dans une installation plus ancienne que le contrôle de la casse), mais étaient vues comme une seule règle, et l'une
des deux n'était plus contrôlée.

L'inverse ne se produit pas : la syntaxe des formules n'a ni nom de fonction ni mot-clé dont la casse serait libre ; le
décalage s'écrit « N-1 », « P-1 », « N » ou une année, en majuscules seulement (« [X@n-1] » est refusé), et les nombres
s'écrivent en chiffres (aucun exposant « e »). Deux formules qui ne diffèrent que par la casse sont donc deux contrôles
différents, ou l'une est refusée."""
from decimal import Decimal

from django.test import SimpleTestCase

from referentiel import formule as F
from referentiel.models import KPI, Niveau

from . import coherence as CO
from . import regles_textes as RT
from .aides_tests.saisie import Base
from .models import Alerte, RegleCoherence, Reponse

D = Decimal


class ConditionCasseTests(SimpleTestCase):
    def test_casse_gardee_espaces_retires(self):
        self.assertNotEqual(RT.condition("[abc]", "<=", "[t]", 0, "Site"), RT.condition("[ABC]", "<=", "[T]", 0, "Site"))
        self.assertEqual(RT.condition("[ abc ] + [B]", "<=", "[t]", 0, "Site"), RT.condition("[abc]+[B]", "<=", "[t]", 0, "Site"))

    def test_aucune_ecriture_dont_la_casse_est_libre(self):
        """La seule écriture en lettres hors des codes est le décalage : en minuscules, il est refusé."""
        self.assertEqual(F.references("[X@N-1]")[0].decalage, "N-1")
        for texte in ("[X@n-1]", "[X@p-1]", "[X@n]", "1e3", "SUM([X])"):
            with self.subTest(texte), self.assertRaises(F.FormuleInvalide):
                F.analyser(texte)


class DeuxReglesQuiNeDifferentQueParLaCasseTests(Base):
    def setUp(self):
        super().setUp()
        for code in ("abc", "ABC"):
            KPI.objects.create(code=code, libelle=code, type_saisie_id="Saisi", granularite_id=Niveau.ENTITY, methode_agregation="Somme")
        self.minuscules = RegleCoherence.objects.create(nom="m", gauche="[abc]", operateur="<=", droite="10", niveau_id=Niveau.ENTITY)
        self.majuscules = RegleCoherence.objects.create(nom="M", gauche="[ABC]", operateur="<=", droite="10", niveau_id=Niveau.ENTITY)
        Reponse.objects.create(periode=self.c.periode, kpi_id="ABC", organisation=self.e1, valeur=D(20), statut=Reponse.Statut.BROUILLON)
        Reponse.objects.create(periode=self.c.periode, kpi_id="abc", organisation=self.e1, valeur=D(5), statut=Reponse.Statut.BROUILLON)

    def test_les_deux_regles_sont_controlees(self):
        self.assertEqual(CO.doublons([self.minuscules, self.majuscules]), {})
        CO.controler(self.c)
        self.assertEqual(list(Alerte.objects.filter(campagne=self.c, controle=Alerte.Controle.REGLE).values_list("regle__nom", flat=True)), ["M"])
