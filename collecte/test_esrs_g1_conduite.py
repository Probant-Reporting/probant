"""Modèle « ESRS G1 – Conduite des affaires » (ESRS révisées, lot E) : contrôle et couverture de l'inventaire, condamnations
pour corruption reprises de la norme VS (un seul KPI) avec sanctions administratives et total calculés, amendes distinctes de
celles de la VS, part des paiements conformes calculée sur les factures (exacte au niveau du groupe, pas une moyenne de
parts), règle de cohérence, niveaux (entreprise, entité), installation avec la VS sans double saisie."""
import datetime
from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from parametres.models import TypeReponse
from referentiel.bibliotheque import controle as C
from referentiel.bibliotheque import socles as S
from referentiel.bibliotheque.definitions import couverture, esrs_g1
from referentiel.models import KPI, ElementReferentiel, Organisation, Referentiel

from . import paquets as P
from .aides_tests.paquets import vider
from .calcul import Calculateur, recalculer
from .models import Campagne, Periode, Reponse

D = Decimal


def installer(fichier):
    a = P.analyser(P.fourni(fichier).paquet, source=fichier, fourni=True)
    assert a.erreur == "" and a.compteurs["rejet"] == 0 and a.compteurs["conflit"] == 0, (a.erreur, a.compteurs)
    P.appliquer(None, a)


class ModeleConduiteTests(SimpleTestCase):
    def test_controle_et_couverture(self):
        socle = next(s for s in S.SOCLES if s["code"] == "ESRS_G1")
        r = C.controler(socle, couverture=couverture(esrs_g1), propres=set(esrs_g1.KPIS), regles_propres=set(esrs_g1.REGLES))
        self.assertEqual(r.erreurs, [])
        self.assertEqual((r.chiffres["couverture"]["total"], r.chiffres["couverture"]["taux"]), (24, 100))

    def test_trente_neuf_kpi_dont_deux_repris_de_la_vs(self):
        placés = {c for c, *_ in C.elements(esrs_g1.SOCLE)}
        self.assertEqual(len(placés), 42)  # + paiements en valeur (deux montants et leur part)
        # condamnations et amendes : KPI de la VS (B11), même définition que la G1 (AR 5, AR 6 = guide VS §140-141)
        self.assertEqual(placés - set(esrs_g1.KPIS), {"GOV-CORRUPTION", "GOV-AMENDES"})
        self.assertNotIn("GOV-AMENDES-ANTICORRUPTION", placés)  # doublon fusionné dans GOV-AMENDES
        self.assertNotIn("GOV-DELAI-PAIEMENT", placés)  # délai réel moyen, pas les conditions standard (D23)

    def test_bloc_avec_indicateurs_sans_parties_prenantes(self):
        self.assertIn("GOV-CONDUITE-METHODES", esrs_g1.KPIS)  # GDR-M : G1-4 à G1-6 sont des indicateurs
        self.assertIn("GOV-CONDUITE-EVOLUTION", esrs_g1.KPIS)
        self.assertNotIn("GOV-CONDUITE-POLIT-PARTIES", esrs_g1.KPIS)  # §42(d) : normes sociales seulement

    def test_descriptions_en_deux_langues_et_entree_progressive(self):
        for code, d in esrs_g1.KPIS.items():
            with self.subTest(code=code):
                self.assertTrue(d["fr"] and d["en"] and all(d["description"]))
                self.assertIn("ESRS 1 §126(a)", d["description"][0])
                self.assertIn("ESRS 1 §126(a)", d["description"][1])
                self.assertRegex(d["description"][0], r"ESRS (G1-\d|2 §|1 §11)")
        amendes = S.KPIS["GOV-AMENDES"]["description"]  # définition commune aux deux normes, qui cite les deux
        self.assertIn("comptabilisées dans les états financiers", amendes[0])
        self.assertTrue("G1 AR 6" in amendes[0] and "§141" in amendes[0] and "G1 AR 6" in amendes[1])

    def test_unites_du_socle_commun(self):
        self.assertEqual(esrs_g1.KPIS["GOV-FACTURES"]["unite"], "factures")
        self.assertIn("factures", {u[0] for u in esrs_g1.UNITES})


