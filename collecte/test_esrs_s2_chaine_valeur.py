"""Modèle « ESRS S2 – Travailleurs de la chaîne de valeur » (ESRS révisées, lot E) : contrôle et couverture de l'inventaire,
formats des KPI (oui / non, textes rédigés, tableaux des actions et des cibles), une réponse pour l'entreprise (niveau le plus
haut), bloc des exigences générales avec la prise en compte des parties prenantes (§42(d)) et sans indicateurs (pas de
GDR-M), contraction française (« aux travailleurs »), phrase d'entrée progressive, installation dans une base neuve sans
conflit."""
from django.test import SimpleTestCase, TestCase

from parametres.models import TypeReponse
from referentiel.bibliotheque import controle as C
from referentiel.bibliotheque import socles as S
from referentiel.bibliotheque.definitions import couverture, esrs_s2
from referentiel.models import KPI, ElementReferentiel, Referentiel

from . import paquets as P
from .aides_tests.paquets import vider

FICHIER = "esrs_s2.json"
OUI_NON = {"SOC-CHAINE-POLITIQUES", "SOC-CHAINE-ACTIONS", "SOC-CHAINE-CIBLES", "SOC-CHAINE-TRAITE", "SOC-CHAINE-TRAVAIL-FORCE",
           "SOC-CHAINE-TRAVAIL-ENFANTS", "SOC-CHAINE-CODE-FOURNIS", "SOC-CHAINE-PLAINTES"}
TABLEAUX = {"SOC-CHAINE-ACT-TAB": "ESRS-TAB-ACTIONS", "SOC-CHAINE-CIB-TAB": "ESRS-TAB-CIBLES"}


def installer(fichier=FICHIER):
    a = P.analyser(P.fourni(fichier).paquet, source=fichier, fourni=True)
    assert a.erreur == "" and a.compteurs["rejet"] == 0 and a.compteurs["conflit"] == 0, (a.erreur, a.compteurs)
    P.appliquer(None, a)


class ModeleChaineValeurTests(SimpleTestCase):
    def test_controle_et_couverture(self):
        socle = next(s for s in S.SOCLES if s["code"] == "ESRS_S2")
        r = C.controler(socle, couverture=couverture(esrs_s2), propres=set(esrs_s2.KPIS), regles_propres=set())
        self.assertEqual(r.erreurs, [])
        self.assertEqual((r.chiffres["couverture"]["total"], r.chiffres["couverture"]["taux"]), (16, 100))

    def test_vingt_sept_kpi_dont_aucun_repris(self):
        """Rien n'est repris de la norme VS (revue des doublons D20, D21) : tous les KPI sont nouveaux et tous placés."""
        placés = {c for c, *_ in C.elements(esrs_s2.SOCLE)}
        self.assertEqual(len(esrs_s2.KPIS), 30)  # + indicateurs propres facultatifs (ESRS 2 AR 42)
        self.assertEqual(placés, set(esrs_s2.KPIS))
        self.assertTrue(all(c.startswith("SOC-CHAINE-") for c in esrs_s2.KPIS))
        self.assertTrue({"SOC-INCIDENTS-CHAINE", "SOC-PLAINTES"}.isdisjoint(placés))

    def test_bloc_des_exigences_generales_sans_indicateurs(self):
        self.assertIn("SOC-CHAINE-POLIT-PARTIES", esrs_s2.KPIS)  # ESRS 2 §42(d), normes sociales
        # indicateurs propres à l'entreprise (ESRS 2 §48, AR 42) : tableau et GDR-M, facultatifs
        for code in ("SOC-CHAINE-INDICATEURS", "SOC-CHAINE-METHODES", "SOC-CHAINE-EVOLUTION"):
            self.assertIn(code, esrs_s2.KPIS)
            self.assertFalse(next(o for c, _, _, o in C.elements(esrs_s2.SOCLE) if c == code))

    def test_descriptions_citent_le_paragraphe_en_deux_langues(self):
        for code, d in esrs_s2.KPIS.items():
            fr, en = d["description"]
            with self.subTest(code=code):
                self.assertTrue(d["fr"] and d["en"] and fr and en)
                self.assertRegex(fr, r"ESRS (S2-\d|2 §|S2 AR)")
                self.assertRegex(en, r"ESRS (S2-\d|2 §|S2 AR)")
                self.assertIn("ESRS 1 §125(a)", fr)  # entrée progressive des normes S2 à S4
                self.assertIn("Phase-in", en)
                self.assertNotIn(" à les ", fr)  # « liés aux travailleurs », pas « liés à les travailleurs »
        self.assertIn("liés aux travailleurs", esrs_s2.KPIS["SOC-CHAINE-POLITIQUES"]["description"][0])


class InstallationChaineValeurTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        vider()
        installer()

    def test_referentiel_installe(self):
        r = Referentiel.objects.get(code="ESRS_S2")
        self.assertEqual(ElementReferentiel.objects.filter(referentiel=r).count(), 30)
        self.assertEqual(KPI.objects.filter(code__startswith="SOC-CHAINE-").count(), 30)

    def test_une_reponse_pour_l_entreprise(self):
        niveaux = set(KPI.objects.filter(code__startswith="SOC-CHAINE-").values_list("granularite_id", flat=True))
        self.assertEqual(niveaux, {"Group"})  # niveau le plus haut de l'arbre de départ

    def test_formats(self):
        for code in OUI_NON:
            with self.subTest(code=code):
                k = KPI.objects.get(code=code)
                self.assertEqual(TypeReponse.objects.get(code=k.type_reponse_id).format, TypeReponse.Format.OUI_NON)
        for code, type_ in TABLEAUX.items():
            with self.subTest(code=code):
                self.assertEqual(KPI.objects.get(code=code).type_reponse_id, type_)
                self.assertEqual(TypeReponse.objects.get(code=type_).format, TypeReponse.Format.TABLEAU)
        texte = TypeReponse.objects.get(code=KPI.objects.get(code="SOC-CHAINE-DIALOGUE").type_reponse_id)
        self.assertEqual(texte.format, TypeReponse.Format.TEXTE)

    def test_conditionnels_en_texte_avec_la_condition_dans_la_description(self):
        for code in ("SOC-CHAINE-VULNERABLES", "SOC-CHAINE-ACCORDS-CADRES", "SOC-CHAINE-ACTIONS-SUIVI"):
            with self.subTest(code=code):
                self.assertIn("N/A", esrs_s2.KPIS[code]["description"][0])
                self.assertIn("N/A", esrs_s2.KPIS[code]["description"][1])
