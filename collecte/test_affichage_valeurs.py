"""Filet de tests de l'affichage et de la lecture des valeurs : figent le comportement actuel.

Format français (espaces, virgule), arrondi d'affichage, pourcentages stockés en fraction, N/A, oui / non et listes,
écarts avec N-1, lecture d'une saisie ou d'une cellule de fichier (virgule, point, %, espaces, nombres trop grands)."""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase

from parametres.models import TypeReponse, Unite
from referentiel.formule import NA
from referentiel.models import KPI, Niveau

from . import fichiers as X
from . import saisie as S
from .calcul import Decompte
from .models import Reponse
from .templatetags import collecte as T

D = Decimal


class NombreTests(SimpleTestCase):
    """Séparateur de milliers : espace fine insécable (U+202F)."""

    def test_separateurs_francais(self):
        self.assertEqual(T.nombre(D("1234567.891"), 2), "1\u202f234\u202f567,89")
        self.assertEqual(T.nombre(D("1234567.891"), 0), "1\u202f234\u202f568")
        self.assertEqual(T.nombre(D("-1234.5"), 1), "-1\u202f234,5")
        self.assertEqual(T.nombre(D(0), 3), "0,000")
        self.assertEqual(T.nombre(1234.5678), "1\u202f234,57")  # float, 2 décimales par défaut

    def test_arrondi_comme_excel(self):
        # comme Excel (exports, format « #,##0 ») : 0,5 s'arrondit en s'éloignant de zéro, pas au pair 
        self.assertEqual(T.nombre(D("2.5"), 0), "3")
        self.assertEqual(T.nombre(D("3.5"), 0), "4")
        self.assertEqual(T.nombre(D("0.125"), 2), "0,13")
        self.assertEqual(T.nombre(D("-2.5"), 0), "-3")
        self.assertEqual(T.nombre(1.005, 2), "1,01")  # float lu par son texte, pas par sa valeur binaire (1,00499…)
        self.assertTrue(T.nombre(D("1E+30"), 2).endswith(",00"))  # trop long pour arrondir en décimal : affiché tel quel, sans erreur

    def test_pas_de_moins_zero(self):
        # une petite valeur négative arrondie à zéro s'affiche « 0,00 », pas « -0,00 »
        self.assertEqual(T.nombre(D("-0.001"), 2), "0,00")

    def test_ecarts(self):
        self.assertEqual(T.ecart(None), "–")
        self.assertEqual(T.ecart(D("0.1")), "+10,0\u202f%")
        self.assertEqual(T.ecart(D("-0.054")), "-5,4\u202f%")
        self.assertEqual(T.ecart(D(0)), "0,0\u202f%")
        self.assertEqual(T.ecart(0.25), "+25,0\u202f%")  # float accepté
        self.assertEqual(T.pourcent(None), "")
        self.assertEqual(T.pourcent(D("0.505")), "51\u202f%")  # comme Excel : 50,5 → 51
        self.assertEqual(T.pourcent(D(1)), "100\u202f%")

    def test_fleche_et_seuil(self):
        self.assertEqual(T.ecart_fleche(None), "–")
        fort = T.ecart_fleche(D("0.3"), D("0.2"))
        self.assertIn('class="ecart-fort"', fort)
        self.assertIn("▲", fort)
        self.assertIn("+30,0\u202f%", fort)
        egal = T.ecart_fleche(D("0.2"), D("0.2"))  # au seuil : pas au-delà
        self.assertNotIn("ecart-fort", egal)
        self.assertIn("▼", T.ecart_fleche(D("-0.01")))
        self.assertIn("=", T.ecart_fleche(D(0)))
        self.assertEqual(T.ecart_sous(D("0.3")), "")  # sans seuil : rien
        self.assertEqual(T.ecart_sous(D("0.1"), D("0.2")), "")
        sous = T.ecart_sous(D("-0.5"), D("0.2"), "P-1")
        self.assertIn("vs P-1", sous)
        self.assertIn("-50,0\u202f%", sous)
        self.assertIn("vs N-1", T.ecart_sous(D("0.5"), D("0.2"), ""))

    def test_pluriel(self):
        self.assertEqual([T.pluriel(n) for n in (0, 1, 2, -2, "3", None, [1], [1, 2])], ["", "", "s", "s", "s", "", "", "s"])
        self.assertEqual(T.pluriel(5, "x"), "x")

    def test_ecart_avec_n1(self):
        self.assertIsNone(S.ecart(None, D(1)))
        self.assertIsNone(S.ecart(D(1), None))
        self.assertIsNone(S.ecart(D(1), D(0)))
        self.assertEqual(S.ecart(D(110), D(100)), D("0.1"))
        self.assertEqual(S.ecart(D(-50), D(-100)), D("0.5"))  # base négative : écart rapporté à sa valeur absolue
        self.assertEqual(S.ecart(D(0), D(100)), D(-1))


