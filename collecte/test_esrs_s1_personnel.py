"""Modèle « ESRS S1 – Personnel de l'entreprise » (ESRS révisées) : contrôle et couverture (54 lignes de l'inventaire
maître), KPI repris de la norme volontaire VS et du catalogue sans redéfinition, réutilisations refusées absentes de
l'arbre, données de rémunération sensibles, installation avec la VS (base et complète) et la transparence des
rémunérations sans conflit ni KPI en double, niveaux choisis, et calculs refaits à la main à chaque niveau de l'arbre :
parts (négociation collective, santé et sécurité), taux de rotation, taux d'accidents par million d'heures, décès,
mixité de la direction, écart de rémunération et ratio de la rémunération totale."""
import datetime
from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from referentiel.bibliotheque import controle as C
from referentiel.bibliotheque import socles as S
from referentiel.bibliotheque.definitions import couverture, esrs_s1
from referentiel.bibliotheque.outils import langue
from referentiel.models import KPI, ElementReferentiel, Organisation, Referentiel

from . import paquets as P
from .aides_tests.paquets import vider
from .calcul import Calculateur, recalculer
from .models import Campagne, Periode, RegleCoherence, Reponse

D = Decimal
FICHIER = "esrs_s1.json"
# KPI repris tels quels (norme VS, catalogue commun) : jamais redéfinis par le modèle S1 (revue des doublons de l'atelier).
REPRIS = {"SOC-EFFECTIF", "SOC-EFF-FEMMES", "SOC-EFF-HOMMES", "SOC-EFF-GENRE-AUTRE", "SOC-EFF-GENRE-NC", "SOC-EFF-CDI",
          "SOC-DEPARTS-CDI", "SOC-SAL-CONVENTION", "SOC-HANDICAP", "SOC-PART-HANDICAP", "SOC-HEURES-FORM", "SOC-FORM-PAR-SAL",
          "SOC-HEURES-TRAV", "SOC-ACCIDENTS-ENREG", "SOC-DECES", "SOC-CODE-TRAITE",
          "SOC-CODE-FORCE", "SOC-CODE-ENFANTS", "SOC-PLAINTES"}
# Réutilisations refusées (autre définition, population ou méthode) : ces KPI ne sont pas dans l'arbre de S1.
REFUSES = {"SOC-REMU-H-HOMMES", "SOC-REMU-H-FEMMES",  # VS : autre définition (B10 §42(b)), chaque norme son calcul
           "SOC-ECART-REMU", "SOC-ECART-MOY-HOR", "SOC-REMU-MOY-HOR-F", "SOC-REMU-MOY-HOR-H", "SOC-MANAGERS-FEMMES",
           "SOC-MANAGERS-HOMMES", "SOC-INDEPENDANTS", "SOC-INTERIMAIRES", "SOC-SALAIRE-MINIMUM", "SOC-JOURS-PERDUS",
           "SOC-INCIDENTS", "SOC-TF", "SOC-AT", "SOC-ETP", "SOC-EFFECTIF-DEBUT", "SOC-TAUX-DEPART"}


def installer(fichier=FICHIER):
    a = P.analyser(P.fourni(fichier).paquet, source=fichier, fourni=True)
    assert a.erreur == "" and a.compteurs["rejet"] == 0 and a.compteurs["conflit"] == 0, (fichier, a.erreur, a.compteurs)
    P.appliquer(None, a)