class InstallationConduiteTests(TestCase):
    """Base neuve : Groupe › Pays › Entité › Site ; la VS de base installée d'abord, puis ESRS G1."""

    @classmethod
    def setUpTestData(cls):
        vider()
        installer("vs_base.json")
        installer("esrs_g1.json")
        cls.g = Organisation.objects.create(nom="Groupe", niveau_id="Group")
        fr = Organisation.objects.create(nom="France", niveau_id="Country", parent=cls.g)
        cls.e1 = Organisation.objects.create(nom="Entité 1", niveau_id="Entity", parent=fr)
        cls.e2 = Organisation.objects.create(nom="Entité 2", niveau_id="Entity", parent=fr)
        cls.a = Organisation.objects.create(nom="Usine A", niveau_id="Site", parent=cls.e1)
        cls.b = Organisation.objects.create(nom="Usine B", niveau_id="Site", parent=cls.e2)
        p = Periode.objects.create(type="annee", debut=datetime.date(2026, 1, 1), fin=datetime.date(2026, 12, 31), libelle="2026")
        cls.c = Campagne.objects.create(referentiel=Referentiel.objects.get(code="ESRS_G1"), periode=p, exercice=2026,
                                        statut=Campagne.Statut.OUVERTE)
        valeurs = (
            ("GOV-CORRUPTION", cls.a, 1), ("GOV-CORRUPTION", cls.b, 2),  # condamnations : saisies au site (KPI de la VS)
            ("GOV-SANCTIONS-CORRUP", cls.e1, 1), ("GOV-SANCTIONS-CORRUP", cls.e2, 0),  # sanctions : saisies à l'entité
            ("GOV-FACTURES", cls.e1, 100), ("GOV-FACTURES-A-TEMPS", cls.e1, 90),
            ("GOV-FACTURES", cls.e2, 300), ("GOV-FACTURES-A-TEMPS", cls.e2, 150),
            ("GOV-CONTRIBUTIONS-POLIT", cls.e1, 1500), ("GOV-CONTRIBUTIONS-POLIT", cls.e2, 500),
        )
        for code, org, v in valeurs:
            Reponse.objects.create(periode=p, kpi_id=code, organisation=org, valeur=D(v), statut=Reponse.Statut.VALIDE)
        recalculer(cls.c)

    def val(self, code, org):
        return Calculateur(self.c).valeur(code, org.id)

    def test_un_seul_kpi_de_condamnations_partage_avec_la_vs(self):
        k = KPI.objects.get(code="GOV-CORRUPTION")
        self.assertEqual(set(ElementReferentiel.objects.filter(kpi=k).values_list("referentiel__code", flat=True)),
                         {"VS_BASE", "ESRS_G1"})
        self.assertEqual(KPI.objects.filter(code="GOV-CORRUPTION").count(), 1)
        # les amendes : un seul KPI, celui de la VS, placé dans les deux modèles (une seule saisie)
        self.assertEqual(set(ElementReferentiel.objects.filter(kpi__code="GOV-AMENDES").values_list("referentiel__code", flat=True)),
                         {"VS_BASE", "ESRS_G1"})
        self.assertFalse(KPI.objects.filter(code="GOV-AMENDES-ANTICORRUPTION").exists())

    def test_niveaux_choisis_par_l_outil(self):
        self.assertEqual(KPI.objects.get(code="GOV-POLIT-ANTICORRUPTION").granularite_id, "Group")  # une réponse pour l'entreprise
        self.assertEqual(KPI.objects.get(code="GOV-PAIEMENT-JOURS").granularite_id, "Group")
        for code in ("GOV-FACTURES", "GOV-CONTRIBUTIONS-POLIT", "GOV-SANCTIONS-CORRUP",
                     "GOV-PAIEMENT-CONTENTIEUX"):
            with self.subTest(code=code):
                self.assertEqual(KPI.objects.get(code=code).granularite_id, "Entity")  # une déclaration par entité juridique
        self.assertEqual(KPI.objects.get(code="GOV-PAIEMENT-PART-CONFORME").granularite_id, "Entity")  # niveau de ses sources

    def test_condamnations_et_sanctions_calculees(self):
        self.assertEqual(self.val("GOV-CONDAMN-SANCTIONS", self.e1), D(2))  # 1 condamnation du site + 1 sanction de l'entité
        self.assertEqual(self.val("GOV-CONDAMN-SANCTIONS", self.e2), D(2))
        self.assertEqual(self.val("GOV-CONDAMN-SANCTIONS", self.g), D(4))
        self.assertEqual(self.val("GOV-CORRUPTION", self.g), D(3))  # la valeur de la VS remonte comme avant

    def test_part_des_paiements_conformes_exacte_au_groupe(self):
        self.assertEqual(self.val("GOV-PAIEMENT-PART-CONFORME", self.e1), D("0.9"))
        self.assertEqual(self.val("GOV-PAIEMENT-PART-CONFORME", self.e2), D("0.5"))
        # 240 factures sur 400 : 60 %, et non la moyenne des deux parts (70 %)
        self.assertEqual(self.val("GOV-PAIEMENT-PART-CONFORME", self.g), D("0.6"))

    def test_montants_additionnes(self):
        self.assertEqual(self.val("GOV-CONTRIBUTIONS-POLIT", self.g), D(2000))

    def test_regle_factures_a_temps(self):
        from .models import RegleCoherence

        r = RegleCoherence.objects.get(nom__startswith="Factures payées dans les délais")
        self.assertEqual(r.operateur, "<=")

    def test_types_et_formats(self):
        for code in ("GOV-POLIT-ANTICORRUPTION", "GOV-POLIT-LANCEURS", "GOV-ACHATS-FORMATION", "GOV-CONDUITE-POLITIQUES"):
            with self.subTest(code=code):
                k = KPI.objects.get(code=code)
                self.assertEqual(TypeReponse.objects.get(code=k.type_reponse_id).format, TypeReponse.Format.OUI_NON)
        self.assertEqual(TypeReponse.objects.get(code=KPI.objects.get(code="GOV-PAIEMENT-PART-CONFORME").type_reponse_id).format,
                         TypeReponse.Format.POURCENTAGE)


