"""Nuit de fiabilité des calculs : tests de non-régression des écarts trouvés par les cas au hasard
(qa/calculation_fuzz.py, qa/formula_fuzz.py) et quelques cas aléatoires rejoués à chaque passage de la suite.

Données inventées uniquement."""
import datetime
import sys
from decimal import Decimal
from pathlib import Path

from django.test import SimpleTestCase, TestCase

from referentiel import formule as F

from .templatetags.collecte import arrondi

D = Decimal
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "qa"))


class EspacesDansLesReferencesTests(SimpleTestCase):
    def test_espace_avant_le_crochet_apres_un_decalage(self):
        # « [A@N-1 ] » était refusé (« Référence invalide ») alors que « [A ] » et « [A @ N-1] » passaient
        for texte in ("[A@N-1 ]", "[ A @ N-1 ]", "[A@2021 ]", "[A @P-1  ]", "[A@N ]"):
            with self.subTest(texte=texte):
                ref = F.analyser(texte)
                self.assertEqual(ref.kpi, "A")
        self.assertEqual(F.analyser("[A@N-1 ]"), F.analyser("[A@N-1]"))
        self.assertEqual(F.renommer("[A@N-1 ] + [B]", {"A": "Z"}), "[Z@N-1 ] + [B]")

    def test_reference_sans_code_refusee(self):
        # « [ ] » donnait une référence au KPI « » : la formule n'était refusée qu'ensuite, avec un code vide
        for texte in ("[ ]", "[ @N-1]", "[A] + [  ]", "[@2021]"):
            with self.subTest(texte=texte), self.assertRaises(F.FormuleInvalide):
                F.analyser(texte)


class ArrondiCommeExcelTests(SimpleTestCase):
    def test_flottant_lu_a_15_chiffres(self):
        # 0,1 + 0,235 = 0.33499999999999996 en binaire : Excel le lit 0,335 (15 chiffres) et l'arrondit à 0,34
        self.assertEqual(arrondi(0.1 + 0.235, 2), D("0.34"))
        self.assertEqual(arrondi(0.2 + 0.025, 2), D("0.23"))
        self.assertEqual(arrondi(-(0.1 + 0.235), 2), D("-0.34"))
        self.assertEqual(arrondi(2.675, 2), D("2.68"))
        self.assertEqual(arrondi(1e20, 0), D("1E+20"))
        self.assertEqual(str(arrondi(float("nan"), 2)), "NaN")  # laissé tel quel, sans erreur

    def test_decimaux_inchanges(self):
        self.assertEqual(arrondi(D("0.125"), 2), D("0.13"))
        self.assertEqual(arrondi(D("-2.5")), D("-3"))
        self.assertEqual(arrondi(D("0.33499999999999996"), 2), D("0.33"))  # un décimal est exact : pas relu


class CasAuHasardTests(TestCase):
    """Quelques cas aléatoires (graines fixes) : l'outil et le second calcul indépendant donnent les mêmes cases."""

    def test_cas_au_hasard(self):
        import calculation_fuzz as CF

        for graine in (3, 17, 42, 108):
            with self.subTest(graine=graine):
                differences, compte = CF.verifier(CF.generate(graine))
                self.assertEqual(differences, {})
                self.assertTrue(compte)


# ---------------------------------------------------------------- chemins jamais testés (mesure de couverture)

from referentiel.models import KPI, Niveau, Organisation  # noqa: E402

from .calcul import Calculateur, recalculer  # noqa: E402
from .models import Campagne, Reponse  # noqa: E402


