"""Calculs des modèles ESRS après la relecture du 18/11, sur des cas chiffrés (base neuve, VS de base installée d'abord) :
part du personnel couverte par la santé et la sécurité juste quand le nombre de non-salariés est N/A (0,9) ; part des
salariés couverts par une convention lue sur l'Espace économique européen (75 %) ; plus de fausse alerte entre l'eau
consommée en zone de stress hydrique et la consommation totale ; une catégorie du scope 3 non significative (N/A) compte
pour 0 dans le total ; parts des femmes et des hommes au conseil (ESRS 2 §12(a)) ; amendes et statut du plan de transition :
un seul KPI pour la VS et les ESRS."""
import datetime
from decimal import Decimal

from django.test import TestCase

from referentiel.models import KPI, ElementReferentiel, Organisation, Referentiel

from . import coherence as CO
from . import paquets as P
from .aides_tests.paquets import vider
from .calcul import NA, Calculateur, recalculer
from .models import Campagne, Periode, Reponse

D = Decimal


def installer(fichier):
    a = P.analyser(P.fourni(fichier).paquet, source=fichier, fourni=True)
    assert a.erreur == "" and a.compteurs["rejet"] == 0 and a.compteurs["conflit"] == 0, (a.erreur, a.compteurs)
    P.appliquer(None, a)


