"""Modèle « ESRS E1 – Changement climatique » (ESRS révisées, lot B) : contrôle et couverture de l'inventaire, KPI repris de
la norme volontaire VS sans redéfinition, installation après la VS sans conflit ni double saisie, niveaux choisis par
l'outil, et calculs chiffrés à la main : répartition de l'énergie (fossile + nucléaire + renouvelable = total ; les cinq
sources fossiles = énergie fossile), scope 1 brut, part du SEQE-UE recalculée à chaque niveau, répartition groupe
consolidé / hors groupe, total du scope 3, règles de cohérence."""
import datetime
from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from referentiel.bibliotheque import controle as C
from referentiel.bibliotheque import socles as S
from referentiel.bibliotheque.definitions import couverture, esrs_e1
from referentiel.models import KPI, ElementReferentiel, Organisation, Referentiel

from . import paquets as P
from .aides_tests.paquets import vider
from .calcul import Calculateur, recalculer
from .coherence import controles_regles
from .models import Campagne, Periode, Reponse

D = Decimal
FICHIER = "esrs_e1.json"


def installer(fichier=FICHIER):
    a = P.analyser(P.fourni(fichier).paquet, source=fichier, fourni=True)
    assert a.erreur == "" and a.compteurs["rejet"] == 0 and a.compteurs["conflit"] == 0, (a.erreur, a.compteurs)
    P.appliquer(None, a)


class ModeleClimatTests(SimpleTestCase):
    def test_controle_et_couverture(self):
        socle = next(s for s in S.SOCLES if s["code"] == "ESRS_E1")
        r = C.controler(socle, couverture=couverture(esrs_e1), propres=set(esrs_e1.KPIS), regles_propres=set(esrs_e1.REGLES))
        self.assertEqual(r.erreurs, [])
        # 87 points de la liste de l'EFRAG + GDR-M et §30(b), §30(c), AR 24(g) du règlement
        self.assertEqual((r.chiffres["couverture"]["total"], r.chiffres["couverture"]["taux"]), (90, 100))
        self.assertEqual(S.CONFLITS, [])

    def test_inventaire_du_lot(self):
        _, lignes, _ = C.lire_couverture(couverture(esrs_e1), "ESRS_E1")
        self.assertEqual(len(lignes), 90)  # 87 points de la liste de l'EFRAG + trois exigences du règlement hors liste
        refs = {ligne["reference"] for ligne in lignes}
        self.assertTrue({"E1 · E1-8 §30(b)", "E1 · E1-8 §30(c)", "E1 · E1-8 §AR 24(g)"} <= refs, refs)
        self.assertEqual({ligne["status"] for ligne in lignes}, {"covered"})

    def test_kpi_repris_de_la_vs_non_redefinis(self):
        """La chaîne énergie et GES de la VS (et du catalogue commun) est placée telle quelle, jamais redéfinie."""
        # 46 + le statut du plan de transition (VS C3, fusionné) + les huit KPI des cibles absolues des scopes 1 et 2 (VS C3)
        self.assertEqual(len(esrs_e1.REPRIS), 55)
        self.assertFalse(set(esrs_e1.REPRIS) & set(esrs_e1.KPIS))
        codes = {c for c, *_ in C.elements(esrs_e1.SOCLE)}
        self.assertTrue(set(esrs_e1.REPRIS) <= codes)
        self.assertEqual(len(codes), 152)
        # refusés (définition différente, revue des doublons) : ni placés ni redéfinis
        self.assertNotIn("CLI-PLAN-STATUT", codes)  # doublon de GES-PLAN-STATUT (VS C3 §55, E1-1 §13) : fusionné
        for code in ("GES-S3", "GES-S3-AUTRES", "GES-TOTAL", "GES-INTENSITE", "NRJ-ELEC-REN", "GES-PLAN-DESC",
                     "CLI-EXPOSITION", "CLI-HORIZONS"):
            self.assertNotIn(code, codes)

    def test_parts_fossiles_calculees_par_difference(self):
        """Une seule saisie des mêmes combustibles : « autres sources fossiles » et énergie achetée fossile sont calculées."""
        self.assertEqual(esrs_e1.KPIS["NRJ-FOSSILE-AUTRES"]["formule"], "[NRJ-COMB-AUTRES] - [NRJ-CHARBON] - [NRJ-PETROLE-AUTRES]")
        self.assertEqual(esrs_e1.KPIS["NRJ-ACHAT-FOSSILE"]["type"], "Calculé")
        self.assertEqual(esrs_e1.KPIS["GES-PART-SEQE"]["agregation"], "Formule")  # ratio recalculé à chaque niveau

    def test_francais_du_bloc_commun(self):
        textes = " ".join(str(d["fr"]) + str(d["description"]) for c, d in esrs_e1.KPIS.items() if c.startswith("CLI-"))
        self.assertNotIn("à le changement", textes)
        self.assertIn("liés au changement climatique", textes)


