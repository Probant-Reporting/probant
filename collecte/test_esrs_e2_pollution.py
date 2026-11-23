"""Modèle « ESRS E2 – Pollution » : contrôle et couverture, tableaux de rejets de la norme volontaire VS repris comme types de
réponse (KPI distincts), installation seule puis avec la VS dans une base neuve, niveaux (entité pour les substances, site
pour les rejets et les microplastiques, entreprise pour les textes), substances additionnées entité par entité, règle de
cohérence « substance extrêmement préoccupante ≤ substance préoccupante », même grandeur pour les paragraphes 18(d) et 19(b),
mesures transitoires écrites dans les descriptions."""
import csv
import datetime
from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from referentiel.bibliotheque import controle as C
from referentiel.bibliotheque import socles as S
from referentiel.bibliotheque.definitions import couverture, esrs_e2
from referentiel.models import KPI, ElementReferentiel, Organisation, Referentiel

from . import coherence as CO
from . import paquets as P
from .aides_tests.paquets import vider
from .calcul import Calculateur, recalculer
from .models import Campagne, Periode, RegleCoherence, Reponse

D = Decimal
SOC = ("ACHETEES", "FABRIQUEES", "MISES-MARCHE", "REJETEES")


def installer(fichier):
    a = P.analyser(P.fourni(fichier).paquet, source=fichier, fourni=True)
    assert a.erreur == "" and a.compteurs["rejet"] == 0 and a.compteurs["conflit"] == 0, (a.erreur, a.compteurs)
    P.appliquer(None, a)


class ModelePollutionTests(SimpleTestCase):
    def test_controle_et_couverture(self):
        socle = next(s for s in S.SOCLES if s["code"] == "ESRS_E2")
        r = C.controler(socle, couverture=couverture(esrs_e2), propres=set(esrs_e2.KPIS), regles_propres=set(esrs_e2.REGLES))
        self.assertEqual(r.erreurs, [])
        self.assertEqual((r.chiffres["couverture"]["total"], r.chiffres["couverture"]["taux"]), (21, 100))
        self.assertEqual((r.chiffres["kpi"], r.chiffres["calcules"], r.chiffres["regles"]), (30, 0, 4))

    def test_rejets_de_la_vs_non_repris_mais_leurs_types_de_tableau_oui(self):
        codes = {c for c, *_ in C.elements(esrs_e2.SOCLE)}
        self.assertFalse({"POL-REJETS", "POL-REJETS-AUTRES", "POL-DECLARATION", "POL-PUBLIC", "POL-URL"} & codes)
        self.assertEqual(esrs_e2.KPIS["POL-EMISSIONS"]["reponse"], "VS-TAB-POLLUANTS")
        self.assertEqual(esrs_e2.KPIS["POL-EMISSIONS-AUTRES"]["reponse"], "VS-TAB-POLLUANTS-AUTRES")

    def test_chaque_ligne_de_la_liste_a_son_kpi_et_les_deux_paragraphes_des_rejets_de_svhc_un_seul(self):
        _, lignes, _ = C.lire_couverture(couverture(esrs_e2), "ESRS_E2")
        par_ref = {ligne["reference"]: ligne["kpi_codes"].split() for ligne in lignes}
        self.assertEqual(len(par_ref), 21)
        self.assertIn("POL-SVHC-REJETEES", par_ref["E2 · E2-5 §18(d) (2)"])  # §18(d), fabricant
        self.assertIn("POL-SVHC-REJETEES", par_ref["E2 · E2-5 §19(b)"])  # §19(b), utilisateur : même grandeur
        d = esrs_e2.KPIS["POL-SVHC-REJETEES"]["description"][1]
        self.assertIn("§18(d)", d)
        self.assertIn("§19(b)", d)
        with open(couverture(esrs_e2), encoding="utf-8-sig", newline="") as f:
            ids = {ligne["reference"] for ligne in csv.DictReader(f) if ligne["template"] == "ESRS_E2"}
        self.assertEqual(ids, set(par_ref))

    def test_substances_au_niveau_de_l_entite_et_champ_dans_la_description(self):
        for suffixe in SOC:
            d = esrs_e2.KPIS[f"POL-SOC-{suffixe}"]
            with self.subTest(suffixe):
                self.assertEqual((d["niveau"], d["unite"], d["agregation"]), ("entite", "t", "Somme"))
                self.assertIn("E2 AR 4", d["description"][1])
                self.assertIn("N/A", d["description"][1])
        d = esrs_e2.KPIS["POL-SVHC-UTILISEES"]["description"][1]
        self.assertIn("outside the scope of §18", d)  # §19 : utilisateurs seulement, E2 AR 4

    def test_mesures_transitoires_ecrites_dans_les_descriptions(self):
        for suffixe in SOC:  # §125(d), §126(d), §127(d) : informations quantitatives sur les substances préoccupantes
            self.assertIn("§125(d)", esrs_e2.KPIS[f"POL-SOC-{suffixe}"]["description"][1])
            self.assertIn("2030", esrs_e2.KPIS[f"POL-SOC-{suffixe}"]["description"][0])
        for code in ("POL-SVHC-ARTICLES-ACHETES", "POL-SVHC-ARTICLES-VENDUS"):  # §125(e), §126(e), §127(e) : utilisateurs d'articles
            self.assertIn("§127(e)", esrs_e2.KPIS[code]["description"][1])
        # pas de mesure propre aux totaux ; seulement l'entrée progressive de toute la norme (§126(a))
        d = esrs_e2.KPIS["POL-SVHC-ACHETEES"]["description"][1]
        self.assertNotIn("§127(e)", d)
        self.assertNotIn("§125(d)", d)
        self.assertTrue(d.endswith("(ESRS 1 §126(a))."))