class LectureCelluleTests(SimpleTestCase):
    def test_lire_decimal(self):
        cas = {"1234,5": "1234.5", "1 234,5": "1234.5", "1\xa0234,5": "1234.5", "1 234,5": "1234.5", "1,234.5": "1234.5",
               "1.234,5": "1234.5", "12 %": "12", "12%": "12", "-3": "-3", "1e3": "1E+3", "0,1": "0.1"}
        for texte, attendu in cas.items():
            self.assertEqual(X.lire_decimal(texte), D(attendu), texte)
        self.assertEqual(X.lire_decimal("1,234"), D("1.234"))  # virgule seule : toujours décimale (pas un millier)
        self.assertEqual(X.lire_decimal(0.1), D("0.1"))  # float de la cellule : pas d'erreur binaire
        self.assertEqual(X.lire_decimal(12), D(12))
        for vide in (None, "", "   ", "%"):
            self.assertIsNone(X.lire_decimal(vide), repr(vide))
        for mauvais in ("abc", "nan", "inf", "1.234.567", True, "12 kWh"):
            with self.assertRaises(ValueError, msg=repr(mauvais)):
                X.lire_decimal(mauvais)
        self.assertIsNone(X.lire_decimal_ou_none("abc"))

    def test_texte_et_oui(self):
        self.assertEqual(X.texte(12.0), "12")
        self.assertEqual(X.texte(12.5), "12.5")
        self.assertEqual(X.texte(None), "")
        self.assertEqual(X.texte("  a  "), "a")
        self.assertEqual(X.texte("'=1+1"), "=1+1")  # apostrophe de protection retirée
        for v in ("Oui", "yes", "VRAI", "true", "1", "x", "N/A", "na"):
            self.assertTrue(X.oui(v), v)
        for v in ("Non", "no", "0", "", None, "faux"):
            self.assertFalse(X.oui(v), v)


class AvecKpi(TestCase):
    def setUp(self):
        self.ouinon = TypeReponse.objects.create(code="OuiNon", libelle="Oui / non", format="oui_non",
                                                 traductions={"en": {"valeurs": ["Yes", "No"]}})
        self.liste = TypeReponse.objects.create(code="Certif", libelle="Certification", format="liste", valeurs=["ISO 14001", "Aucune"])
        self.kwh = Unite.objects.create(code="kWh_t", symbole="kWh", decimales=0)
        self.salaries = Unite.objects.create(code="sal_t", symbole="salariés", entier=True, decimales=0)

        def kpi(code, **autres):
            return KPI.objects.create(code=code, type_saisie_id="Saisi", granularite_id=Niveau.ENTITY, **autres)
        self.nrj = kpi("NRJ", unite=self.kwh, decimales=1, methode_agregation="Somme")
        self.tx = kpi("TX", type_reponse_id="Pourcentage", decimales=1)
        self.eff = kpi("EFF", unite=self.salaries, methode_agregation="Somme")  # décimales par défaut (2)
        self.pol = kpi("POL", type_reponse=self.ouinon, methode_agregation="Décompte")
        self.cert = kpi("CERT", type_reponse=self.liste, methode_agregation="Décompte")

    def r(self, **champs):
        return Reponse(**champs)


