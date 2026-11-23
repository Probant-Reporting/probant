"""Arbitrages du propriétaire du produit sur les modèles de la bibliothèque (revue des doublons de l'atelier,
section 9.3) : textes, entrée progressive, calculs refaits à la main."""
import datetime
from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from referentiel.bibliotheque import controle as C
from referentiel.bibliotheque import socles as S
from referentiel.bibliotheque.definitions import _esrs_lot_e as L
from referentiel.bibliotheque.definitions import esrs_e1, esrs_e2, esrs_e3, esrs_e5, esrs_s1
from referentiel.formule import NA
from referentiel.models import Organisation, Referentiel

from . import paquets as P
from .aides_tests.paquets import vider
from .calcul import Calculateur, recalculer
from .models import Campagne, Periode, Reponse

D = Decimal

ESRS = [s for s in S.SOCLES if s["code"].startswith("ESRS_")]


def installer(*fichiers):
    for fichier in fichiers:
        a = P.analyser(P.fourni(fichier).paquet, source=fichier, fourni=True)
        assert a.erreur == "" and a.compteurs["rejet"] == 0 and a.compteurs["conflit"] == 0, (fichier, a.erreur, a.compteurs)
        P.appliquer(None, a)


class AvecCampagne(TestCase):
    """Base neuve : Groupe › Pays › Entité › deux sites ; une campagne 2026 ouverte du modèle ``REFERENTIEL``."""
    FICHIERS, REFERENTIEL = (), ""

    @classmethod
    def setUpTestData(cls):
        vider()
        installer(*cls.FICHIERS)
        cls.g = Organisation.objects.create(nom="Groupe", niveau_id="Group")
        fr = Organisation.objects.create(nom="France", niveau_id="Country", parent=cls.g)
        cls.e = Organisation.objects.create(nom="Entité", niveau_id="Entity", parent=fr)
        cls.s1 = Organisation.objects.create(nom="Site 1", niveau_id="Site", parent=cls.e)
        cls.s2 = Organisation.objects.create(nom="Site 2", niveau_id="Site", parent=cls.e)
        cls.p = Periode.objects.create(type="annee", debut=datetime.date(2026, 1, 1), fin=datetime.date(2026, 12, 31),
                                       libelle="2026")
        cls.c = Campagne.objects.create(referentiel=Referentiel.objects.get(code=cls.REFERENTIEL), periode=cls.p,
                                        exercice=2026, statut=Campagne.Statut.OUVERTE)

    def saisir(self, valeurs):
        """{code: {organisation: valeur}} ; valeur NA = réponse N/A."""
        for code, par_org in valeurs.items():
            for org, v in par_org.items():
                Reponse.objects.update_or_create(
                    periode=self.p, kpi_id=code, organisation=org,
                    defaults={"valeur": None if v is NA else D(v), "non_applicable": v is NA,
                              "statut": Reponse.Statut.VALIDE})
        recalculer(self.c)
        return Calculateur(self.c)


def textes(d):
    for cat in ("fr", "en", "description", "a_inclure", "a_exclure", "source"):
        v = d.get(cat)
        for t in (v if isinstance(v, (tuple, list)) else (v,)):
            if t:
                yield t


class TermeEtatDeDurabiliteTests(SimpleTestCase):
    """#4 : « état de durabilité », plus jamais « déclaration relative à la durabilité »."""

    def test_aucun_ancien_terme_dans_les_modeles_esrs(self):
        for s in ESRS:
            for code, *_ in C.elements(s):
                for t in textes(S.KPIS[code]):
                    self.assertNotIn("relative à la durabilité", t, code)
                    self.assertNotIn("relatives à la durabilité", t, code)
        self.assertIn("état de durabilité", S.KPIS["GEN-INDEX-EXIGENCES"]["description"][0])


class EntreeProgressiveToutesNormesTests(SimpleTestCase):
    """#5 : ESRS 1 §126(a) écrit dans chaque KPI propre à E1, E2, E3, E5 et S1, avec la phrase de G1 ; jamais dans un KPI repris
    de la norme VS ou du catalogue (une seule définition, lue aussi dans une installation VS seule)."""

    def test_phrase_dans_chaque_kpi_propre_et_jamais_dans_un_kpi_repris(self):
        for m in (esrs_e1, esrs_e2, esrs_e3, esrs_e5, esrs_s1):
            for code, *_ in C.elements(m.SOCLE):
                fr, en = S.KPIS[code]["description"][:2] if isinstance(S.KPIS[code]["description"], tuple) else (
                    S.KPIS[code]["description"], "")
                with self.subTest(code=code):
                    if code in m.KPIS:
                        self.assertTrue(fr.endswith(L.PHASE_IN_G1[0]), fr)
                        self.assertTrue(en.endswith(L.PHASE_IN_G1[1]), en)
                    else:
                        self.assertNotIn("§126(a)", fr)
                        self.assertNotIn("§126(a)", en)


