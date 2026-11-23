"""Audit du moteur de calcul (novembre 2026) : cas limites trouvés en relisant collecte/calcul.py et referentiel/formule.py.

Données inventées uniquement. Chaque test fige une règle écrite du README (« Calculation rules ») que le moteur ne
respectait pas, ou un comportement vérifié lors de l'audit."""
import datetime
from decimal import Decimal

from django.test import TestCase

from referentiel import formule as F
from referentiel.composition import composer
from referentiel.models import KPI, Niveau, Organisation, Referentiel

from . import periodes as P
from .calcul import Calculateur, recalculer
from .models import Campagne, Reponse

D = Decimal
NA = F.NA


def evaluer(texte, valeurs, na_zero=False):
    """Évalue une formule avec {code: valeur} (None : manquante) ; renvoie la valeur, « manquante » ou « erreur »."""
    try:
        return F.evaluer(F.analyser(texte), lambda r: valeurs.get(r.kpi), na_zero=na_zero)
    except F.ValeurManquante:
        return "manquante"
    except F.ErreurCalcul:
        return "erreur"


class OrdreDesTermesTests(TestCase):
    """Le résultat d'une formule ne dépend pas de l'ordre de ses termes (README : « whatever the order of the terms »)."""

    def test_division_par_un_vrai_zero_meme_apres_une_division_par_na(self):
        # case « N/A compte comme 0 » : diviser par une source N/A donne N/A, mais une vraie division par zéro ailleurs
        # dans la formule reste une erreur, quel que soit l'ordre
        v = {"A": D(1), "X": NA, "D": D(2), "E": D(0)}
        self.assertEqual(evaluer("[A] / [X] + [D] / [E]", v, na_zero=True), "erreur")
        self.assertEqual(evaluer("[D] / [E] + [A] / [X]", v, na_zero=True), "erreur")

    def test_source_manquante_et_division_par_zero(self):
        v = {"A": D(1), "B": D(0), "C": None}
        self.assertEqual(evaluer("[C] + [A] / [B]", v), "manquante")
        self.assertEqual(evaluer("[A] / [B] + [C]", v), "manquante")

    def test_source_manquante_et_division_par_na(self):
        v = {"A": D(1), "X": NA, "C": None}
        for na_zero in (False, True):
            self.assertEqual(evaluer("[C] + [A] / [X]", v, na_zero), "manquante")
            self.assertEqual(evaluer("[A] / [X] + [C]", v, na_zero), "manquante")

    def test_regles_inchangees(self):
        self.assertIs(evaluer("[A] / [X]", {"A": D(1), "X": NA}), NA)
        self.assertIs(evaluer("[A] / [X]", {"A": D(1), "X": NA}, na_zero=True), NA)
        self.assertEqual(evaluer("[A] / [B] + [X]", {"A": D(1), "B": D(0), "X": NA}), "erreur")
        self.assertEqual(evaluer("[X] + [A] / [B]", {"A": D(1), "B": D(0), "X": NA}), "erreur")
        self.assertEqual(evaluer("[A] + [X]", {"A": D(4), "X": NA}, na_zero=True), D(4))
        self.assertIs(evaluer("[A] + [X]", {"A": D(4), "X": NA}), NA)
        self.assertIs(evaluer("[X] + 1", {"X": NA}, na_zero=True), NA)
        self.assertEqual(evaluer("[A] / [B]", {"A": "Oui", "B": D(1)}), "erreur")


class Base(TestCase):
    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.p)
        self.e2 = Organisation.objects.create(nom="E2", niveau_id=Niveau.ENTITY, parent=self.p)

    def kpi(self, code, t="Saisi", f="", gran=Niveau.ENTITY, agg="Somme", **autres):
        return KPI.objects.create(code=code, type_saisie_id=t, formule=f, granularite_id=gran, methode_agregation=agg, **autres)

    def mettre(self, kpi, org, periode, v):
        return Reponse.objects.create(periode=periode, kpi_id=kpi, organisation=org, valeur=D(v), origine=Reponse.Origine.IMPORT)

    def lire(self, kpi, org, periode):
        return Reponse.objects.get(periode=periode, kpi_id=kpi, organisation=org)