class LotEInstalleEnsembleTests(TestCase):
    """Les quatre modèles du lot E, avec la VS et l'eau : aucun conflit, aucun KPI en double, rien de la VS ne change."""

    @staticmethod
    def empreinte():
        return {k.code: (k.libelle, k.unite_id, k.granularite_id, k.methode_agregation, k.agregation_temps, k.formule,
                         k.type_reponse_id, k.type_saisie_id, k.confidentialite)
                for k in KPI.objects.all()}

    def test_installation_ensemble(self):
        vider()
        for fichier in ("vs_base.json", "vs_complet.json"):
            installer(fichier)
        avant = self.empreinte()
        elements_vs = {r.code: r.elements.count() for r in Referentiel.objects.filter(code__in=("VS_BASE", "VS_COMPLET"))}
        for fichier in ("esrs_e3.json", "esrs_s2.json", "esrs_s3.json", "esrs_s4.json", "esrs_g1.json"):
            installer(fichier)
        apres = self.empreinte()
        # aucune valeur, aucune définition de la VS ne change ; les KPI ajoutés sont ceux des cinq modèles
        self.assertEqual({c: v for c, v in apres.items() if c in avant}, avant)
        self.assertEqual({r.code: r.elements.count() for r in Referentiel.objects.filter(code__in=elements_vs)}, elements_vs)
        # chaque KPI du lot E est dans son seul modèle, hors GOV-CORRUPTION et GOV-AMENDES (VS B11 et G1-4)
        for code in ("ESRS_S2", "ESRS_S3", "ESRS_S4", "ESRS_G1"):
            for k in KPI.objects.filter(elements__referentiel__code=code):
                modeles = set(k.elements.values_list("referentiel__code", flat=True))
                with self.subTest(code=k.code):
                    self.assertTrue(modeles == {code} or (k.code in ("GOV-CORRUPTION", "GOV-AMENDES") and code in modeles
                                                          and "VS_BASE" in modeles))