class TotalPublieRepliTests(TestCase):
    """README : un chiffre publié par un fichier historique (origine « import ») sert aux totaux et formules au-dessus quand le
    calcul n'est pas possible (détail manquant), pour le total d'un KPI saisi comme pour un KPI calculé ; il ne remplace
    jamais un total calculable. Dans une période clôturée, il est le chiffre officiel."""

    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.p)
        self.e2 = Organisation.objects.create(nom="E2", niveau_id=Niveau.ENTITY, parent=self.p)
        KPI.objects.create(code="A", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY, methode_agregation="Somme")
        KPI.objects.create(code="X", type_saisie_id="Calculé", formule="[A] * 2", granularite_id=Niveau.ENTITY,
                           methode_agregation="Somme")
        KPI.objects.create(code="R", type_saisie_id="Calculé", formule="[X] / [A]", granularite_id=Niveau.ENTITY,
                           methode_agregation="Formule")

    def mettre(self, c, kpi, org, v, origine=Reponse.Origine.SAISIE):
        # sans le signal de recalcul : seules les données posées ici
        Reponse.objects.bulk_create([Reponse(periode=c.periode, kpi_id=kpi, organisation=org, valeur=D(v), origine=origine)])

    def test_total_d_un_kpi_saisi_et_d_un_kpi_calcule(self):
        c = Campagne.objects.create(exercice=2026, statut=Campagne.Statut.OUVERTE)
        self.mettre(c, "A", self.e1, 10)  # E2 manque : le total du pays ne se calcule pas
        self.mettre(c, "A", self.p, 25, Reponse.Origine.IMPORT)
        self.mettre(c, "X", self.p, 60, Reponse.Origine.IMPORT)
        calc = Calculateur(c)
        self.assertEqual(calc.valeur("A", self.g.id), D(25))  # le total publié remonte
        self.assertEqual(calc.valeur("X", self.g.id), D(60))
        self.assertEqual(calc.valeur("R", self.p.id), D("2.4"))  # 60 / 25
        self.mettre(c, "A", self.e2, 20)  # détail complet : le total calculé l'emporte
        calc = Calculateur(c)
        self.assertEqual(calc.valeur("A", self.g.id), D(30))
        self.assertEqual(calc.valeur("X", self.g.id), D(60))
        self.assertEqual(calc.valeur("R", self.p.id), D(2))

    def test_periode_cloturee_le_chiffre_importe_fait_foi(self):
        c = Campagne.objects.create(exercice=2025, statut=Campagne.Statut.CLOTUREE)
        self.mettre(c, "A", self.e1, 10)
        self.mettre(c, "A", self.e2, 20)
        self.mettre(c, "A", self.p, 31, Reponse.Origine.IMPORT)  # publié 31 alors que le détail donne 30
        recalculer(c)
        g = Reponse.objects.get(periode=c.periode, kpi_id="A", organisation=self.g)
        self.assertEqual((g.valeur, g.origine), (D(31), Reponse.Origine.AGREGATION))


class AnneeFixeDeLaPeriodeTests(TestCase):
    """Une formule qui cite l'année de sa propre période ([B@2026] dans la campagne 2026 ; exercice qui commence en
    juillet : [B@2022] dans l'exercice 2022/23) cite la période elle-même : une saisie de B la recalcule aussitôt.
    Avant, seules les formules qui citaient B sans décalage étaient refaites (cas au hasard, graine 166)."""

    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.p)
        for code in ("A", "B"):
            KPI.objects.create(code=code, type_saisie_id="Saisi", granularite_id=Niveau.ENTITY, methode_agregation="Somme")
        KPI.objects.create(code="X", type_saisie_id="Calculé", formule="[A] - [B@2026]", granularite_id=Niveau.ENTITY,
                           methode_agregation="Somme")
        KPI.objects.create(code="Y", type_saisie_id="Calculé", formule="[X] * 2", granularite_id=Niveau.ENTITY,
                           methode_agregation="Somme")

    def test_saisie_de_la_source_citee_par_son_annee(self):
        c = Campagne.objects.create(exercice=2026, statut=Campagne.Statut.OUVERTE)
        a = Reponse.objects.create(periode=c.periode, kpi_id="A", organisation=self.e1, valeur=D(100))
        b = Reponse.objects.create(periode=c.periode, kpi_id="B", organisation=self.e1, valeur=D(30))
        lire = lambda k, o=self.e1: Reponse.objects.get(periode=c.periode, kpi_id=k, organisation=o).valeur  # noqa: E731
        self.assertEqual((lire("X"), lire("Y"), lire("X", self.g)), (D(70), D(140), D(70)))
        b.valeur = D(40)
        b.save()  # comme une saisie : recalcul de B et de ce qui en dépend
        self.assertEqual((lire("X"), lire("Y"), lire("X", self.g)), (D(60), D(120), D(60)))
        a.valeur = D(50)
        a.save()
        self.assertEqual(lire("Y"), D(20))