class TropGrandTests(Base):
    def test_un_resultat_trop_grand_n_alimente_pas_les_formules_qui_le_citent(self):
        c = Campagne.objects.create(exercice=2026, statut=Campagne.Statut.OUVERTE)
        self.kpi("A")
        self.kpi("X", "Calculé", "[A] * 1000000")
        self.kpi("Y", "Calculé", "[X] / 1000000")
        self.mettre("A", self.e1, c.periode, "10000000000")  # X = 1e16 : au-delà de ce que la base garde
        calc = Calculateur(c)
        self.assertIsNone(calc.valeur("X", self.e1.id))
        self.assertIsNone(calc.valeur("Y", self.e1.id))  # et non 1e10, calculé à partir d'une valeur en erreur
        recalculer(c)
        x, y = self.lire("X", self.e1, c.periode), self.lire("Y", self.e1, c.periode)
        self.assertEqual((x.statut, x.valeur), (Reponse.Statut.ERREUR, None))
        self.assertIn("trop grand", x.message_calcul)
        self.assertEqual((y.statut, y.valeur, y.message_calcul), (Reponse.Statut.INCOMPLET, None, "Source manquante : X"))


class FermeesTests(Base):
    def test_total_sans_organisation_ouverte_avec_valeur_dit_pourquoi(self):
        c = Campagne.objects.create(exercice=2026, statut=Campagne.Statut.OUVERTE)
        self.e1.actif, self.e1.date_desactivation = False, datetime.date(2026, 6, 30)
        self.e1.save()
        self.e2.parent = self.g  # le pays n'a plus qu'une entité, fermée en cours d'année et sans valeur
        self.e2.save()
        self.kpi("A")
        calc = Calculateur(c)
        self.assertIsNone(calc.valeur("A", self.p.id))
        self.assertEqual(calc.message("A", self.p.id), "Incomplet : E1")
        vide = Organisation.objects.create(nom="Pays vide", niveau_id=Niveau.COUNTRY, parent=self.g)
        calc = Calculateur(c)
        self.assertIsNone(calc.valeur("A", vide.id))
        self.assertEqual(calc.message("A", vide.id), "Aucune organisation rattachée n'a ce KPI à son niveau")


class PropagationTests(Base):
    """Une saisie refait aussi les périodes non figées qui citent, par [ID@N-1] ou [ID@P-1], un KPI qu'elle a changé,
    même calculé, et de proche en proche."""

    def test_annee_suivante_qui_cite_un_kpi_calcule_change(self):
        c25 = Campagne.objects.create(exercice=2025, statut=Campagne.Statut.REVUE)
        c26 = Campagne.objects.create(exercice=2026, statut=Campagne.Statut.OUVERTE)
        self.kpi("A")
        self.kpi("X", "Calculé", "[A] * 2")
        self.kpi("EVOL", "Calculé", "[X] / [X@N-1]")
        self.mettre("A", self.e1, c25.periode, 1)
        self.mettre("A", self.e1, c26.periode, 4)
        recalculer(c25)
        self.assertEqual(self.lire("EVOL", self.e1, c26.periode).valeur, D(4))
        Reponse.objects.filter(periode=c25.periode, kpi_id="A", organisation=self.e1).update(valeur=D(2))
        recalculer(c25, ["A"])  # comme après une saisie de A en 2025
        self.assertEqual(self.lire("X", self.e1, c25.periode).valeur, D(4))
        self.assertEqual(self.lire("EVOL", self.e1, c26.periode).valeur, D(2))

    def test_cumul_de_mois_en_mois(self):
        mensuel = Referentiel.objects.create(code="STK", nom="Stock", ordre=1, frequence="mois")
        self.kpi("IN")
        self.kpi("S", "Calculé", "[S@P-1] + [IN]")
        composer({"IN": ["Flux"], "S": ["Flux"]}, mensuel)
        dec, _ = P.campagne(mensuel, datetime.date(2025, 12, 1), statut=Campagne.Statut.CLOTUREE)
        mois = {m: P.campagne(mensuel, datetime.date(2026, m, 1), statut=Campagne.Statut.OUVERTE)[0] for m in (1, 2, 3, 4)}
        self.mettre("S", self.e1, dec.periode, 100)  # stock de décembre, figé
        for m, c in mois.items():
            self.mettre("IN", self.e1, c.periode, 10)
        recalculer(mois[1])  # un recalcul complet de janvier refait aussi les mois suivants, de proche en proche
        self.assertEqual([self.lire("S", self.e1, mois[m].periode).valeur for m in (1, 2, 3, 4)], [D(110), D(120), D(130), D(140)])
        Reponse.objects.filter(periode=mois[1].periode, kpi_id="IN", organisation=self.e1).update(valeur=D(15))
        recalculer(mois[1], ["IN"])
        self.assertEqual([self.lire("S", self.e1, mois[m].periode).valeur for m in (1, 2, 3, 4)], [D(115), D(125), D(135), D(145)])