class ModelePersonnelTests(SimpleTestCase):
    def setUp(self):
        self.socle = next(s for s in S.SOCLES if s["code"] == "ESRS_S1")
        self.codes = {c for c, *_ in C.elements(self.socle)}

    def test_controle_et_couverture(self):
        r = C.controler(self.socle, couverture=couverture(esrs_s1), propres=set(esrs_s1.KPIS),
                        regles_propres=set(esrs_s1.REGLES))
        self.assertEqual(r.erreurs, [])
        self.assertEqual((r.chiffres["couverture"]["total"], r.chiffres["couverture"]["taux"]), (54, 100))
        self.assertEqual((len(self.codes), len(esrs_s1.KPIS)), (100, 81))  # + rémunérations horaires propres à S1, − celles de la VS (chaque norme son calcul)

    def test_kpi_repris_non_redefinis(self):
        self.assertFalse(REPRIS & set(esrs_s1.KPIS))
        self.assertTrue(REPRIS <= self.codes)
        self.assertEqual(self.codes - set(esrs_s1.KPIS), REPRIS)

    def test_reutilisations_refusees_absentes(self):
        self.assertFalse(REFUSES & self.codes)

    def test_remunerations_sensibles(self):
        self.assertEqual(esrs_s1.KPIS["SOC-REMU-PLUS-HAUTE"]["confidentialite"], "Confidentiel")  # une seule personne
        self.assertEqual(esrs_s1.KPIS["SOC-REMU-MEDIANE"]["confidentialite"], "Restreint")
        self.assertEqual(esrs_s1.KPIS["SOC-ECART-REMU-H"]["agregation"], "Formule")  # jamais saisi
        self.assertEqual(esrs_s1.KPIS["SOC-ECART-REMU-H"]["type"], "Calculé")

    def test_textes_francais_sans_a_le_ni_a_les(self):
        """Le bloc commun écrit « liés à {sujet} » : corrigé en « liés au personnel ». Aucun texte français du modèle (noms,
        définitions, thèmes, règles) ne contient « à le » ni « à les » (contraction : « au », « aux »)."""
        import re

        textes = [(c, d["fr"]) for c, d in esrs_s1.KPIS.items()]
        textes += [(c, langue(d[cat], "fr")) for c, d in esrs_s1.KPIS.items()
                   for cat in ("description", "a_inclure", "a_exclure", "source")]
        textes += [(t[0], t[1]) for t in C.themes(self.socle)]
        textes += [(nom, nom + " " + langue(r[3], "fr")) for nom, r in esrs_s1.REGLES.items()]
        faute = re.compile(r"\b[àÀ] les?\b")
        for code, texte in textes:
            with self.subTest(code=code):
                self.assertIsNone(faute.search(texte or ""), texte)
        self.assertIn("liés au personnel", langue(esrs_s1.KPIS["SOC-PERSO-POLITIQUES"]["description"], "fr"))

    def test_chaque_kpi_cite_son_paragraphe(self):
        for code, d in esrs_s1.KPIS.items():
            with self.subTest(code=code):
                fr, en = d["description"]
                self.assertRegex(en, r"(ESRS S1, §|ESRS 2 §)")
                self.assertRegex(fr, r"(ESRS S1, §|ESRS 2 §)")


