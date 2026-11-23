"""Revue des pages : catalogue des KPI et fiche KPI. Onglet « Référentiels et KPI », « + » d'une ligne
(ajouter un KPI au-dessus ou en dessous), en-tête de référentiel au-dessus des thèmes, compteurs dans le filtre de type,
code proposé tout seul, proposition de traduction après la création, fiche en groupes titrés."""
from django.test import TestCase
from django.urls import reverse

from parametres.models import Langue
from referentiel.composition import composer
from referentiel.models import KPI, ElementReferentiel, Niveau, Organisation, Referentiel, Utilisateur

from . import reglages as R
from collecte.outils_tests import html_de

FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}


class Base(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)

        def kpi(code, libelle, **autres):
            return KPI.objects.create(code=code, libelle=libelle, type_saisie_id="Saisi", granularite_id=Niveau.ENTITY, **autres)
        self.a, self.b, self.c = kpi("AAA", "Premier"), kpi("BBB", "Deuxième"), kpi("CCC", "Troisième")
        self.hors = kpi("HORS", "Hors référentiel")
        self.rse = Referentiel.objects.create(code="RSE", nom="Reporting", ordre=1, couleur="#1F5FAD")
        self.nrg = Referentiel.objects.create(code="ENERGIE", nom="Énergie", ordre=2, couleur="#E07A1F")
        composer({"AAA": ["Social"], "BBB": ["Social"]}, self.rse)
        composer({"CCC": ["Consommations"]}, self.nrg)
        self.client.force_login(self.admin)

    def nouveau(self, requete="", **champs):
        """Poste la fiche d'un nouveau KPI, pré-remplie comme l'affiche la page (place, code proposé)."""
        url = reverse("collecte:referentiel_kpi_nouveau")
        form = R.KPIForm(instance=KPI())
        donnees = {n: form[n].value() for n in form.fields if form[n].value() not in (None, False, "")}
        donnees.update({"type_saisie": "Saisi", "granularite": Niveau.ENTITY, "nom__fr": "Nouveau"})
        donnees.update(champs)
        return self.client.post(url + requete, donnees, **FETCH).json()

    def ordre(self, ref, theme):
        return list(ElementReferentiel.objects.filter(referentiel=ref, theme__nom=theme).order_by("ordre").values_list("kpi_id", flat=True))


class OngletTests(Base):
    def test_onglet_referentiels_et_kpi(self):
        html = html_de(self.client, reverse("collecte:admin_accueil"))
        self.assertIn("Référentiels et KPI", html)  # onglet, vue d'ensemble et aide des rubriques
        html = html_de(self.client, reverse("collecte:referentiel"))
        self.assertIn(">Référentiels et KPI</a>", html)
        self.assertIn(">Référentiels</a>", html)  # le sous-onglet garde son nom


class CatalogueTests(Base):
    def test_entete_de_referentiel_au_dessus_des_themes(self):
        html = html_de(self.client, reverse("collecte:referentiel"))
        self.assertEqual(html.count('class="entete-referentiel"'), 3)  # Reporting, Énergie, hors référentiel
        self.assertLess(html.index('class="entete-referentiel"'), html.index('id="theme-0"'))
        self.assertNotIn("Reporting · Social", html)  # le thème ne répète plus le nom du référentiel
        self.assertIn("referentiel-sommaire", html)  # même regroupement dans le sommaire
        # un seul référentiel affiché : pas d'en-tête (il est déjà choisi dans les onglets)
        html = html_de(self.client, reverse("collecte:referentiel") + "?ref=RSE")
        self.assertNotIn('class="entete-referentiel"', html)

    def test_compteurs_dans_le_filtre_et_plus_de_cartes(self):
        self.hors.actif = False
        self.hors.save()
        html = html_de(self.client, reverse("collecte:referentiel"))
        self.assertNotIn("compteurs-ref", html)
        # les chiffres sont dans le panneau des champs de filtre (data-nb de chaque choix)
        self.assertIn('id="filtre-type" data-panneau-filtre data-multiple', html)
        self.assertRegex(html, r'data-nb="1"[^>]*>Actifs et inactifs</option>')

    def test_pas_de_tiret_devant_texte_redige(self):
        from parametres.models import TypeReponse
        redige = TypeReponse.objects.filter(format="texte").first()
        if redige is None:
            self.skipTest("pas de type « texte rédigé »")
        KPI.objects.filter(pk="AAA").update(type_reponse=redige, unite=None)
        html = html_de(self.client, reverse("collecte:referentiel"))
        self.assertIn(f'<td class="unite mq-m"><span class="discret">{redige}</span></td>', html)

    def test_bouton_ajouter_sur_les_lignes_d_un_referentiel(self):
        html = html_de(self.client, reverse("collecte:referentiel") + "?actifs=0")
        self.assertEqual(html.count("data-ajout-kpi="), 3)  # pas sur le KPI hors référentiel
        self.assertIn("dans=RSE&amp;voisin=AAA", html)
        self.assertIn("Ajouter un KPI au-dessus", html)
        self.assertIn("Ajouter un KPI en dessous", html)


