"""Modèle « ESRS 2 – Informations générales » (ESRS révisées) : contrôle et couverture des 96 lignes de son inventaire,
KPI repris de la norme volontaire VS sans redéfinition, installation seule et après la VS (un seul KPI partagé), niveaux
choisis par l'outil (tout est donné une fois pour l'entreprise), part des membres indépendants et rapport femmes / hommes
calculés, bloc des exigences générales (GDR) des sujets propres à l'entreprise, et saisie de KPI de chaque format dans
l'écran Saisie (texte, oui / non, liste, nombre, montant, pourcentage, tableau)."""
import datetime
import re
from decimal import Decimal

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from parametres.models import TypeReponse
from referentiel.bibliotheque import controle as C
from referentiel.bibliotheque import socles as S
from referentiel.bibliotheque.definitions import couverture, esrs_2
from referentiel.models import KPI, ElementReferentiel, Organisation, Referentiel, Utilisateur

from .aides_tests.paquets import vider
from . import paquets as P
from .calcul import Calculateur, recalculer
from .models import Campagne, Periode, Reponse

D = Decimal
FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}
REPRIS = {"GEN-PERIMETRE", "GOV-CA-FEMMES", "GOV-CA-HOMMES", "GOV-REV-ARMES", "GOV-REV-CHARBON", "GOV-REV-CHIMIE", "GOV-REV-GAZ",
          "GOV-REV-PETROLE", "GOV-REV-TABAC"}


def installer(fichier):
    a = P.analyser(P.fourni(fichier).paquet, source=fichier, fourni=True)
    assert a.erreur == "" and a.compteurs["rejet"] == 0 and a.compteurs["conflit"] == 0, (a.erreur, a.compteurs)
    P.appliquer(None, a)


class ModeleGeneralitesTests(SimpleTestCase):
    def test_controle_et_couverture(self):
        socle = next(s for s in S.SOCLES if s["code"] == "ESRS_2")
        r = C.controler(socle, couverture=couverture(esrs_2), propres=set(esrs_2.KPIS), regles_propres=set(esrs_2.REGLES))
        self.assertEqual(r.erreurs, [])
        self.assertEqual(r.avertissements, [])
        self.assertEqual((r.chiffres["couverture"]["total"], r.chiffres["couverture"]["taux"]), (97, 100))
        self.assertEqual((r.chiffres["kpi"], len(esrs_2.KPIS)), (104, 95))

    def test_kpi_repris_de_la_norme_vs_non_redefinis(self):
        codes = {c for c, *_ in C.elements(esrs_2.SOCLE)}
        self.assertFalse(REPRIS & set(esrs_2.KPIS))
        self.assertTrue(REPRIS <= codes)
        # autres définitions (revue des doublons) : jamais placés dans l'ESRS 2
        for code in ("GEN-CONFORMITE", "GEN-NACE", "STR-PRODUITS", "STR-MARCHES", "GOV-REV-SECTEURS"):
            self.assertNotIn(code, codes)

    def test_references_dans_l_arbre(self):
        """Chaque KPI cite l'exigence de son thème (« GOV-1 · 12(a) ») ; la description cite le paragraphe."""
        for code, theme, ref, _ in C.elements(esrs_2.SOCLE):
            attendu = {"ESRS1": "ESRS 1"}.get(theme, theme.replace("_", "-"))
            with self.subTest(code=code):
                self.assertTrue(ref.startswith(attendu + " · "), (theme, ref))
        for code, d in esrs_2.KPIS.items():
            with self.subTest(code=code):
                self.assertRegex(d["description"][0], r"ESRS [12] §\d+")
                self.assertRegex(d["description"][1], r"ESRS [12] §\d+")

    def test_textes_francais_sans_contraction_oubliee(self):
        """Le bloc commun GDR écrit « liés à {sujet} » : le sujet des sujets propres doit éviter « à les »."""
        for code, d in esrs_2.KPIS.items():
            for texte in (d["fr"], d["description"][0]):
                with self.subTest(code=code):
                    self.assertIsNone(re.search(r"\bà (les|le) ", texte), texte)

    def test_mesure_transitoire_des_effets_financiers_dans_la_description(self):
        for code in ("STR-EFFETS-ATTENDUS", "STR-EFFETS-HORIZONS"):
            self.assertIn("ESRS 1 §125(b)-(c)", esrs_2.KPIS[code]["description"][1])