class AffichageValeurTests(AvecKpi):
    def test_valeur_d_une_reponse(self):
        self.assertEqual(T.valeur(None, self.nrj), "–")
        self.assertEqual(T.valeur(self.r(non_applicable=True, valeur=D(5)), self.nrj), "N/A")
        self.assertEqual(T.valeur(self.r(), self.nrj), "–")
        self.assertEqual(T.valeur(self.r(valeur=D("1234.56")), self.nrj), "1\u202f234,6 kWh")
        self.assertEqual(T.valeur(self.r(valeur=D("1234.56")), self.nrj, False), "1\u202f234,6")
        self.assertEqual(T.valeur(self.r(valeur=D("0.355")), self.tx), "35,5\u202f%")  # fraction stockée, affichée sur 100
        self.assertEqual(T.valeur(self.r(valeur=D("0.355")), self.tx, False), "35,5")
        self.assertEqual(T.valeur(self.r(valeur=D(1)), self.tx), "100,0\u202f%")

    def test_unite_entiere_sans_decimale(self):
        # une unité « nombre entier » (comptage) donne toujours 0 décimale au KPI, comme l'aperçu
        # de l'unité (avant : « 12,00 salariés »)
        self.assertEqual(self.eff.decimales, 0)
        self.assertTrue(self.eff.est_entier)
        self.assertEqual(T.valeur(self.r(valeur=D(12)), self.eff), "12 salariés")
        self.assertEqual(T.exemple_unite(self.salaries), "1\u202f235 salariés")
        self.assertEqual(T.exemple_unite(self.kwh), "1\u202f235 kWh")
        self.eff.decimales = 2
        self.eff.save(update_fields=["decimales"])
        self.eff.refresh_from_db()
        self.assertEqual(self.eff.decimales, 0)
        self.nrj.unite = self.salaries  # unité changée seule : les décimales suivent
        self.nrj.save(update_fields=["unite"])
        self.nrj.refresh_from_db()
        self.assertEqual(self.nrj.decimales, 0)

    def test_oui_non_et_liste(self):
        self.assertEqual(T.valeur(self.r(texte="Oui"), self.pol), "Oui")
        self.assertEqual(T.valeur(self.r(texte=""), self.pol), "–")
        self.assertEqual(T.valeur(self.r(texte="Oui : 2 · Non : 1", valeur=D(3)), self.pol), "Oui : 2 · Non : 1")
        self.assertEqual(T.valeur(self.r(texte="ISO 14001"), self.cert), "ISO 14001")
        self.assertEqual(self.pol.reponse_affichee("Oui : 2 · Non : 1", "en"), "Yes : 2 · No : 1")
        self.assertEqual(self.pol.reponse_affichee("Non", "en"), "No")
        self.assertEqual(self.pol.reponse_affichee("Peut-être : 1", "en"), "Peut-être : 1")  # inconnue : telle quelle

    def test_formater_une_valeur_brute(self):
        self.assertEqual(T.formater(None, self.nrj), "manquant")
        self.assertEqual(T.formater(NA, self.nrj), "N/A")
        self.assertEqual(T.formater(D("12.34"), self.nrj), "12,3 kWh")
        self.assertEqual(T.formater(D("12.34"), self.nrj, avec_unite=False), "12,3")
        self.assertEqual(T.formater(D("0.5"), self.tx), "50,0\u202f%")
        self.assertEqual(T.formater(Decompte({"Non": 1, "Oui": 2}), self.pol), "Oui : 2 · Non : 1")
        self.assertEqual(T.formater("Oui", self.pol), "Oui")
        self.assertEqual(self.tx.symbole, "%")
        self.assertEqual(self.nrj.symbole, "kWh")
        self.assertEqual(KPI(code="Z", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY).symbole, "")