class InstallationClimatTests(TestCase):
    """Base neuve : niveaux Groupe › Pays › Entité › Site ; la VS (base et complète) installée d'abord, puis ESRS E1.
    Deux usines ; toutes les valeurs ci-dessous et les résultats attendus sont calculés à la main dans les tests."""

    @classmethod
    def setUpTestData(cls):
        vider()
        installer("vs_base.json")
        installer("vs_complet.json")
        installer()
        cls.g = Organisation.objects.create(nom="Groupe", niveau_id="Group")
        cls.fr = Organisation.objects.create(nom="France", niveau_id="Country", parent=cls.g)
        e = Organisation.objects.create(nom="Entité", niveau_id="Entity", parent=cls.fr)
        cls.a = Organisation.objects.create(nom="Usine A", niveau_id="Site", parent=e)
        cls.b = Organisation.objects.create(nom="Usine B", niveau_id="Site", parent=e)
        cls.p = Periode.objects.create(type="annee", debut=datetime.date(2026, 1, 1), fin=datetime.date(2026, 12, 31),
                                       libelle="2026")
        cls.c = Campagne.objects.create(referentiel=Referentiel.objects.get(code="ESRS_E1"), periode=cls.p, exercice=2026,
                                        statut=Campagne.Statut.OUVERTE)
        groupe = {"CONV-GAZ-PCI": "0.9", "CONV-FIOUL": 10, "CONV-GAZOLE": 10, "CONV-ESSENCE": 9, "FE-GAZ": "0.2",
                  "FE-FIOUL": 3, "FE-GAZOLE": 3, "FE-ESSENCE": "2.5", "FE-CHALEUR": "0.1", "FE-FROID": 0,
                  # saisis pour l'entreprise : scope 2 (marché) de la VS, parts hors du groupe consolidé, scope 3 (VS)
                  "GES-S2-MB": 6, "GES-S1-HORS-GROUPE": "4.25", "GES-S2-LB-HORS-GROUPE": "0.5", "GES-S2-MB-HORS-GROUPE": 1,
                  "GES-S3-ACTIFS-AMONT": 0, "GES-S3-TRANSFO": 0, "GES-S3-ACTIFS-AVAL": 0, "GES-S3-FRANCHISES": 0,
                  "GES-S3-INVEST": 10, "GES-S3-CLOUD": 8,
                  # les dix autres catégories aussi pour l'entreprise (mêmes totaux que les deux usines)
                  "GES-S3-ACHATS": 150, "GES-S3-DEPLACEMENTS": 10,
                  **{c: 0 for c in ("GES-S3-IMMO", "GES-S3-ENERGIE", "GES-S3-FRET-AMONT", "GES-S3-DECHETS", "GES-S3-DOMICILE",
                                    "GES-S3-FRET-AVAL", "GES-S3-UTILISATION", "GES-S3-FIN-VIE")}}
        sites = {  # code : (usine A, usine B)
            "NRJ-ELEC": (100000, 50000), "NRJ-CHALEUR": (20000, 0), "NRJ-FROID": (0, 10000), "NRJ-ELEC-AUTO": (10000, 0),
            "NRJ-GAZ": (50000, 0), "NRJ-FIOUL": (1000, 0), "GES-GAZOLE": (2000, 1000), "GES-ESSENCE": (500, 0),
            "NRJ-COMB-AUTRES": (30, 0), "NRJ-COMB-REN": (40, 0), "NRJ-ACHAT-NUCLEAIRE": (50, 20),
            "NRJ-ACHAT-RENOUV": (30, 10), "NRJ-CHARBON": (10, 0), "NRJ-PETROLE-AUTRES": (15, 0), "NRJ-PROD-REN": (12, 0),
            "NRJ-PROD-NON-REN": (0, 0), "GES-FUGITIVES": (5, 1), "GES-S1-AUTRES": (20, 0), "GES-S1-SEQE": (30, 0),
            "GES-BIOGENIQUE": (14, 0)}

        def saisir(code, org, v):
            Reponse.objects.create(periode=cls.p, kpi_id=code, organisation=org, valeur=D(str(v)), statut=Reponse.Statut.VALIDE)
        for code, v in groupe.items():
            saisir(code, cls.g, v)
        saisir("FE-ELEC", cls.fr, "0.05")  # facteur du réseau : niveau Pays
        for code, (va, vb) in sites.items():
            saisir(code, cls.a, va)
            saisir(code, cls.b, vb)
        recalculer(cls.c)

    def val(self, code, org):
        return Calculateur(self.c).valeur(code, org.id)

    def test_un_seul_kpi_partage_avec_la_vs(self):
        for code, attendus in (("NRJ-ELEC", {"VS_BASE", "ESRS_E1"}), ("GES-S2-MB", {"VS_BASE", "ESRS_E1"}),
                               ("GES-PLAN-ANNEE", {"VS_COMPLET", "ESRS_E1"})):
            self.assertEqual(set(ElementReferentiel.objects.filter(kpi_id=code).values_list("referentiel__code", flat=True)),
                             attendus)
        # facultatif dans la VS, obligatoire dans l'ESRS E1 : chaque référentiel garde le sien
        self.assertFalse(ElementReferentiel.objects.get(kpi_id="GES-S2-MB", referentiel__code="VS_BASE").obligatoire)
        self.assertTrue(ElementReferentiel.objects.get(kpi_id="GES-S2-MB", referentiel__code="ESRS_E1").obligatoire)

    def test_niveaux_choisis_par_l_outil(self):
        niveaux = dict(KPI.objects.values_list("code", "granularite_id"))
        for code, attendu in (("CLI-PLAN-TRANSITION", "Group"), ("CLI-CIBLES-GES-TAB", "Group"), ("CLI-CAPEX-CHARBON", "Entity"),
                              ("NRJ-ACHAT-NUCLEAIRE", "Site"), ("NRJ-FOSSILE", "Site"), ("NRJ-ACHAT-FOSSILE", "Site"),
                              ("GES-S1-SEQE", "Site"), ("GES-PART-SEQE", "Site"), ("GES-S1-HORS-GROUPE", "Group"),
                              ("GES-S1-GROUPE", "Group"), ("GES-S2-MB-GROUPE", "Group"),
                              ("GES-S3-TOTAL", "Group"), ("GES-S3-ACHATS", "Group")):  # les quinze catégories pour l'entreprise
            self.assertEqual(niveaux[code], attendu, code)

    def test_energie_repartie_et_totaux(self):
        # usine A : combustibles fossiles (50 000 × 0,9 + 1 000 × 10 + 2 000 × 10 + 500 × 9) / 1 000 + 30 = 109,5 MWh ;
        # énergie achetée (100 000 + 20 000 + 0) / 1 000 = 120 MWh, dont nucléaire 50 et renouvelable 30, donc fossile 40
        attendus = {
            "NRJ-COMBUSTIBLES": (D("109.5"), D(10), D("119.5")),
            "NRJ-ACHAT-FOSSILE": (D(40), D(30), D(70)),
            "NRJ-FOSSILE": (D("149.5"), D(40), D("189.5")),
            "NRJ-RENOUVELABLE": (D(80), D(10), D(90)),  # 40 + 10 000 / 1 000 + 30 ; 0 + 0 + 10
            "NRJ-TOTAL-MWH": (D("279.5"), D(70), D("349.5")),
            "NRJ-GAZ-MWH": (D(45), D(0), D(45)),
            "NRJ-PETROLE": (D("49.5"), D(10), D("59.5")),  # (10 000 + 20 000 + 4 500) / 1 000 + 15 ; 10 000 / 1 000
            "NRJ-FOSSILE-AUTRES": (D(5), D(0), D(5)),  # 30 − 10 − 15
        }
        for code, valeurs in attendus.items():
            for org, v in zip((self.a, self.b, self.g), valeurs):
                self.assertEqual(self.val(code, org), v, (code, org.nom))
        for org in (self.a, self.b, self.g):
            fossile, nucleaire, renouv = (self.val(c, org) for c in ("NRJ-FOSSILE", "NRJ-ACHAT-NUCLEAIRE", "NRJ-RENOUVELABLE"))
            self.assertEqual(fossile + nucleaire + renouv, self.val("NRJ-TOTAL-MWH", org))  # ESRS E1 §26
            sources = ("NRJ-CHARBON", "NRJ-PETROLE", "NRJ-GAZ-MWH", "NRJ-FOSSILE-AUTRES", "NRJ-ACHAT-FOSSILE")
            self.assertEqual(sum(self.val(c, org) for c in sources), fossile)  # ESRS E1 §27

    def test_scopes_1_et_2_et_part_du_seqe(self):
        # usine A : combustion fixe (50 000 × 0,2 + 1 000 × 3) / 1 000 = 13 ; mobile (2 000 × 3 + 500 × 2,5) / 1 000 = 7,25 ;
        # GES-S1 = 13 + 7,25 + 5 = 25,25 ; brut = 25,25 + 20 = 45,25 ; usine B : 1 000 × 3 / 1 000 + 1 = 4
        self.assertEqual([self.val("GES-S1-BRUT", o) for o in (self.a, self.b, self.g)], [D("45.25"), D(4), D("49.25")])
        # scope 2 (localisation) : (100 000 × 0,05 + 20 000 × 0,1) / 1 000 = 7 ; 50 000 × 0,05 / 1 000 = 2,5
        self.assertEqual([self.val("GES-S2-LB", o) for o in (self.a, self.b, self.g)], [D(7), D("2.5"), D("9.5")])
        # part du SEQE-UE : recalculée à chaque niveau (30 / 49,25), pas la somme ni la moyenne des parts des sites
        self.assertAlmostEqual(self.val("GES-PART-SEQE", self.a), D(30) / D("45.25"), places=8)
        self.assertEqual(self.val("GES-PART-SEQE", self.b), D(0))
        self.assertAlmostEqual(self.val("GES-PART-SEQE", self.g), D(30) / D("49.25"), places=8)
        # groupe consolidé = total − part hors du groupe (saisie pour l'entreprise)
        self.assertEqual(self.val("GES-S1-GROUPE", self.g), D(45))
        self.assertEqual(self.val("GES-S2-LB-GROUPE", self.g), D(9))
        self.assertEqual(self.val("GES-S2-MB-GROUPE", self.g), D(5))
        self.assertEqual(self.val("GES-BIOGENIQUE", self.g), D(14))  # à part du scope 1

    def test_total_du_scope_3(self):
        # catégorie 1 : 100 + 50 ; catégorie 6 : 5 + 5 ; catégorie 15 (VS, entreprise) : 10 ; le reste 0
        self.assertEqual(self.val("GES-S3-TOTAL", self.g), D(170))
        self.assertEqual(self.val("GES-S3-ACHATS", self.g), D(150))  # dont informatique en nuage : 8, hors du total

    def test_regles_de_coherence(self):
        noms = set(esrs_e1.REGLES)
        self.assertEqual([d for d in controles_regles(self.c) if d["regle"].nom in noms], [])  # jeu cohérent
        # usine B : nucléaire 20 + renouvelable 45 > énergie achetée 60 MWh (la part fossile calculée serait négative)
        Reponse.objects.filter(periode=self.p, kpi_id="NRJ-ACHAT-RENOUV", organisation=self.b).update(valeur=D(45))
        recalculer(self.c)
        self.assertEqual(self.val("NRJ-ACHAT-FOSSILE", self.b), D(-5))
        alertes = [(d["regle"].nom, d["org"].nom) for d in controles_regles(self.c) if d["regle"].nom in noms]
        self.assertEqual(alertes, [("Énergie achetée nucléaire et renouvelable ≤ énergie achetée", "Usine B")])