class InstallationGeneralitesTests(TestCase):
    """Base neuve : niveaux Groupe › Pays › Entité › Site ; VS de base et complète installées, puis ESRS 2."""

    @classmethod
    def setUpTestData(cls):
        vider()
        for f in ("vs_base.json", "vs_complet.json", "esrs_2.json"):
            installer(f)
        cls.g = Organisation.objects.create(nom="Groupe", niveau_id="Group")
        fr = Organisation.objects.create(nom="France", niveau_id="Country", parent=cls.g)
        e = Organisation.objects.create(nom="Entité", niveau_id="Entity", parent=fr)
        Organisation.objects.create(nom="Usine A", niveau_id="Site", parent=e)
        cls.p = Periode.objects.create(type="annee", debut=datetime.date(2026, 1, 1), fin=datetime.date(2026, 12, 31), libelle="2026")
        cls.c = Campagne.objects.create(referentiel=Referentiel.objects.get(code="ESRS_2"), periode=cls.p, exercice=2026,
                                        statut=Campagne.Statut.OUVERTE)
        cls.admin = Utilisateur.objects.create_user("admin", "admin@exemple.test", "x", role=Utilisateur.Role.ADMIN)

    def test_kpi_partages_avec_la_vs(self):
        for code, attendu in (("GOV-CA-FEMMES", {"VS_COMPLET", "ESRS_2"}), ("GEN-PERIMETRE", {"VS_BASE", "ESRS_2"}),
                              ("GOV-REV-CHARBON", {"VS_COMPLET", "ESRS_2"})):
            refs = set(ElementReferentiel.objects.filter(kpi_id=code).values_list("referentiel__code", flat=True))
            self.assertEqual(refs, attendu, code)

    def test_tout_est_donne_une_fois_pour_l_entreprise(self):
        codes = set(ElementReferentiel.objects.filter(referentiel__code="ESRS_2").values_list("kpi_id", flat=True))
        self.assertEqual(len(codes), 104)
        self.assertEqual(set(KPI.objects.filter(code__in=codes).values_list("granularite_id", flat=True)), {"Group"})

    def test_types_de_reponse(self):
        def type_(code):
            return TypeReponse.objects.get(code=KPI.objects.get(code=code).type_reponse_id)

        self.assertEqual(type_("GEN-IRO-TAB").format, TypeReponse.Format.TABLEAU)
        self.assertEqual([c["code"] for c in type_("GEN-IRO-TAB").colonnes], ["iro", "nature", "sujet", "chaine", "horizon"])
        self.assertEqual(KPI.objects.get(code="GEN-SPEC-ACT-TAB").type_reponse_id, "ESRS-TAB-ACTIONS")
        self.assertEqual(KPI.objects.get(code="GEN-SPEC-CIB-TAB").type_reponse_id, "ESRS-TAB-CIBLES")
        self.assertEqual(KPI.objects.get(code="GEN-SPEC-INDICATEURS").type_reponse_id, "ESRS-TAB-INDICATEURS")
        self.assertEqual(type_("GEN-CONFORMITE-ESRS").format, TypeReponse.Format.LISTE)
        self.assertEqual(type_("GEN-SPEC-POLIT-PARTIES").format, TypeReponse.Format.TEXTE)  # §42(d) : sujets sociaux possibles

    def test_saisie_de_chaque_format_puis_calcul(self):
        """Écran Saisie : le panneau de chaque KPI s'ouvre et la valeur s'enregistre ; parts calculées au niveau du groupe."""
        self.client.force_login(self.admin)
        page = self.client.get(reverse("collecte:saisie") + f"?campagne={self.c.pk}&org={self.g.pk}")
        self.assertEqual(page.status_code, 200)
        valeurs = (  # code, valeur saisie, contrôle de ce qui est enregistré
            ("GEN-CHAINE-VALEUR", "Fournisseurs de rang 1 et clients directs.", ("texte", "Fournisseurs de rang 1 et clients directs.")),
            ("GEN-MAT-DATE", "2026-10-15", ("texte", "2026-10-15")),
            ("STR-ACTIF-FOSSILE", "Non", ("texte", "Non")),
            ("GOV-REMU-LIEN", "Yes", ("texte", "Oui")),
            ("GEN-CONFORMITE-ESRS", "ESRS révisées (règlement délégué 2026/1563)", ("texte", "ESRS révisées (règlement délégué 2026/1563)")),
            ("GOV-CA-FEMMES", "4", ("valeur", D(4))),
            ("GOV-CA-HOMMES", "6", ("valeur", D(6))),
            ("GOV-CA-AUTRES", "0", ("valeur", D(0))),  # dénominateur = tous les membres (membres d'un autre genre)
            ("GOV-CA-INDEPENDANTS", "5", ("valeur", D(5))),
            ("GOV-REV-CHARBON", "0", ("valeur", D(0))),
            ("GOV-REMU-PART-VARIABLE", "20", ("valeur", D("0.2"))),
            ("GEN-IRO-TAB", "| Émissions des fours | Impact négatif réel | Changement climatique (E1) | Activités propres | "
                            "Court terme (période de reporting) |", ("lignes", 1)),
            ("GEN-SPEC-INDICATEURS", "| Taux de rebut | 2,5 | % | Usines |", ("lignes", 1)),
        )
        for code, saisie, (champ, attendu) in valeurs:
            with self.subTest(code=code):
                url = reverse("collecte:cellule", args=[self.c.pk, code, self.g.pk])
                html = self.client.get(url, **FETCH).json()["html"]
                self.assertIn(KPI.objects.get(code=code).libelle, html.replace("&#x27;", "'"))
                rep = self.client.post(url, {"action": "enregistrer", "version": "", "valeur": saisie, "commentaire": ""}, **FETCH).json()
                self.assertTrue(rep["ok"], rep)
                r = Reponse.objects.get(periode=self.p, kpi_id=code, organisation=self.g)
                if champ == "lignes":
                    self.assertEqual(len([x for x in r.texte.split("\n") if x.startswith("|")]) - 2, attendu, r.texte)
                else:
                    self.assertEqual(getattr(r, champ), attendu)
        recalculer(self.c)
        calc = Calculateur(self.c)
        self.assertEqual(calc.valeur("GOV-CA-PART-INDEP", self.g.id), D("0.5"))
        self.assertEqual(round(calc.valeur("GOV-CA-RATIO-FH", self.g.id), 4), D("0.6667"))


class InstallationSeuleTests(TestCase):
    """ESRS 2 sans la VS : les KPI repris et leur liste de choix (base de présentation) arrivent avec le modèle."""

    def test_installation_seule(self):
        vider()
        installer("esrs_2.json")
        self.assertEqual(KPI.objects.get(code="GEN-PERIMETRE").type_reponse_id, "VS-PERIMETRE")
        self.assertEqual(TypeReponse.objects.get(code="VS-PERIMETRE").format, TypeReponse.Format.LISTE)
        self.assertEqual(ElementReferentiel.objects.filter(referentiel__code="ESRS_2").count(), 104)