class AjoutPresDUnKpiTests(Base):
    def test_fiche_preremplie_et_annonce(self):
        html = self.client.get(reverse("collecte:referentiel_kpi_nouveau") + "?dans=RSE&voisin=BBB&position=avant", **FETCH).json()["html"]
        theme = ElementReferentiel.objects.get(referentiel=self.rse, kpi=self.b).theme_id
        self.assertIn(f'<option value="RSE|{theme}" selected>', html)
        self.assertIn('name="voisin" value="BBB"', html)
        self.assertIn('name="position" value="avant"', html)
        self.assertIn("juste avant BBB", html)

    def test_au_dessus_et_en_dessous(self):
        theme = ElementReferentiel.objects.get(referentiel=self.rse, kpi=self.a).theme_id
        res = self.nouveau(code="AVANT", voisin="BBB", dans="RSE", position="avant", ajout_place=f"RSE|{theme}")
        self.assertTrue(res["ok"], res["html"])
        self.assertEqual(self.ordre(self.rse, "Social"), ["AAA", "AVANT", "BBB"])
        res = self.nouveau(code="APRES", voisin="AAA", dans="RSE", position="apres", ajout_place=f"RSE|{theme}")
        self.assertTrue(res["ok"], res["html"])
        self.assertEqual(self.ordre(self.rse, "Social"), ["AAA", "APRES", "AVANT", "BBB"])

    def test_autre_place_choisie_le_kpi_va_a_la_fin(self):
        theme = ElementReferentiel.objects.get(referentiel=self.nrg, kpi=self.c).theme_id
        res = self.nouveau(code="AILLEURS", voisin="AAA", dans="RSE", position="avant", ajout_place=f"ENERGIE|{theme}")
        self.assertTrue(res["ok"], res["html"])
        self.assertEqual(self.ordre(self.rse, "Social"), ["AAA", "BBB"])
        self.assertEqual(self.ordre(self.nrg, "Consommations"), ["CCC", "AILLEURS"])


class CodeProposeTests(Base):
    def test_code_propose_et_option_repliee(self):
        self.assertEqual(R.proposer_code(), "KPI0001")
        html = self.client.get(reverse("collecte:referentiel_kpi_nouveau"), **FETCH).json()["html"]
        self.assertIn('<details class="option-code">', html)  # repliée : modifier le code est une option
        self.assertIn("Code : KPI0001", html)
        self.assertIn('value="KPI0001"', html)

    def test_code_vide_ou_laisse_tel_quel(self):
        self.assertTrue(self.nouveau()["ok"])
        self.assertTrue(KPI.objects.filter(pk="KPI0001").exists())
        self.assertTrue(self.nouveau(code="")["ok"])  # champ vidé : le code suivant est pris
        self.assertTrue(KPI.objects.filter(pk="KPI0002").exists())
        KPI.objects.create(code="kpi0003", libelle="x", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY)
        self.assertEqual(R.proposer_code(), "KPI0004")  # à la casse près

    def test_code_ecrit_a_la_main_et_codes_existants_inchanges(self):
        self.assertTrue(self.nouveau(code="KP-2026")["ok"])
        self.assertTrue(KPI.objects.filter(pk="KP-2026").exists())
        res = self.nouveau(code="aaa")  # déjà pris, à la casse près : l'option s'ouvre sur l'erreur
        self.assertFalse(res["ok"])
        self.assertIn('<details class="option-code" open>', res["html"])
        self.assertIn(f'action="{reverse("collecte:referentiel_kpi_nouveau")}"', res["html"])  # toujours la fiche d'un nouveau KPI
        self.assertEqual(set(KPI.objects.values_list("code", flat=True)), {"AAA", "BBB", "CCC", "HORS", "KP-2026"})
        # un KPI existant : le code ne se modifie pas
        html = self.client.get(reverse("collecte:referentiel_kpi", args=["AAA"]), **FETCH).json()["html"]
        self.assertNotIn("option-code", html)


class TraductionProposeeTests(Base):
    def test_proposee_apres_la_creation_si_une_autre_langue_est_vide(self):
        if Langue.objects.filter(active=True).count() < 2:
            Langue.objects.filter(code="en").update(active=True)
        if Langue.objects.filter(active=True).count() < 2:
            self.skipTest("une seule langue active")
        res = self.nouveau()
        self.assertTrue(res["ok"], res["html"])
        self.assertIn("data-proposer-traduction", res["html"])
        self.assertIn('data-traduire-en="en"', res["html"])
        # plus proposée à l'ouverture suivante, ni quand tout est traduit dès la création
        html = self.client.get(reverse("collecte:referentiel_kpi", args=["KPI0001"]), **FETCH).json()["html"]
        self.assertNotIn("data-proposer-traduction", html)
        res = self.nouveau(nom__en="New")
        self.assertTrue(res["ok"], res["html"])
        self.assertNotIn("data-proposer-traduction", res["html"])
        # modification d'un KPI existant : jamais proposée
        html = self.client.get(reverse("collecte:referentiel_kpi", args=["AAA"]), **FETCH).json()["html"]
        self.assertNotIn("data-proposer-traduction", html)


class FicheTests(Base):
    def test_groupes_titres_et_textes_retires(self):
        html = self.client.get(reverse("collecte:referentiel_kpi", args=["AAA"]), **FETCH).json()["html"]
        for titre in ("Saisie ou calcul", "Réponse attendue", "Consolidation", "Valeur des niveaux supérieurs", "Valeur de l'année"):
            self.assertIn(titre, html)
        self.assertNotIn("rubriques réglées dans", html)
        self.assertNotIn("propres à votre structure", html)
        self.assertNotIn("Dans le temps", html)
        self.assertNotIn("cartes-choix", html)  # une seule façon de choisir : la liste de choix
        self.assertEqual(html.count('class="liste-choix"'), 3)
        self.assertIn("section=types-saisie", html)  # les types (« Facteur d'émission »…) se règlent dans l'outil
        # les réglages restent tous là
        for nom in ("type_saisie", "granularite", "type_reponse", "unite", "decimales", "methode_agregation", "saisie_au_dessus",
                    "agregation_temps", "preuve_obligatoire", "actif", "confidentialite", "formule", "na_compte_zero"):
            self.assertIn(f'name="{nom}"', html)