class AllegementsS1DansBP2Tests(SimpleTestCase):
    """#9 : ESRS 2 §10 ne vise que les points (b) à (e) ; la description cite aussi les allègements propres à S1 (point (f))."""

    def test_point_f_cite(self):
        fr, en = S.KPIS["GEN-PROGRESSIF-OMIS"]["description"]
        for t in (fr, en):
            self.assertIn("§126(f)", t)
            self.assertIn("S1-14", t)


class MembresAutreGenreTests(AvecCampagne):
    """#8 : membres d'un autre genre ou au genre non déclaré comptés au dénominateur des parts du §12(a) ; le rapport de l'AR 6
    ne compte que femmes et hommes ; un nombre N/A d'autres membres compte comme 0."""
    FICHIERS, REFERENTIEL = ("esrs_2.json",), "ESRS_2"

    def test_parts_sur_tous_les_membres(self):
        g = self.g
        calc = self.saisir({"GOV-CA-FEMMES": {g: 4}, "GOV-CA-HOMMES": {g: 5}, "GOV-CA-AUTRES": {g: 1},
                            "GOV-CA-INDEPENDANTS": {g: 3}})
        self.assertEqual(calc.valeur("GOV-CA-MEMBRES", g.id), D(10))
        self.assertEqual(calc.valeur("GOV-CA-PART-FEMMES", g.id), D("0.4"))  # avant : 4 / 9
        self.assertEqual(calc.valeur("GOV-CA-PART-HOMMES", g.id), D("0.5"))
        self.assertEqual(calc.valeur("GOV-CA-PART-AUTRES", g.id), D("0.1"))
        self.assertEqual(calc.valeur("GOV-CA-PART-INDEP", g.id), D("0.3"))
        self.assertEqual(calc.valeur("GOV-CA-RATIO-FH", g.id), D("0.8"))  # AR 6 : femmes / hommes seulement

    def test_autres_membres_na_comptent_comme_zero(self):
        g = self.g
        calc = self.saisir({"GOV-CA-FEMMES": {g: 4}, "GOV-CA-HOMMES": {g: 6}, "GOV-CA-AUTRES": {g: NA},
                            "GOV-CA-INDEPENDANTS": {g: 5}})
        self.assertEqual(calc.valeur("GOV-CA-MEMBRES", g.id), D(10))
        self.assertEqual(calc.valeur("GOV-CA-PART-FEMMES", g.id), D("0.4"))
        self.assertEqual(calc.valeur("GOV-CA-PART-INDEP", g.id), D("0.5"))
        self.assertIs(calc.valeur("GOV-CA-PART-AUTRES", g.id), NA)


class ChaleurVapeurEtScope2Tests(SimpleTestCase):
    """#12 : NRJ-CHALEUR couvre la chaleur et la vapeur achetées (une seule définition pour la VS et l'E1 : l'énergie finale de
    la VS compte la vapeur reçue) ; la règle de l'E1 compare donc à l'électricité, la chaleur, la vapeur et le froid achetés.
    #13 : E1-11 §40(c) cite les prêts garantis d'un établissement financier. #17 : la méthode marché du scope 2 couvre la
    chaleur, la vapeur, le froid et le mix résiduel."""

    def test_chaleur_et_vapeur(self):
        d = S.KPIS["NRJ-CHALEUR"]
        self.assertEqual((d["fr"], d["en"]), ("Chaleur et vapeur achetées", "Purchased heat and steam"))
        self.assertIn("vapeur fatale", S._langue(d["description"], "fr"))
        self.assertIn("steam", S._langue(d["description"], "en"))
        self.assertIn("vapeur", S._langue(S.KPIS["FE-CHALEUR"]["description"], "fr"))
        gauche, op, droite = esrs_e1.REGLES["Énergie achetée nucléaire et renouvelable ≤ énergie achetée"][:3]
        self.assertEqual(droite, "([NRJ-ELEC] + [NRJ-CHALEUR] + [NRJ-FROID]) / 1000")
        self.assertIn("vapeur", esrs_e1.REGLES["Énergie achetée nucléaire et renouvelable ≤ énergie achetée"][3][0])

    def test_prets_garantis_et_methode_marche(self):
        fr, en = S.KPIS["CLI-IMMO-GARANTIES"]["description"]
        self.assertIn("établissement financier", fr)
        self.assertIn("loans collateralised by real estate", en)
        self.assertIn("valeur comptable des biens immobiliers de l'entreprise", fr)  # rien de retiré
        fr, en = S.KPIS["GES-S2-MB"]["description"]
        for mot in ("chaleur", "vapeur", "froid", "mix résiduel"):
            self.assertIn(mot, fr)
        self.assertIn("residual mix", en)