class InstallationPersonnelTests(TestCase):
    """Base neuve : Groupe › Pays › Entité › Site ; la VS (base et complète) et la transparence des rémunérations
    installées d'abord, puis ESRS S1. Trois sites : A1 et A2 (France, entité A), B1 (Espagne, entité B)."""

    @classmethod
    def setUpTestData(cls):
        vider()
        for f in ("vs_base.json", "vs_complet.json", "transparence_remunerations.json"):
            installer(f)
        installer()
        cls.g = Organisation.objects.create(nom="Groupe", niveau_id="Group")
        fr = Organisation.objects.create(nom="France", niveau_id="Country", parent=cls.g)
        es = Organisation.objects.create(nom="Espagne", niveau_id="Country", parent=cls.g)
        cls.ea = Organisation.objects.create(nom="Entité A", niveau_id="Entity", parent=fr)
        cls.eb = Organisation.objects.create(nom="Entité B", niveau_id="Entity", parent=es)
        cls.fr, cls.es = fr, es
        cls.a1 = Organisation.objects.create(nom="Site A1", niveau_id="Site", parent=cls.ea)
        cls.a2 = Organisation.objects.create(nom="Site A2", niveau_id="Site", parent=cls.ea)
        cls.b1 = Organisation.objects.create(nom="Site B1", niveau_id="Site", parent=cls.eb)
        p = Periode.objects.create(type="annee", debut=datetime.date(2026, 1, 1), fin=datetime.date(2026, 12, 31), libelle="2026")
        cls.c = Campagne.objects.create(referentiel=Referentiel.objects.get(code="ESRS_S1"), periode=p, exercice=2026,
                                        statut=Campagne.Statut.OUVERTE)
        par_site = {  # code : (A1, A2, B1)
            "SOC-EFFECTIF": (100, 50, 30), "SOC-SAL-CONVENTION": (100, 20, 0),
            "SOC-DEPARTS-CDI": (8, 2, 3), "SOC-EFF-MOYEN": (80, 40, 20),  # effectif moyen de tous les salariés (AR 11)
            "SOC-ACCIDENTS-ENREG": (2, 1, 0), "SOC-ACCIDENTS-NON-SAL": (1, 0, 0),
            "SOC-HEURES-TRAV": (160000, 80000, 48000), "SOC-HEURES-NON-SAL": (40000, 10000, 12000),
            "SOC-DECES": (1, 0, 0), "SOC-DECES-MALADIE": (1, 0, 0), "SOC-DECES-NON-SAL": (0, 0, 1), "SOC-DECES-SITE": (0, 1, 0),
            "SOC-SST-COUVERTS": (110, 50, 30), "SOC-NON-SALARIES": (20, 5, 10),
        }
        groupe = {"SOC-DIRECTION-F": 3, "SOC-DIRECTION-H": 6, "SOC-DIRECTION-AUTRE": 1, "SOC-S1-REMU-H-HOMMES": D("25"),
                  "SOC-S1-REMU-H-FEMMES": D("22"), "SOC-REMU-PLUS-HAUTE": 450000, "SOC-REMU-MEDIANE": 36000}
        for code, valeurs in par_site.items():
            for org, v in zip((cls.a1, cls.a2, cls.b1), valeurs):
                Reponse.objects.create(periode=p, kpi_id=code, organisation=org, valeur=D(v), statut=Reponse.Statut.VALIDE)
        for code, v in groupe.items():
            Reponse.objects.create(periode=p, kpi_id=code, organisation=cls.g, valeur=D(v), statut=Reponse.Statut.VALIDE)
        recalculer(cls.c)

    def val(self, code, org):
        return Calculateur(self.c).valeur(code, org.id)

    def proche(self, code, org, attendu):
        v = self.val(code, org)
        self.assertIsNotNone(v, (code, org.nom))
        self.assertAlmostEqual(float(v), attendu, places=6, msg=(code, org.nom))

    def test_kpi_partages_sans_doublon(self):
        """Un seul KPI pour une même donnée, placé dans chaque modèle qui la demande."""
        def modeles(code):
            return set(ElementReferentiel.objects.filter(kpi_id=code).values_list("referentiel__code", flat=True))
        self.assertEqual(modeles("SOC-EFFECTIF"), {"VS_BASE", "ESRS_S1"})
        self.assertEqual(modeles("SOC-REMU-H-HOMMES"), {"VS_BASE"})  # S1 a ses propres rémunérations horaires
        self.assertEqual(modeles("SOC-S1-REMU-H-HOMMES"), {"ESRS_S1"})
        self.assertEqual(modeles("SOC-DEPARTS-CDI"), {"VS_COMPLET", "ESRS_S1"})
        self.assertEqual(modeles("SOC-PLAINTES"), {"VS_COMPLET", "ESRS_S1"})
        self.assertEqual(modeles("SOC-ECART-MOY-HOR"), {"TRANSPARENCE_REMU"})  # autre écart, non repris
        self.assertEqual(ElementReferentiel.objects.filter(referentiel__code="ESRS_S1").count(), 100)

    def test_niveaux_choisis_par_l_outil(self):
        niveau = {c: KPI.objects.get(code=c).granularite_id for c in (
            "SOC-PERSO-POLIT-CONTENU", "SOC-PERSO-ACT-TAB", "SOC-EFF-CDI-F", "SOC-NON-SALARIES", "SOC-AMENDES-DH",
            "SOC-REMU-MEDIANE", "SOC-DIRECTION-F", "SOC-ECART-REMU-H", "SOC-TAUX-ACCIDENTS", "SOC-PART-CONVENTION")}
        self.assertEqual(niveau, {
            "SOC-PERSO-POLIT-CONTENU": "Group", "SOC-PERSO-ACT-TAB": "Group", "SOC-EFF-CDI-F": "Site", "SOC-NON-SALARIES": "Site",
            "SOC-AMENDES-DH": "Entity", "SOC-REMU-MEDIANE": "Group", "SOC-DIRECTION-F": "Group", "SOC-ECART-REMU-H": "Group",
            "SOC-TAUX-ACCIDENTS": "Site", "SOC-PART-CONVENTION": "Site"})

    def test_regles_de_coherence_installees(self):
        noms = set(RegleCoherence.objects.values_list("nom", flat=True))
        self.assertTrue(set(esrs_s1.REGLES) <= noms)
        self.assertTrue(set(esrs_s1.REGLES_REPRISES) <= noms)

    def test_part_des_salaries_couverts_par_une_convention(self):
        """Salariés couverts / effectif, recalculé à chaque niveau sur les totaux (pas une moyenne des parts)."""
        for org, attendu in ((self.a1, 100 / 100), (self.a2, 20 / 50), (self.b1, 0 / 30), (self.ea, 120 / 150),
                             (self.fr, 120 / 150), (self.es, 0.0), (self.g, 120 / 180)):
            self.proche("SOC-PART-CONVENTION", org, attendu)

    def test_taux_de_rotation(self):
        for org, attendu in ((self.a1, 8 / 80), (self.a2, 2 / 40), (self.b1, 3 / 20), (self.ea, 10 / 120), (self.g, 13 / 140)):
            self.proche("SOC-ROTATION-CDI", org, attendu)

    def test_taux_d_accidents_par_million_d_heures(self):
        for org, attendu in ((self.a1, 3e6 / 200000), (self.a2, 1e6 / 90000), (self.b1, 0.0), (self.ea, 4e6 / 290000),
                             (self.es, 0.0), (self.g, 4e6 / 350000)):
            self.proche("SOC-TAUX-ACCIDENTS", org, attendu)
        self.proche("SOC-TAUX-ACC-SALARIES", self.g, 3e6 / 288000)
        self.proche("SOC-TAUX-ACC-NON-SAL", self.g, 1e6 / 62000)
        self.proche("SOC-TAUX-ACC-NON-SAL", self.ea, 1e6 / 50000)
        self.assertEqual(self.val("SOC-ACCIDENTS-TOUS", self.g), D(4))

    def test_deces(self):
        """§37(b)(i) : accidents du personnel et des autres travailleurs sur les sites ; somme (b) avec la maladie."""
        for org, accidents, tous in ((self.a1, 0, 1), (self.a2, 1, 1), (self.b1, 1, 1), (self.ea, 1, 2), (self.g, 2, 3)):
            self.assertEqual(self.val("SOC-DECES-ACCIDENTS", org), D(accidents), org.nom)
            self.assertEqual(self.val("SOC-DECES-TOUS", org), D(tous), org.nom)

    def test_part_du_personnel_couverte_par_la_sante_et_la_securite(self):
        for org, attendu in ((self.a1, 110 / 120), (self.a2, 50 / 55), (self.b1, 30 / 40), (self.ea, 160 / 175),
                             (self.g, 190 / 215)):
            self.proche("SOC-PART-SST", org, attendu)

    def test_mixite_de_la_direction(self):
        self.proche("SOC-DIRECTION-PART-F", self.g, 3 / 10)
        self.proche("SOC-DIRECTION-PART-H", self.g, 6 / 10)
        self.assertIsNone(self.val("SOC-DIRECTION-PART-F", self.ea))  # saisie pour toute l'entreprise

    def test_ecart_de_remuneration_calcule_jamais_saisi(self):
        """(25 − 22) / 25 = 12 % : calculé depuis les rémunérations horaires de la VS, au niveau où elles sont saisies."""
        self.proche("SOC-ECART-REMU-H", self.g, 0.12)
        self.assertIsNone(self.val("SOC-ECART-REMU-H", self.ea))

    def test_ratio_de_la_remuneration_totale(self):
        self.proche("SOC-RATIO-REMU", self.g, 450000 / 36000)

    def test_ratio_et_remunerations_sensibles_pour_les_assistants(self):
        from .sensibles import codes_sensibles

        caches = codes_sensibles()
        self.assertTrue({"SOC-REMU-PLUS-HAUTE", "SOC-REMU-MEDIANE", "SOC-RATIO-REMU"} <= caches)
        self.assertNotIn("SOC-TAUX-ACCIDENTS", caches)
