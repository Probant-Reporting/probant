"""Modèle « ESRS E3 – Eau » (ESRS révisées, premier modèle de la famille ESRS) et inventaire maître des ESRS
(``esrs_coverage.csv``) : installation dans une base neuve, niveaux choisis (politiques et cibles pour l'entreprise,
indicateurs au site), consommation calculée (prélèvement − rejet) et additionnée, KPI partagé avec la norme volontaire VS
sans conflit ni double saisie, colonne de zones de stress hydrique dans le tableau des actions, inventaire complet (une
ligne par point de la liste de l'EFRAG)."""
import datetime
from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from parametres import libelles as LB
from referentiel.bibliotheque import controle as C
from referentiel.bibliotheque import socles as S
from referentiel.bibliotheque.definitions import _esrs_communs as EC
from referentiel.bibliotheque.definitions import couverture, esrs_e3
from referentiel.models import KPI, ElementReferentiel, Organisation, Referentiel

from . import paquets as P
from .aides_tests.paquets import vider
from .calcul import Calculateur, recalculer
from .models import Campagne, Periode, Reponse

D = Decimal
FICHIER = "esrs_e3.json"
# Colonnes de l'inventaire publié : le règlement seulement (norme, exigence, paragraphe), nos KPI et le statut. La
# correspondance avec la liste des points de données de l'EFRAG reste dans l'atelier, avec son test.
COLONNES_PUBLIEES = ["reference", "requirement", "datapoint", "status", "kpi_codes", "note", "template", "standard", "dr",
                     "paragraph"]


def installer(fichier=FICHIER):
    a = P.analyser(P.fourni(fichier).paquet, source=fichier, fourni=True)
    assert a.erreur == "" and a.compteurs["rejet"] == 0 and a.compteurs["conflit"] == 0, (a.erreur, a.compteurs)
    P.appliquer(None, a)


class InventaireEsrsTests(SimpleTestCase):
    """L'inventaire maître publié : une ligne par exigence du règlement, des références uniques, un modèle prévu pour chaque
    ligne, rien de la liste de l'EFRAG (identifiants, types, conditions, entrées progressives)."""

    def setUp(self):
        self.colonnes, self.lignes, self.numeros = C.lire_couverture(couverture(esrs_e3))

    def test_colonnes_du_reglement_seulement(self):
        self.assertEqual(list(self.colonnes), COLONNES_PUBLIEES)
        with open(couverture(esrs_e3), encoding="utf-8") as f:
            self.assertNotIn("ESRS26" + "_", f.read())  # identifiant de la liste de l'EFRAG
        self.assertEqual(len(self.lignes), 375)  # 359 points de la liste + 16 exigences du règlement absentes de la liste

    def test_references_uniques_et_modeles_prevus(self):
        refs = [ligne["reference"] for ligne in self.lignes]
        self.assertEqual(len(refs), len(set(refs)))
        self.assertEqual({ligne["template"] for ligne in self.lignes}, set(EC.MODELES))
        # la référence se lit dans le règlement : norme, exigence de publication, paragraphe
        for ligne in self.lignes:
            self.assertIn(f"§{ligne['paragraph']}", ligne["reference"], ligne["reference"])

    def test_noms_des_onze_modeles_dans_les_sept_langues(self):
        for code, m in EC.MODELES.items():
            for lg in ("fr", "en", "es", "de", "it", "nl", "pt"):
                table = LB.table(lg)
                for champ in ("nom", "description", "thematique"):
                    cle = f"referentiels.socle.{code.lower()}.{champ}"
                    with self.subTest(cle=cle, lg=lg):
                        self.assertTrue(table.get(cle))
                        if lg in ("fr", "en"):
                            attendu = (m["nom"], m["description"], EC.THEMATIQUE)[("nom", "description", "thematique").index(champ)]
                            self.assertEqual(table[cle], attendu[0 if lg == "fr" else 1])


