"""(bugs et sécurité) : textes piégés qui bloquaient le serveur, formule avec une année impossible,
écritures d'un nombre, comparaison d'une règle de cohérence, identifiants forgés, blocage de connexion en IPv6."""
import time
from decimal import Decimal
from types import SimpleNamespace

from django.core.exceptions import ValidationError
from django.test import Client, SimpleTestCase, TestCase

from referentiel import connexion as CX
from referentiel import formule as F

from . import markdown as MD
from . import saisie as S
from django.urls import reverse

from . import visuels as VS
from .aides_tests.echanges import Base


def _temps_processeur(texte):
    """Temps processeur du fil (pas l'horloge : une machine chargée par d'autres processus ne le fait pas grandir) du
    rendu, du texte lisible et de l'extrait d'un texte."""
    debut = time.thread_time()
    MD.rendu(texte, 4)
    MD.texte_lisible(texte)
    MD.extrait(texte)
    return time.thread_time() - debut


class TextesPiegesTests(SimpleTestCase):
    # longueur × 4 : un rendu linéaire prend environ 4 fois plus de temps (mesuré de 3,7 à 4,7), un rendu quadratique
    # 16 fois (mesuré de 11 à 15 sur le premier motif rendu quadratique exprès) ; seuil entre les deux
    CROISSANCE_MAX = 8
    PLANCHER = 0.02  # secondes : en dessous, la mesure est trop petite pour un rapport (et le rendu assez rapide)

    def test_rendu_markdown_reste_rapide(self):
        """Des milliers d'espaces, de « ** » ou de « [ » : le rendu ne dépend plus du carré (ou du cube) de la longueur.

        Mesure du temps processeur à deux longueurs (n et 4 n) : le rapport ne dépend ni de la vitesse de la machine ni
        de sa charge. Jusqu'à trois tours alternés, minimum de chaque longueur : un écart passager ne fait pas échouer,
        un rendu quadratique échoue à chaque tour."""
        cas = {"# a": lambda n: "# a" + " " * (4 * n) + "b", "**a ": lambda n: "**a " * n, "[": lambda n: "[" * (4 * n),
               "*a ": lambda n: "*a " * (4 * n // 3), "_a ": lambda n: "_a " * (4 * n // 3), "~~a ": lambda n: "~~a " * n,
               "[a](": lambda n: "[a](" * n, "![a": lambda n: "![a" * (6 * n // 5)}
        for nom, texte in cas.items():
            court, long_ = texte(1250), texte(5000)  # 5 000 : la longueur d'avant (20 000 espaces, 5 000 « ** »…)
            t_court = t_long = float("inf")
            for _ in range(3):
                t_court, t_long = min(t_court, _temps_processeur(court)), min(t_long, _temps_processeur(long_))
                if t_long < self.PLANCHER or t_long < self.CROISSANCE_MAX * t_court:
                    break
            self.assertLess(t_long, 5, nom)  # borne d'avant, en temps processeur
            self.assertTrue(t_long < self.PLANCHER or t_long < self.CROISSANCE_MAX * t_court,
                            f"{nom!r} : {t_court:.3f} s puis {t_long:.3f} s pour une longueur 4 fois plus grande")

    def test_titres_inchanges(self):
        self.assertEqual(MD.rendu("## Titre ##", 4), "<h5>Titre</h5>")
        self.assertEqual(MD.rendu("# a#", 4), "<h4>a</h4>")
        self.assertEqual(MD.rendu("**gras** et [x](https://a.b)", 4),
                         '<p><strong>gras</strong> et <a href="https://a.b" target="_blank" rel="noopener noreferrer">x</a></p>')

    def test_journal_texte_long_non_analyse(self):
        from .administration import traduire_texte_journal

        def temps_processeur(texte):
            debut = time.thread_time()
            self.assertEqual(traduire_texte_journal(texte), texte)
            return time.thread_time() - debut

        traduire_texte_journal(" (")  # premier appel : remplit les caches (motifs, textes de la Visualisation), hors mesure
        # Comme le rendu Markdown : temps processeur (pas l'horloge) à deux longueurs (n et 4 n), minimum de chaque
        # longueur sur trois tours alternés. Un texte trop long n'est pas analysé : le temps reste minuscule (sous le
        # plancher) ; si l'analyse redevient coûteuse, il grandit comme le carré de la longueur et le test échoue.
        court, long = " (" * 2500, " (" * 10000
        t_court = t_long = float("inf")
        for _ in range(3):
            t_court, t_long = min(t_court, temps_processeur(court)), min(t_long, temps_processeur(long))
            if t_long < self.PLANCHER or t_long < self.CROISSANCE_MAX * t_court:
                break
        self.assertLess(t_long, 1)  # borne d'avant, en temps processeur
        self.assertTrue(t_long < self.PLANCHER or t_long < self.CROISSANCE_MAX * t_court,
                        f"{t_court:.3f} s puis {t_long:.3f} s pour une longueur 4 fois plus grande")


class FormuleAnneeTests(SimpleTestCase):
    def test_annee_impossible_refusee(self):
        for texte in ("[A] - [A@0000]", "[A@9999]", "[A@1899]"):
            with self.assertRaises(F.FormuleInvalide, msg=texte):
                F.analyser(texte)
        F.analyser("[A] - [A@2021]")


class LectureNombreTests(SimpleTestCase):
    nombre = SimpleNamespace(est_pourcentage=False, est_entier=False, symbole="")
    pourcent = SimpleNamespace(est_pourcentage=True, est_entier=False, symbole="%")

    def test_ecritures_inhabituelles_refusees(self):
        for texte in ("1e3", "1E-20", "1_000", "١٢٣", "²", "NaN", "Infinity"):
            with self.assertRaises(ValidationError, msg=texte):
                S.lire_nombre(texte, self.nombre)

    def test_valeur_arrondie_a_ce_que_la_base_garde(self):
        self.assertEqual(S.lire_nombre("33,333333333333", self.pourcent), Decimal("0.3333333333"))
        self.assertEqual(S.lire_nombre("12,5", self.nombre), Decimal("12.5"))
        self.assertEqual(S.lire_nombre("-12", self.nombre), Decimal("-12"))
        self.assertFalse(S.lire_nombre("-0", self.nombre).is_signed())

    def test_pourcentage_force_sans_bornes(self):
        with self.assertRaises(ValidationError):
            S.lire_nombre("150", self.pourcent)
        self.assertEqual(S.lire_nombre("150", self.pourcent, bornes=False), Decimal("1.5"))
        self.assertEqual(S.lire_nombre("-12", self.pourcent, bornes=False), Decimal("-0.12"))


class RegleArrondieTests(SimpleTestCase):
    def test_un_tiers_trois_fois_vaut_un(self):
        from .coherence import respecte

        regle = SimpleNamespace(tolerance=Decimal(0), operateur="=")
        tiers = Decimal(1) / Decimal(3)
        self.assertTrue(respecte(regle, tiers + tiers + tiers, Decimal(1)))
        self.assertFalse(respecte(regle, Decimal("0.99"), Decimal(1)))


class IdentifiantsTests(SimpleTestCase):
    def test_chiffres_ascii_seulement(self):
        from .vues_communes import identifiant

        self.assertEqual(identifiant("12"), 12)
        for texte in ("²", "١٢", "", None, "9" * 19, "1a"):
            self.assertEqual(identifiant(texte), 0, texte)


class BlocageIPv6Tests(SimpleTestCase):
    def test_ipv6_ramenee_a_son_reseau(self):
        self.assertEqual(CX._reseau("2001:db8:1:2:aaaa::1"), CX._reseau("2001:db8:1:2:bbbb::9"))
        self.assertNotEqual(CX._reseau("2001:db8:1:2::1"), CX._reseau("2001:db8:1:3::1"))
        self.assertEqual(CX._reseau("192.0.2.7"), "192.0.2.7")
        self.assertEqual(CX._reseau(""), "")


class FichiersTests(SimpleTestCase):
    def test_caracteres_interdits_en_xml_retires(self):
        from . import fichiers as X

        self.assertEqual(X.sans_controle("abc\uffff\ufffe\ud800d"), "abcd")

    def test_preuve_au_nom_non_latin_garde_son_extension(self):
        from parametres import rangement as RG

        self.assertEqual(RG._nom_fichier("отчёт.pdf"), "file.pdf")
        self.assertEqual(RG._nom_fichier("a/../../b.pdf"), "b.pdf")
        self.assertEqual(RG._nom_fichier("x.html.pdf"), "x.html.pdf")

    def test_compteur_de_lignes_borne(self):
        from .garde_requetes import nombre_envoye

        self.assertEqual(nombre_envoye({"nb": "99999999999", "a": 1}, "nb"), 2)
        self.assertEqual(nombre_envoye({"nb": "abc"}, "nb"), 0)


class GardeRequetesTests(TestCase):
    def test_octet_nul_et_envoi_anonyme_trop_gros(self):
        c = Client()
        self.assertEqual(c.get("/connexion/?a=%00").status_code, 400)
        self.assertEqual(c.post("/connexion/", {"username": "a\x00", "password": "x"}).status_code, 400)
        gros = b"x" * (2 * 1024 * 1024)
        self.assertEqual(c.post("/connexion/", data=gros, content_type="application/octet-stream").status_code, 413)
        self.assertIn(c.post("/connexion/", {"username": "a", "password": "x"}).status_code, (200, 302))


ENORME = "99999999999999999999"


class AdresseVisualisationTests(Base):
    """Visualisation : ?theme= (et ?org=, ?periode=) démesuré ignoré."""

    def test_filtres_depuis_adresse_bornes(self):
        f = VS.filtres_depuis_adresse({"theme": f"{ENORME},3", "org": ENORME, "periode": ENORME})
        self.assertEqual(f, {"themes": [3]})
        erreurs = []
        self.assertEqual(VS.nettoyer_filtres({"themes": [int(ENORME)]}, erreurs), {})
        self.assertEqual(len(erreurs), 1)

    def test_pages_sans_erreur(self):
        self.client.force_login(self.admin)
        for url in (reverse("collecte:visu"), reverse("collecte:visu_kpi", args=["EFF"])):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url, {"theme": ENORME}).status_code, 200)


class AdresseHistoriqueTests(Base):
    """Historique / Journal : org, exercice ou personne démesurés ignorés."""

    def test_filtres_ignores(self):
        self.client.force_login(self.admin)
        for nom in ("collecte:historique", "collecte:admin_journal"):
            for params in ({"org": ENORME}, {"exercice": "999999"}, {"exercice": ENORME}, {"personne": ENORME}, {"org": "²"}):
                with self.subTest(nom=nom, params=params):
                    self.assertEqual(self.client.get(reverse(nom), params).status_code, 200)

    def test_filtre_valide_garde(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse("collecte:admin_journal"), {"exercice": "2026", "org": str(self.e1.pk)})
        # plusieurs valeurs à la fois désormais : des listes
        self.assertEqual((r.context["exercices_choisis"], r.context["orgs_choisies"]), (["2026"], [str(self.e1.pk)]))
