"""Monnaie de référence d'un espace (``parametres/monnaies.py``) : les modèles de la bibliothèque
écrits en euros prennent, à l'installation et à la mise à jour, les mêmes unités dans la monnaie de référence (« M€ »
devient « M$ ») ; l'euro par défaut ne change rien ; un KPI déjà dans l'installation garde son unité, qu'il ait des
valeurs ou non, sans que la ligne de la mise à jour soit rejetée ; changer le réglage après coup ne touche à aucun KPI ; le contrôle des
unités mal rangées ne prend pas une unité en dollars pour une erreur. Aucune valeur n'est jamais convertie."""
from decimal import Decimal

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from parametres import monnaies as MO
from parametres.models import Instance, Unite
from referentiel.models import KPI, Niveau, Organisation, Referentiel, Utilisateur

from . import paquets as P
from .models import Campagne, Reponse


def regler(code):
    i = Instance.courante()
    i.monnaie = code
    i.save()


def installer(fichier="vs_base.json"):
    """Installe tout le modèle (comme la démo) ; renvoie le référentiel."""
    p = P.fourni(fichier).paquet
    a = P.analyser(p, fourni=True)
    assert not a.erreur, a.erreur
    P.appliquer(None, a, sans_recalcul=True)
    return Referentiel.objects.get(identifiant=p.referentiel["identifiant"])


class FonctionsTests(SimpleTestCase):
    def test_forme_et_monnaie_d_une_unite(self):
        self.assertEqual(MO.forme("M$"), ("USD", "M€"))
        self.assertEqual(MO.forme("CHF/h"), ("CHF", "€/h"))
        self.assertEqual(MO.forme("MEUR"), ("EUR", "M€"))  # code ISO aussi
        self.assertEqual(MO.forme("kg"), (None, "kg"))
        self.assertIsNone(MO.monnaie_du_symbole("tCO2e/M€"))  # intensité : pas un montant
        self.assertTrue(MO.variante("€/h", "$/h"))
        self.assertFalse(MO.variante("€/h", "h"))
        self.assertFalse(MO.variante("€", "€"))
        self.assertTrue(MO.autre_monnaie_seule("M€", "M$"))
        self.assertFalse(MO.autre_monnaie_seule("M€", "$"))  # autre échelle : pas seulement la monnaie
        self.assertTrue(MO.dans_la_monnaie("MUSD", "M€", "USD"))
        self.assertFalse(MO.dans_la_monnaie("k$", "M€", "USD"))

    def test_liste_fermee(self):
        self.assertEqual(MO.depuis_texte("usd"), "USD")
        self.assertEqual(MO.depuis_texte("£"), "GBP")
        self.assertIsNone(MO.depuis_texte("XYZ"))
        self.assertEqual(MO.CODES[0], "EUR")
        self.assertEqual(len(set(MO.SYMBOLES.values())), len(MO.MONNAIES))  # un symbole, une monnaie


class AdapterPaquetTests(TestCase):
    def test_euro_ne_change_rien(self):
        """Tous les modèles de la bibliothèque, en euros (défaut) : paquet identique au fichier livré."""
        for f in P.bibliotheque():
            brut = P.depuis_json((P.BIBLIOTHEQUE / f.nom_fichier).read_text(encoding="utf-8"))
            with self.subTest(modele=f.nom_fichier):
                self.assertEqual(P.vers_json(f.paquet), P.vers_json(brut))
                self.assertEqual((f.paquet.monnaie, f.paquet.unites_monnaie), ("EUR", {}))

    def test_dollars(self):
        regler("USD")
        p = P.fourni("vs_base.json").paquet
        unites = {u["code"]: u for u in p.unites}
        self.assertNotIn("€", " ".join(unites))
        # libellé dans les sept langues de l'interface (avant : français et anglais seulement)
        self.assertEqual({lg: unites["M$"]["libelle"][lg] for lg in ("fr", "en")}, {"fr": "million de USD", "en": "million USD"})
        self.assertEqual(len(unites["M$"]["libelle"]), 7)
        self.assertEqual(unites["$"]["libelle"]["en"], "US dollar")
        self.assertEqual(unites["$/h"]["symbole"], {"fr": "$/h", "en": "$/h"})
        kpis = {k["code"]: k["unite"] for k in p.kpis}
        self.assertEqual((kpis["ECO-CA"], kpis["SOC-REMU-H-FEMMES"], kpis["GOV-AMENDES"]), ("M$", "$/h", "$"))
        self.assertEqual(p.unites_monnaie, {"M$": "M€", "$": "€", "$/h": "€/h"})


class InstallationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = Utilisateur.objects.create_user("admin", "admin@exemple.test", "x", role=Utilisateur.Role.ADMIN)

    def test_installation_en_euros_par_defaut(self):
        installer()
        self.assertEqual(KPI.objects.get(pk="ECO-CA").unite.symbole, "M€")
        self.assertEqual(KPI.objects.get(pk="SOC-REMU-H-HOMMES").unite.symbole, "€/h")

    def test_installation_en_francs_suisses(self):
        regler("CHF")
        installer()
        ca, h = KPI.objects.get(pk="ECO-CA").unite, KPI.objects.get(pk="SOC-REMU-H-HOMMES").unite
        self.assertEqual((ca.symbole, h.symbole), ("MCHF", "CHF/h"))
        self.assertEqual(ca.famille, "Monnaie")
        self.assertEqual(ca.libelle, "million de CHF")
        self.assertEqual(ca.traductions["en"]["libelle"], "million CHF")
        self.assertFalse(KPI.objects.filter(unite__symbole__contains="€").exists())
        self.assertTrue(Unite.objects.filter(symbole="CHF").exists())

    def test_reglage_change_ensuite_ne_touche_a_rien(self):
        installer()
        regler("USD")
        self.assertEqual(KPI.objects.get(pk="ECO-CA").unite.symbole, "M€")
        self.assertEqual(KPI.objects.get(pk="GOV-AMENDES").unite.symbole, "€")

    def test_mise_a_jour_garde_l_unite_d_un_kpi_qui_a_des_valeurs(self):
        ref = installer()
        org = Organisation.objects.create(nom="Site 1", niveau_id=Niveau.SITE)
        c = Campagne.objects.create(exercice=2024, statut=Campagne.Statut.CLOTUREE)
        Reponse.objects.create(periode=c.periode, kpi_id="GOV-AMENDES", organisation=org, valeur=Decimal(1200),
                               origine=Reponse.Origine.SAISIE, statut=Reponse.Statut.VALIDE)
        regler("USD")
        f = P.fourni("vs_base.json")
        a, _ = P.analyser_installation(f.paquet, [k["code"] for k in f.paquet.kpis], existant=ref, nouvelle_version=True)
        lignes = {l.code: l for l in a.kpis}
        self.assertNotEqual(lignes["GOV-AMENDES"].statut, "rejet")  # la ligne n'est pas rejetée : seule l'unité reste
        self.assertIn("GOV-AMENDES", a.unites_gardees)
        self.assertIn("ECO-TOTAL-BILAN", a.unites_gardees)
        self.assertIn("Le KPI GOV-AMENDES garde son unité « € » : il existe déjà dans cet espace.", " ".join(a.avertissements))
        P.appliquer(self.admin, a)
        self.assertEqual(KPI.objects.get(pk="GOV-AMENDES").unite.symbole, "€")  # valeur jamais convertie : unité gardée
        self.assertEqual(Reponse.objects.get(kpi_id="GOV-AMENDES").valeur, Decimal(1200))
        # sans valeur, déjà dans l'installation : garde aussi son unité (seuls les KPI nouveaux prennent la monnaie)
        self.assertEqual(KPI.objects.get(pk="ECO-TOTAL-BILAN").unite.symbole, "€")

    def test_fichier_importe_reste_refuse(self):
        """Hors de la bibliothèque (fichier déposé), un changement d'unité d'un KPI qui a des valeurs reste refusé, même
        s'il ne change que la monnaie : c'est un choix de l'administrateur, pas le réglage de l'espace."""
        installer()
        org = Organisation.objects.create(nom="Site 1", niveau_id=Niveau.SITE)
        c = Campagne.objects.create(exercice=2024, statut=Campagne.Statut.CLOTUREE)
        Reponse.objects.create(periode=c.periode, kpi_id="GOV-AMENDES", organisation=org, valeur=Decimal(5),
                               origine=Reponse.Origine.SAISIE, statut=Reponse.Statut.VALIDE)
        p = MO.adapter_paquet(P.depuis_json((P.BIBLIOTHEQUE / "vs_base.json").read_text(encoding="utf-8")), "USD")
        a = P.analyser(p, {"kpi:GOV-AMENDES": "mettre_a_jour"})
        self.assertEqual({l.code: l for l in a.kpis}["GOV-AMENDES"].statut, "rejet")

    def test_ecrans_de_l_installation_le_disent(self):
        regler("USD")
        self.client.force_login(self.admin)
        rep = self.client.get(reverse("parametres:installer_kpi", args=["VS_BASE"]))
        self.assertContains(rep, "Les montants sont dans la monnaie de référence de cet espace : dollar américain ($, USD). "
                                 "L'outil ne convertit aucune valeur.")
        self.assertContains(rep, "M$")
        self.assertContains(rep, reverse("parametres:referentiel") + "?section=unites#monnaie-reference")
        codes = [k["code"] for k in P.fourni("vs_base.json").paquet.kpis]
        self.client.post(reverse("parametres:installer_kpi", args=["VS_BASE"]), {"action": "continuer", "kpi": codes})
        rep = self.client.get(reverse("parametres:installer_resume", args=["VS_BASE"]))
        self.assertContains(rep, "dollar américain ($, USD)")

    def test_modele_sans_montant_n_en_parle_pas(self):
        self.client.force_login(self.admin)
        rep = self.client.get(reverse("parametres:installer_kpi", args=["ESRS_E2"]))
        self.assertEqual(rep.status_code, 200)
        self.assertNotContains(rep, "monnaie de référence de cet espace")


class UnitesMalRangeesTests(TestCase):
    def test_unite_en_dollars_d_un_modele_n_est_pas_douteuse(self):
        from . import unites_mal_rapprochees as UM

        regler("USD")
        installer()
        douteux = {c.kpi.code for c in UM.douteux()}
        self.assertFalse(douteux & {"ECO-CA", "SOC-REMU-H-HOMMES", "SOC-REMU-H-FEMMES", "GOV-AMENDES"}, douteux)