class ModeleEauTests(SimpleTestCase):
    def test_controle_et_couverture(self):
        socle = next(s for s in S.SOCLES if s["code"] == "ESRS_E3")
        r = C.controler(socle, couverture=couverture(esrs_e3), propres=set(esrs_e3.KPIS), regles_propres=set(esrs_e3.REGLES))
        self.assertEqual(r.erreurs, [])
        self.assertEqual((r.chiffres["couverture"]["total"], r.chiffres["couverture"]["taux"]), (12, 100))

    def test_kpi_repris_de_la_norme_vs_non_redefinis(self):
        self.assertFalse({"EAU-PRELEVEMENT", "EAU-STRESS"} & set(esrs_e3.KPIS))
        codes = {c for c, *_ in C.elements(esrs_e3.SOCLE)}
        self.assertTrue({"EAU-PRELEVEMENT", "EAU-CONSO-STRESS"} <= codes)
        self.assertNotIn("EAU-STRESS", codes)  # un KPI par méthode (VS B6 §37, ESRS E3 AR 4)
        self.assertNotIn("EAU-CONSO", codes)  # autre définition (le prélèvement à défaut de consommation)
        self.assertNotIn("EAU-REJET-PROCESS", codes)  # rejet des seuls procédés


class InstallationEauTests(TestCase):
    """Base neuve : niveaux Groupe › Pays › Entité › Site ; la VS de base installée d'abord, puis ESRS E3."""

    @classmethod
    def setUpTestData(cls):
        vider()
        installer("vs_base.json")
        installer()
        cls.g = Organisation.objects.create(nom="Groupe", niveau_id="Group")
        fr = Organisation.objects.create(nom="France", niveau_id="Country", parent=cls.g)
        e = Organisation.objects.create(nom="Entité", niveau_id="Entity", parent=fr)
        cls.a = Organisation.objects.create(nom="Usine A", niveau_id="Site", parent=e)
        cls.b = Organisation.objects.create(nom="Usine B", niveau_id="Site", parent=e)
        p = Periode.objects.create(type="annee", debut=datetime.date(2026, 1, 1), fin=datetime.date(2026, 12, 31), libelle="2026")
        cls.c = Campagne.objects.create(referentiel=Referentiel.objects.get(code="ESRS_E3"), periode=p, exercice=2026,
                                        statut=Campagne.Statut.OUVERTE)
        for org, prel, rej, stress in ((cls.a, 1000, 600, 400), (cls.b, 500, 450, 0)):
            for code, v in (("EAU-PRELEVEMENT", prel), ("EAU-REJET", rej), ("EAU-CONSO-STRESS", stress)):
                Reponse.objects.create(periode=p, kpi_id=code, organisation=org, valeur=D(v), statut=Reponse.Statut.VALIDE)
        recalculer(cls.c)

    def val(self, code, org):
        return Calculateur(self.c).valeur(code, org.id)

    def test_un_seul_kpi_partage_avec_la_vs(self):
        prel = KPI.objects.get(code="EAU-PRELEVEMENT")
        self.assertEqual(set(ElementReferentiel.objects.filter(kpi=prel).values_list("referentiel__code", flat=True)),
                         {"VS_BASE", "ESRS_E3"})

    def test_niveaux_choisis_par_l_outil(self):
        self.assertEqual(KPI.objects.get(code="EAU-POLIT-CONTENU").granularite_id, "Group")  # une réponse pour l'entreprise
        self.assertEqual(KPI.objects.get(code="EAU-ACT-TAB").granularite_id, "Group")
        self.assertEqual(KPI.objects.get(code="EAU-REJET").granularite_id, "Site")  # mesuré au site
        self.assertEqual(KPI.objects.get(code="EAU-CONSOMMATION").granularite_id, "Site")  # niveau de ses sources

    def test_consommation_calculee_et_additionnee(self):
        self.assertEqual(self.val("EAU-CONSOMMATION", self.a), D(400))
        self.assertEqual(self.val("EAU-CONSOMMATION", self.b), D(50))
        self.assertEqual(self.val("EAU-CONSOMMATION", self.g), D(450))
        self.assertEqual(self.val("EAU-CONSO-STRESS", self.g), D(400))

    def test_colonne_des_zones_de_stress_hydrique(self):
        from parametres.models import TypeReponse

        kpi = KPI.objects.get(code="EAU-ACT-TAB")
        t = TypeReponse.objects.get(code=kpi.type_reponse_id)
        self.assertEqual(t.format, TypeReponse.Format.TABLEAU)
        self.assertIn("stress", [c["code"] for c in t.colonnes])
        self.assertEqual(KPI.objects.get(code="EAU-CIB-TAB").type_reponse_id, "ESRS-TAB-CIBLES")
