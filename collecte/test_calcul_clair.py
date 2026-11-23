"""Calculs écrits en clair : le nom des KPI à la place des codes, dans le catalogue, le contenu d'un
référentiel et la page d'un ensemble de la bibliothèque."""
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from referentiel import formule as F
from referentiel.models import Utilisateur

from . import paquets as P
from .aides_tests.bibliotheque_essai import BibliothequeEssai


class EnClairTests(SimpleTestCase):
    NOMS = {"A": "Électricité", "B": "Facteur du réseau"}

    def test_noms_et_signes(self):
        self.assertEqual(F.en_clair("[A] * [B] / 1000", self.NOMS), "Électricité × Facteur du réseau ÷ 1000")
        self.assertEqual(F.en_clair("([A]-[B])/[A]", self.NOMS), "(Électricité − Facteur du réseau) ÷ Électricité")

    def test_decalages(self):
        self.assertEqual(F.en_clair("[A@N-1] + [B @ P-1] + [A@2024]", self.NOMS, "exercice précédent", "période précédente"),
                         "Électricité (exercice précédent) + Facteur du réseau (période précédente) + Électricité (2024)")

    def test_code_inconnu_et_formule_illisible(self):
        self.assertEqual(F.en_clair("[X] + [A]", self.NOMS), "X + Électricité")  # code inconnu : laissé tel quel
        self.assertEqual(F.en_clair("", self.NOMS), "")
        self.assertEqual(F.en_clair("[A] ? [B]", self.NOMS), "")  # illisible : rien (signalée dans « Formules à corriger »)


class PagesTests(BibliothequeEssai, TestCase):
    def setUp(self):
        self.client.force_login(Utilisateur.objects.create(username="adm", email="adm@exemple.test", role=Utilisateur.Role.ADMIN))
        P.appliquer(None, P.analyser(P.fourni("socle_ges.json").paquet, fourni=True))

    def test_catalogue_et_contenu(self):
        attendu = "Émissions de la combustion fixe + Émissions de la combustion mobile + Émissions fugitives"
        html = self.client.get(reverse("collecte:referentiel") + "?ref=SOCLE_GES").content.decode()
        self.assertIn('class="calcul-clair"', html)
        self.assertIn(attendu, html)
        self.assertIn('class="menu-deroulant menu-liens-kpi"', html)  # « Calculé avec » et « Sert à calculer » : listes en un clic
        self.assertIn(reverse("collecte:referentiel_kpi", args=["GES-S1-FIXE"]) + '" data-panneau', html)
        html = self.client.get(reverse("parametres:referentiel_contenu", args=["SOCLE_GES"])).content.decode()
        self.assertIn(attendu, html)

    def test_page_d_un_ensemble(self):
        html = self.client.get(reverse("parametres:installer_kpi", args=["SOCLE_ENERGIE"])).content.decode()
        self.assertIn('class="entete-coche"', html)  # en-tête de colonnes, comme le catalogue
        self.assertIn("Consommation totale d", html)
        self.assertIn("Fioul consommé × Contenu énergétique du fioul", html)
        self.assertIn("déjà chez vous", html)  # les KPI communs avec « Gaz à effet de serre », déjà installé
        self.assertNotIn("Calculé à partir de", html)


class ChoisirLesKpiTests(BibliothequeEssai, TestCase):
    """Créer son référentiel : cocher des KPI existants, repris sous des thèmes de même nom, sans copie."""

    def setUp(self):
        self.client.force_login(Utilisateur.objects.create(username="adm", email="adm@exemple.test", role=Utilisateur.Role.ADMIN))
        P.appliquer(None, P.analyser(P.fourni("socle_social.json").paquet, fourni=True))

    def test_creer_cocher_ajouter(self):
        from referentiel.models import KPI, ElementReferentiel, Referentiel

        rep = self.client.post(reverse("parametres:referentiel_nouveau"), {"nom": "Tableau de bord", "frequence": "annee", "composer": "1"})
        cible = Referentiel.objects.get(nom="Tableau de bord")
        url = reverse("parametres:referentiel_choisir", args=[cible.code])
        self.assertRedirects(rep, url)  # « Créer et choisir les KPI » mène à la page à cocher
        html = self.client.get(url).content.decode()
        for texte in ("Choisir les KPI", "Ranger en thèmes", "Attribuer et ouvrir une campagne", "Aucun KPI n", 'class="entete-coche"',
                      'class="calcul-clair"', 'value="SOC-EFFECTIF"'):
            self.assertIn(texte, html)
        avant = KPI.objects.count()
        rep = self.client.post(url, {"source": "SOCLE_SOCIAL", "kpi": ["SOC-EFFECTIF", "SOC-PART-FEMMES"]})
        self.assertRedirects(rep, reverse("parametres:referentiel_contenu", args=[cible.code]) + "?choisis=1")
        elements = ElementReferentiel.objects.filter(referentiel=cible).select_related("theme")
        self.assertEqual({e.kpi_id for e in elements}, {"SOC-EFFECTIF", "SOC-PART-FEMMES"})
        self.assertEqual({e.theme.nom for e in elements}, {"Effectifs"})  # le thème d'origine est repris
        self.assertEqual(KPI.objects.count(), avant)  # aucun KPI recopié
        html = self.client.get(reverse("parametres:referentiel_contenu", args=[cible.code])).content.decode()
        self.assertIn("Et ensuite ?", html)
        self.assertIn(reverse("collecte:admin_attributions"), html)
        html = self.client.get(url + "?source=SOCLE_SOCIAL").content.decode()
        self.assertIn("déjà dedans", html)  # un KPI déjà repris est coché et grisé
        rep = self.client.post(url, {"source": "SOCLE_SOCIAL", "kpi": ["SOC-EFFECTIF"]})  # rien de nouveau : on reste sur la page
        self.assertRedirects(rep, url + "?source=SOCLE_SOCIAL")

    def test_reserve_a_l_administrateur(self):
        from referentiel.models import Referentiel

        r = Referentiel.objects.create(code="TB", nom="TB")
        self.client.force_login(Utilisateur.objects.create(username="c", email="c@exemple.test", role=Utilisateur.Role.CONTRIBUTEUR))
        self.assertEqual(self.client.get(reverse("parametres:referentiel_choisir", args=[r.code])).status_code, 403)

    def test_page_referentiels_trois_facons(self):
        html = self.client.get(reverse("parametres:referentiels")).content.decode()
        for texte in ("Cocher des KPI existants", "Remplir le modèle Excel", "Partir de zéro", reverse("parametres:paquet_modele")):
            self.assertIn(texte, html)