class CasChiffresTests(TestCase):
    """Groupe › Pays (EEE, hors EEE) › Entité › Site."""

    @classmethod
    def setUpTestData(cls):
        vider()
        for fichier in ("vs_base.json", "vs_complet.json", "esrs_2.json", "esrs_e1.json", "esrs_e3.json", "esrs_s1.json",
                        "esrs_g1.json"):
            installer(fichier)
        cls.g = Organisation.objects.create(nom="Groupe", niveau_id="Group")
        eee = Organisation.objects.create(nom="France", niveau_id="Country", parent=cls.g)
        hors = Organisation.objects.create(nom="Maroc", niveau_id="Country", parent=cls.g)
        cls.eee = eee
        e1 = Organisation.objects.create(nom="Entité FR", niveau_id="Entity", parent=eee)
        e2 = Organisation.objects.create(nom="Entité MA", niveau_id="Entity", parent=hors)
        cls.a = Organisation.objects.create(nom="Usine A", niveau_id="Site", parent=e1)
        cls.b = Organisation.objects.create(nom="Usine B", niveau_id="Site", parent=e1)
        cls.m = Organisation.objects.create(nom="Usine M", niveau_id="Site", parent=e2)
        cls.p = Periode.objects.create(type="annee", debut=datetime.date(2026, 1, 1), fin=datetime.date(2026, 12, 31),
                                       libelle="2026")
        cls.campagnes = {code: Campagne.objects.create(referentiel=Referentiel.objects.get(code=code), periode=cls.p,
                                                       exercice=2026, statut=Campagne.Statut.OUVERTE)
                         for code in ("ESRS_2", "ESRS_E1", "ESRS_E3", "ESRS_S1")}

        def saisir(code, org, v):
            Reponse.objects.create(periode=cls.p, kpi_id=code, organisation=org, statut=Reponse.Statut.VALIDE,
                                   **({"non_applicable": True} if v is NA else {"valeur": D(v)}))

        # S1-7 §24 : 600 salariés couverts sur 800 dans l'EEE, 200 salariés hors EEE (site M)
        saisir("SOC-EFFECTIF", cls.a, 500)
        saisir("SOC-SAL-CONVENTION", cls.a, 450)
        saisir("SOC-EFFECTIF", cls.b, 300)
        saisir("SOC-SAL-CONVENTION", cls.b, 150)
        saisir("SOC-EFFECTIF", cls.m, 200)
        # S1-13 §37(a) : 270 personnes couvertes sur 300 salariés, non-salariés non suivis (N/A, mesure transitoire)
        saisir("SOC-SST-COUVERTS", cls.b, 270)
        saisir("SOC-NON-SALARIES", cls.b, NA)
        # E3 : site en zone de stress hydrique ; prélèvement 1 000, rejets des procédés 200 et sanitaires 300
        saisir("EAU-PRELEVEMENT", cls.a, 1000)
        saisir("EAU-REJET", cls.a, 500)
        saisir("EAU-STRESS", cls.a, 800)  # consommation au sens de la VS (B6 §37 : rejets des procédés seulement)
        # E1-8 : scope 3, les quinze catégories pour l'entreprise ; quatre non significatives (N/A)
        for i, code in enumerate(("GES-S3-ACHATS", "GES-S3-IMMO", "GES-S3-ENERGIE", "GES-S3-FRET-AMONT", "GES-S3-DECHETS",
                                  "GES-S3-DEPLACEMENTS", "GES-S3-DOMICILE", "GES-S3-FRET-AVAL", "GES-S3-UTILISATION",
                                  "GES-S3-FIN-VIE"), start=1):
            saisir(code, cls.g, i)
        saisir("GES-S3-ACTIFS-AMONT", cls.g, 100)
        for code in ("GES-S3-TRANSFO", "GES-S3-ACTIFS-AVAL", "GES-S3-FRANCHISES", "GES-S3-INVEST"):
            saisir(code, cls.g, NA)
        # ESRS 2 GOV-1 §12(a) : 4 femmes et 6 hommes au conseil
        saisir("GOV-CA-FEMMES", cls.g, 4)
        saisir("GOV-CA-HOMMES", cls.g, 6)
        saisir("GOV-CA-AUTRES", cls.g, 0)  # dénominateur = tous les membres (membres d'un autre genre)
        for c in cls.campagnes.values():
            recalculer(c)

    def val(self, code, org, campagne="ESRS_S1"):
        return Calculateur(self.campagnes[campagne]).valeur(code, org.id)

    def test_part_couverte_par_la_sante_et_la_securite_sans_les_non_salaries(self):
        # avant : (salariés + non-salariés) au dénominateur, N/A rendait la part N/A
        self.assertEqual(self.val("SOC-PART-SST", self.b), D("0.9"))

    def test_part_couverte_par_une_convention_sur_l_eee(self):
        self.assertEqual(self.val("SOC-PART-CONVENTION", self.eee), D("0.75"))  # 600 / 800

    def test_pas_de_fausse_alerte_eau_en_stress_contre_consommation(self):
        self.assertEqual(self.val("EAU-CONSOMMATION", self.a, "ESRS_E3"), D(500))
        alertes = [d for d in CO.controles_regles(self.campagnes["ESRS_E3"]) if "EAU-STRESS" in d["regle"].gauche]
        self.assertEqual(alertes, [])

    def test_categorie_du_scope_3_non_significative_comptee_pour_zero(self):
        self.assertTrue(KPI.objects.get(code="GES-S3-TOTAL").na_compte_zero)
        self.assertEqual(self.val("GES-S3-TOTAL", self.g, "ESRS_E1"), D(55 + 100))

    def test_parts_des_femmes_et_des_hommes_au_conseil(self):
        self.assertEqual(self.val("GOV-CA-PART-FEMMES", self.g, "ESRS_2"), D("0.4"))
        self.assertEqual(self.val("GOV-CA-PART-HOMMES", self.g, "ESRS_2"), D("0.6"))
        self.assertAlmostEqual(float(self.val("GOV-CA-RATIO-FH", self.g, "ESRS_2")), 4 / 6)  # AR 6, inchangé

    def test_amendes_et_statut_du_plan_un_seul_kpi_pour_la_vs_et_les_esrs(self):
        def modeles(code):
            return set(ElementReferentiel.objects.filter(kpi_id=code).values_list("referentiel__code", flat=True))
        self.assertEqual(modeles("GOV-AMENDES"), {"VS_BASE", "ESRS_G1"})
        self.assertEqual(modeles("GES-PLAN-STATUT"), {"VS_COMPLET", "ESRS_E1"})
        self.assertEqual(modeles("GES-S1-REF"), {"VS_COMPLET", "ESRS_E1"})
        self.assertFalse(KPI.objects.filter(code__in=("GOV-AMENDES-ANTICORRUPTION", "CLI-PLAN-STATUT")).exists())