class EauEnZoneDeStressTests(AvecCampagne):
    """#19 : deux KPI, un par méthode. Site en zone de stress hydrique : prélèvement 1 000, rejets des procédés 200 et
    sanitaires 300. VS (B6 §37) : 1 000 − 200 = 800 ; ESRS (E3 AR 4) : 1 000 − 500 = 500. La règle de l'E3 revient sur le KPI
    de l'ESRS et ne se déclenche pas (500 ≤ 500) ; elle se déclencherait sur une valeur au sens de la VS (800 > 500)."""
    FICHIERS, REFERENTIEL = ("vs_base.json", "esrs_e3.json"), "ESRS_E3"

    def alertes(self):
        from .coherence import controles_regles
        return [d for d in controles_regles(self.c) if "EAU-CONSO-STRESS" in d["regle"].gauche]

    def test_deux_methodes_deux_valeurs(self):
        s1, s2 = self.s1, self.s2
        calc = self.saisir({"EAU-PRELEVEMENT": {s1: 1000, s2: 300}, "EAU-REJET-PROCESS": {s1: 200, s2: 0},
                            "EAU-REJET": {s1: 500, s2: 100}, "EAU-STRESS": {s1: 800, s2: 0},
                            "EAU-CONSO-STRESS": {s1: 500, s2: 0}})
        self.assertEqual(calc.valeur("EAU-CONSOMMATION", self.g.id), D(700))
        self.assertEqual(calc.valeur("EAU-CONSO-STRESS", self.g.id), D(500))
        self.assertEqual(self.alertes(), [])
        self.saisir({"EAU-CONSO-STRESS": {s1: 800}})  # valeur au sens de la VS saisie par erreur
        self.assertEqual(len(self.alertes()), 1)

    def test_kpi_de_la_vs_hors_de_l_e3(self):
        self.assertNotIn("EAU-STRESS", {c for c, *_ in C.elements(esrs_e3.SOCLE)})
        self.assertIn("B6 §37", S.KPIS["EAU-STRESS"]["description"][0])
        self.assertNotIn("Dire dans le texte des méthodes", S.KPIS["EAU-STRESS"]["description"][0])


class TauxDeRotationTests(AvecCampagne):
    """#22 : départs de salariés en contrat permanent divisés par l'effectif moyen de tous les salariés (S1 AR 11), recalculé
    à chaque niveau sur les totaux. Site 1 : 8 départs, 95 salariés en moyenne (dont 80 en contrat permanent) ; site 2 : 3
    départs, 25 en moyenne. Avant : 8 / 80 = 10 % au site 1 (effectif permanent moyen)."""
    FICHIERS, REFERENTIEL = ("esrs_s1.json",), "ESRS_S1"

    def test_denominateur_effectif_moyen_total(self):
        self.assertNotIn("SOC-EFF-CDI-MOYEN", S.KPIS)
        self.assertEqual(S.KPIS["SOC-ROTATION-CDI"]["formule"], "[SOC-DEPARTS-CDI] / [SOC-EFF-MOYEN]")
        calc = self.saisir({"SOC-DEPARTS-CDI": {self.s1: 8, self.s2: 3}, "SOC-EFF-MOYEN": {self.s1: 95, self.s2: 25}})
        self.assertAlmostEqual(float(calc.valeur("SOC-ROTATION-CDI", self.s1.id)), 8 / 95)
        self.assertAlmostEqual(float(calc.valeur("SOC-ROTATION-CDI", self.g.id)), 11 / 120)