# ---------------------------------------------------------------- import de valeurs : refus et validation impossible


class OrganisationFermeeApresCoupTests(TestCase):
    """Une organisation désactivée après coup, avec une date de fermeture avant la période en cours : ses anciens totaux
    calculés de la campagne en cours disparaissent (avant, ils restaient, et partaient dans les exports) ; ceux d'une
    période clôturée restent tels quels (cas au hasard, graine 3513)."""

    def test_anciens_totaux_retires_des_periodes_non_figees(self):
        g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=g)
        e = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=p)
        KPI.objects.create(code="A", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY, methode_agregation="Somme")
        c25 = Campagne.objects.create(exercice=2025, statut=Campagne.Statut.OUVERTE)
        c26 = Campagne.objects.create(exercice=2026, statut=Campagne.Statut.OUVERTE)
        for c in (c25, c26):
            Reponse.objects.create(periode=c.periode, kpi_id="A", organisation=e, valeur=D(10))
        c25.statut = Campagne.Statut.CLOTUREE
        c25.save()
        self.assertTrue(Reponse.objects.filter(periode=c26.periode, kpi_id="A", organisation=p).exists())
        from .calcul import recalculer_en_cours

        e.actif, e.date_desactivation = False, datetime.date(2025, 12, 31)
        e.save()
        p.actif, p.date_desactivation = False, datetime.date(2025, 12, 31)
        p.save()
        recalculer_en_cours()
        self.assertFalse(Reponse.objects.filter(periode=c26.periode, kpi_id="A", organisation=p).exists())
        self.assertEqual(Reponse.objects.get(periode=c26.periode, kpi_id="A", organisation=e).valeur, D(10))  # saisie gardée
        self.assertEqual(Reponse.objects.get(periode=c25.periode, kpi_id="A", organisation=p).valeur, D(10))  # figée


class AncienneSaisieKpiDevenuCalculeTests(TestCase):
    """Une ancienne saisie d'un KPI devenu calculé, sur une organisation fermée pendant la période, la faisait compter
    comme « ayant des valeurs » au premier recalcul seulement : le total passait d'incomplet à calculé au second
    recalcul (cas au hasard, graines 10570 et 20154). Elle ne compte plus : deux recalculs donnent le même total."""

    def test_deux_recalculs_donnent_le_meme_total(self):
        g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=g)
        fermee = Organisation.objects.create(nom="Fermée", niveau_id=Niveau.ENTITY, parent=p, actif=False,
                                             date_desactivation=datetime.date(2026, 6, 30))
        e2 = Organisation.objects.create(nom="E2", niveau_id=Niveau.ENTITY, parent=p)
        Organisation.objects.create(nom="Site", niveau_id=Niveau.SITE, parent=fermee, actif=False,
                                    date_desactivation=datetime.date(2026, 6, 30))
        KPI.objects.create(code="A", type_saisie_id="Saisi", granularite_id=Niveau.SITE, methode_agregation="Somme")
        KPI.objects.create(code="X", type_saisie_id="Calculé", formule="[A] * 2", granularite_id=Niveau.SITE,
                           methode_agregation="Somme")
        c = Campagne.objects.create(exercice=2026, statut=Campagne.Statut.OUVERTE)
        Reponse.objects.bulk_create([
            Reponse(periode=c.periode, kpi_id="X", organisation=fermee, valeur=D(5), origine=Reponse.Origine.SAISIE),
            Reponse(periode=c.periode, kpi_id="X", organisation=e2, valeur=D(0), origine=Reponse.Origine.FORCEE)])
        recalculer(c)
        premier = Reponse.objects.get(periode=c.periode, kpi_id="X", organisation=p)
        recalculer(c)
        second = Reponse.objects.get(periode=c.periode, kpi_id="X", organisation=p)
        self.assertEqual((premier.statut, premier.valeur), (second.statut, second.valeur))
        self.assertEqual((second.statut, second.valeur), (Reponse.Statut.CALCULE, D(0)))