class LectureSaisieTests(AvecKpi):
    def test_nombre(self):
        self.assertEqual(S.lire_nombre("1 234,5", self.nrj), D("1234.5"))
        self.assertEqual(S.lire_nombre(" 1\xa0234.5 ", self.nrj), D("1234.5"))
        self.assertEqual(S.lire_nombre("-12", self.nrj), D(-12))
        self.assertIsNone(S.lire_nombre("", self.nrj))
        self.assertIsNone(S.lire_nombre(None, self.nrj))
        self.assertIsNone(S.lire_nombre("%", self.nrj))
        with self.assertRaises(ValidationError):  # unité entière (comptage) : décimale refusée 
            S.lire_nombre("12,5", self.eff)
        self.assertEqual(S.lire_nombre("12", self.eff), D("12"))
        self.assertEqual(S.lire_nombre("999999999999999", self.nrj), D("999999999999999"))
        for mauvais in ("abc", "1,2,3", "NaN", "Infinity", "1000000000000000", "-1000000000000000"):
            with self.assertRaises(ValidationError, msg=mauvais):
                S.lire_nombre(mauvais, self.nrj)

    def test_pourcentage_saisi_sur_100_stocke_en_fraction(self):
        self.assertEqual(S.lire_nombre("35", self.tx), D("0.35"))
        self.assertEqual(S.lire_nombre("12,5 %", self.tx), D("0.125"))
        self.assertEqual(S.lire_nombre("0", self.tx), D(0))
        self.assertEqual(S.lire_nombre("100", self.tx), D(1))
        self.assertEqual(S.lire_nombre("0,35", self.tx), D("0.0035"))  # une fraction saisie est lue sur 100
        for hors in ("100,01", "-1", "150"):
            with self.assertRaises(ValidationError, msg=hors):
                S.lire_nombre(hors, self.tx)

    def test_valeur_rendue_au_champ_de_saisie(self):
        self.assertEqual(S.valeur_pour_saisie(None, self.nrj), "")
        self.assertEqual(S.valeur_pour_saisie(self.r(), self.nrj), "")
        self.assertEqual(S.valeur_pour_saisie(self.r(valeur=D("1234.5000000000")), self.nrj), "1234,5")
        self.assertEqual(S.valeur_pour_saisie(self.r(valeur=D("1000")), self.nrj), "1000")  # pas « 1E+3 »
        self.assertEqual(S.valeur_pour_saisie(self.r(valeur=D("0.1250000000")), self.tx), "12,5")
        self.assertEqual(S.valeur_pour_saisie(self.r(valeur=D(1)), self.tx), "100")
        self.assertEqual(S.valeur_pour_saisie(self.r(texte="Oui"), self.pol), "Oui")
        # aller-retour saisie → stockage → champ
        for texte in ("35", "12,5", "0,01", "100"):
            v = S.lire_nombre(texte, self.tx)
            self.assertEqual(S.valeur_pour_saisie(self.r(valeur=v.quantize(D("1e-10"))), self.tx), texte)

    def test_oui_non(self):
        for texte in ("Oui", "oui", " OUI ", "yes", "o", "y", "vrai", "true", "1", "x", "Yes"):
            self.assertEqual(S.lire_reponse(texte, self.pol), (None, "Oui"), texte)
        for texte in ("Non", "no", "n", "faux", "false", "0", "No"):
            self.assertEqual(S.lire_reponse(texte, self.pol), (None, "Non"), texte)
        self.assertEqual(S.lire_reponse("", self.pol), (None, ""))
        self.assertEqual(S.lire_reponse(None, self.pol), (None, ""))
        with self.assertRaisesMessage(ValidationError, "Répondez « Oui » ou « Non »."):
            S.lire_reponse("Peut-être", self.pol)

    def test_liste(self):
        self.assertEqual(S.lire_reponse("ISO 14001", self.cert), (None, "ISO 14001"))
        self.assertEqual(S.lire_reponse("iso 14001", self.cert), (None, "ISO 14001"))
        with self.assertRaisesMessage(ValidationError, "Choisissez une des valeurs : ISO 14001, Aucune."):
            S.lire_reponse("ISO 9001", self.cert)

    def test_nombre_pour_un_kpi_numerique(self):
        self.assertEqual(S.lire_reponse("1,5", self.nrj), (D("1.5"), ""))
        self.assertEqual(S.lire_reponse("50", self.tx), (D("0.5"), ""))