class EcartDeRemunerationChaqueNormeSonCalculTests(AvecCampagne):
    """#23 : l'ESRS S1 a ses propres rémunérations horaires (AR 31, AR 32 : toujours demandées) ; la VS garde les siennes (B10
    §42(b) : seulement pour une entreprise déjà tenue de déclarer l'écart, écart calculé dans le classeur de l'EFRAG).
    Même entreprise : VS 25 / 22 (rémunération annuelle totale / heures), soit 12 % ; S1 26 / 21 (moyenne qu'elle décrit
    dans ses méthodes), soit 5 / 26 ≈ 19,2 %. #24 : les rémunérations horaires de la VS sont « Restreint »."""
    FICHIERS, REFERENTIEL = ("vs_base.json", "esrs_s1.json", "transparence_remunerations.json"), "ESRS_S1"

    def test_deux_ecarts_differents_sur_un_meme_jeu(self):
        g = self.g
        calc = self.saisir({"SOC-REMU-H-HOMMES": {g: 25}, "SOC-REMU-H-FEMMES": {g: 22},
                            "SOC-S1-REMU-H-HOMMES": {g: 26}, "SOC-S1-REMU-H-FEMMES": {g: 21}})
        ecart_s1 = calc.valeur("SOC-ECART-REMU-H", g.id)
        self.assertAlmostEqual(float(ecart_s1), 5 / 26)
        self.assertNotAlmostEqual(float(ecart_s1), (25 - 22) / 25)  # écart de la VS (classeur de l'EFRAG)
        calc = self.saisir({"SOC-REMU-H-HOMMES": {g: NA}, "SOC-REMU-H-FEMMES": {g: NA}})  # VS : pas tenue de déclarer
        self.assertEqual(calc.valeur("SOC-ECART-REMU-H", g.id), ecart_s1)

    def test_confidentialite_et_methodes_dites(self):
        from referentiel.models import KPI

        for code in ("SOC-REMU-H-HOMMES", "SOC-REMU-H-FEMMES", "SOC-S1-REMU-H-HOMMES", "SOC-S1-REMU-H-FEMMES"):
            self.assertEqual(KPI.objects.get(code=code).confidentialite, "Restreint", code)
        self.assertIn("Méthode de la norme VS", S.KPIS["SOC-REMU-H-HOMMES"]["description"][0])
        self.assertIn("Méthode de l'ESRS S1", S.KPIS["SOC-S1-REMU-H-HOMMES"]["description"][0])
        self.assertIn("Méthode de la directive", S.KPIS["SOC-ECART-MOY-HOR"]["description"][0])
        self.assertNotIn("SOC-REMU-H-HOMMES", {c for c, *_ in C.elements(esrs_s1.SOCLE)})


class PaiementsEnNombreEtEnValeurTests(AvecCampagne):
    """#31 : part des paiements conformes en nombre de factures et en valeur, saisies par entité. Entité : 100 factures dont
    80 à temps (80 %) ; 500 000 € payés dont 300 000 € à temps (60 %) : les deux mesures diffèrent sur un même jeu."""
    FICHIERS, REFERENTIEL = ("esrs_g1.json",), "ESRS_G1"

    def test_deux_mesures(self):
        e = self.e
        calc = self.saisir({"GOV-FACTURES": {e: 100}, "GOV-FACTURES-A-TEMPS": {e: 80},
                            "GOV-FACTURES-MONTANT": {e: 500000}, "GOV-FACTURES-MONTANT-A-TEMPS": {e: 300000}})
        self.assertEqual(calc.valeur("GOV-PAIEMENT-PART-CONFORME", e.id), D("0.8"))
        self.assertEqual(calc.valeur("GOV-PAIEMENT-PART-CONFORME-VAL", e.id), D("0.6"))
        self.assertEqual(calc.valeur("GOV-PAIEMENT-PART-CONFORME-VAL", self.g.id), D("0.6"))


class Scope3EtDeclarationTests(SimpleTestCase):
    """#34 : les quinze catégories du scope 3 de la VS au même niveau, celui de l'entreprise (VS §51 : catégories
    significatives selon l'évaluation de l'entreprise). #36 : « Employeur tenu de déclarer cette année » facultatif."""

    def test_quinze_categories_pour_l_entreprise(self):
        vs = next(s for s in S.SOCLES if s["code"] == "VS_BASE")
        s3 = [c for c, *_ in C.elements(vs) if c.startswith("GES-S3-")]
        self.assertEqual(len(s3), 15)
        self.assertEqual({S.KPIS[c]["niveau"] for c in s3}, {"haut"})
        self.assertEqual(len({S._langue(S.KPIS[c]["description"], "fr").split(".")[-2] for c in s3}), 1)  # même phrase N/A

    def test_declaration_facultative(self):
        tr = next(s for s in S.SOCLES if s["code"] == "TRANSPARENCE_REMU")
        self.assertEqual({c: o for c, *_, o in C.elements(tr)}.get("SOC-ECART-DECL-SOUMIS"), False)