class InstallationPollutionSeuleTests(TestCase):
    """ESRS E2 installé sans la VS : les types de tableau de rejets et leur liste de polluants viennent avec lui."""

    @classmethod
    def setUpTestData(cls):
        vider()
        installer("esrs_e2.json")

    def test_types_de_reponse_complets(self):
        from parametres.models import TypeReponse

        t = TypeReponse.objects.get(code=KPI.objects.get(code="POL-EMISSIONS").type_reponse_id)
        self.assertEqual([c["code"] for c in t.colonnes], ["polluant", "air", "eau", "sol"])
        self.assertTrue(TypeReponse.objects.filter(code="VS-POLLUANT", format=TypeReponse.Format.LISTE).exists())
        t = TypeReponse.objects.get(code=KPI.objects.get(code="POL-SVHC-TAB").type_reponse_id)
        self.assertEqual([c["code"] for c in t.colonnes], ["classe", "achetees", "fabriquees", "mises_marche", "utilisees", "rejetees"])


class InstallationPollutionTests(TestCase):
    """Base neuve : la VS de base, puis ESRS E2 ; deux entités avec un site chacune."""

    @classmethod
    def setUpTestData(cls):
        vider()
        installer("vs_base.json")
        cls.rejets_vs = list(KPI.objects.filter(code__in=("POL-REJETS", "POL-REJETS-AUTRES")).values())
        installer("esrs_e2.json")
        cls.g = Organisation.objects.create(nom="Groupe", niveau_id="Group")
        fr = Organisation.objects.create(nom="France", niveau_id="Country", parent=cls.g)
        cls.e1 = Organisation.objects.create(nom="Entité 1", niveau_id="Entity", parent=fr)
        cls.e2 = Organisation.objects.create(nom="Entité 2", niveau_id="Entity", parent=fr)
        cls.s1 = Organisation.objects.create(nom="Usine 1", niveau_id="Site", parent=cls.e1)
        cls.s2 = Organisation.objects.create(nom="Usine 2", niveau_id="Site", parent=cls.e2)
        cls.p = Periode.objects.create(type="annee", debut=datetime.date(2026, 1, 1), fin=datetime.date(2026, 12, 31),
                                       libelle="2026")
        cls.c = Campagne.objects.create(referentiel=Referentiel.objects.get(code="ESRS_E2"), periode=cls.p, exercice=2026,
                                        statut=Campagne.Statut.OUVERTE)
        for org, code, v in ((cls.s1, "POL-MICROPLASTIQUES", "12.5"), (cls.s2, "POL-MICROPLASTIQUES", "7.25"),
                             (cls.s1, "POL-MICROPLASTIQUES-REJETS", "0.5"), (cls.s2, "POL-MICROPLASTIQUES-REJETS", "0.25"),
                             (cls.e1, "POL-SOC-ACHETEES", "10"), (cls.e2, "POL-SOC-ACHETEES", "5"),
                             (cls.e1, "POL-SVHC-ACHETEES", "3"), (cls.e2, "POL-SVHC-ACHETEES", "1"),
                             (cls.e1, "POL-SVHC-REJETEES", "0.004"), (cls.e2, "POL-SVHC-REJETEES", "0.001")):
            Reponse.objects.create(periode=cls.p, kpi_id=code, organisation=org, valeur=D(v), statut=Reponse.Statut.VALIDE)
        recalculer(cls.c)

    def val(self, code, org):
        return Calculateur(self.c).valeur(code, org.id)

    def test_kpi_de_la_vs_intacts_et_kpi_distincts(self):
        self.assertEqual(list(KPI.objects.filter(code__in=("POL-REJETS", "POL-REJETS-AUTRES")).values()), self.rejets_vs)
        for code in ("POL-REJETS", "POL-EMISSIONS"):
            self.assertEqual(KPI.objects.filter(code=code).count(), 1)
        self.assertFalse(ElementReferentiel.objects.filter(referentiel__code="ESRS_E2", kpi_id="POL-REJETS").exists())

    def test_niveaux_choisis_par_l_outil(self):
        self.assertEqual(KPI.objects.get(code="POL-POLIT-CONTENU").granularite_id, "Group")
        self.assertEqual(KPI.objects.get(code="POL-SVHC-ARTICLES-ACHETES").granularite_id, "Group")
        self.assertEqual(KPI.objects.get(code="POL-EMISSIONS").granularite_id, "Site")
        self.assertEqual(KPI.objects.get(code="POL-MICROPLASTIQUES").granularite_id, "Site")
        for code in ("POL-SOC-ACHETEES", "POL-SVHC-REJETEES", "POL-SVHC-UTILISEES", "POL-SVHC-TAB"):
            self.assertEqual(KPI.objects.get(code=code).granularite_id, "Entity", code)  # une déclaration par entité

    def test_microplastiques_additionnes_sur_les_sites(self):
        self.assertEqual(self.val("POL-MICROPLASTIQUES", self.g), D("19.75"))
        self.assertEqual(self.val("POL-MICROPLASTIQUES-REJETS", self.g), D("0.75"))

    def test_substances_additionnees_entite_par_entite(self):
        self.assertEqual(self.val("POL-SOC-ACHETEES", self.e1), D(10))
        self.assertEqual(self.val("POL-SOC-ACHETEES", self.g), D(15))
        self.assertEqual(self.val("POL-SVHC-ACHETEES", self.g), D(4))
        self.assertEqual(self.val("POL-SVHC-REJETEES", self.g), D("0.005"))

    def alertes(self):
        return {(a["regle"].nom, a["org"].id) for a in CO.controles_regles(self.c)}

    def test_regles_installees_et_respectees(self):
        self.assertEqual(set(esrs_e2.REGLES) - set(RegleCoherence.objects.values_list("nom", flat=True)), set())
        self.assertEqual(self.alertes(), set())

    def test_svhc_plus_grandes_que_les_substances_preoccupantes_signalees(self):
        Reponse.objects.filter(kpi_id="POL-SVHC-ACHETEES", organisation=self.e1).update(valeur=D(12))
        recalculer(self.c)
        self.assertEqual(self.alertes(), {("Substances extrêmement préoccupantes achetées ≤ substances préoccupantes achetées",
                                           self.e1.id)})
