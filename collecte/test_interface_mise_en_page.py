"""Uniformisation de l'interface, lot 3 : structure des pages, et ménage de la feuille de style.

1. Barre d'enregistrement : une seule (.barre-enregistrement), collante quand le formulaire dépasse l'écran.
2. Choix d'une option : puce ou carte, une seule façon de montrer l'option choisie (bord principal, fond teinté plein).
3. Introduction de page en un seul style (.intro-page) ; deux marges de carte ; tableau encadré, en-têtes en 13 px.
4. Interrupteur si le réglage s'applique tout de suite, case à cocher dans un formulaire ; un seul menu ; le sélecteur
   d'organisation de la Saisie dans le filtre de la Visualisation.
5. Aucune classe de outil.css absente des gabarits, des .py et des .js (qa/css_orphelins.py)."""
import importlib.util
import re
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from collecte.models import Utilisateur
from collecte.outils_tests import script_des_pages, html_de

RACINE = Path(__file__).resolve().parent.parent
CSS = re.sub(r"/\*.*?\*/", "", (RACINE / "static/css/outil.css").read_text(encoding="utf-8"), flags=re.S)  # sans les commentaires
GABARITS = [p for dossier in ("collecte", "parametres", "espaces", "templates") for p in (RACINE / dossier).rglob("*.html")]


def regles_css(selecteur):
    """Déclarations des règles dont l'un des sélecteurs est exactement ``selecteur``."""
    return [m.group(2) for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", CSS)
            if selecteur in [x.strip() for x in m.group(1).split(",")]]


def gabarit(chemin):
    return (RACINE / chemin).read_text(encoding="utf-8")


def absent_partout(test, noms):
    for nom in noms:
        test.assertIsNone(re.search(r"(?<![\w-])" + re.escape(nom) + r"(?![\w-])", CSS), f"{nom} encore dans outil.css")
        for p in GABARITS:
            test.assertIsNone(re.search(r"(?<![\w-])" + re.escape(nom) + r"(?![\w-])", p.read_text(encoding="utf-8")), f"{nom} dans {p.name}")


class BarreEnregistrementTests(TestCase):
    ANCIENS = ("pied-export", "pied-collant", "pied-apercu", "pied-reprise", "pied-form-liste", "pied-cocher",
               "pied-installation", "actions-formulaire", "actions-restauration", "message-pied")

    def test_les_anciens_pieds_de_formulaire_ont_disparu(self):
        absent_partout(self, self.ANCIENS)

    def test_une_seule_regle_collante_meme_habillage_partout(self):
        (regle,) = regles_css(".barre-enregistrement.collante")
        for attendu in ("position: sticky", "bottom: 0", "background: var(--surface)", "border: 1px solid var(--bord)",
                        "border-radius: var(--coin-carte)"):
            self.assertIn(attendu, regle)
        self.assertNotIn("sticky", regles_css(".barre-enregistrement")[0])  # sans modificateur : sous les champs
        self.assertIn("margin: 0 0 0 auto", regles_css(".barre-enregistrement .etat-barre")[0])  # message d'état à droite

    def test_bouton_principal_en_premier_puis_annuler(self):
        """Dans chaque barre : le premier bouton est le principal (jamais « secondaire »), « Annuler » est un bouton
        secondaire, jamais un lien nu."""
        vues = 0
        for p in GABARITS:
            html = p.read_text(encoding="utf-8")
            for m in re.finditer(r'class="barre-enregistrement[^"]*"[^>]*>(.*?)</(?:div|form)>', html, flags=re.S):
                vues += 1
                corps = re.sub(r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}|\{#.*?#\}", "", m.group(1), flags=re.S)
                premier = re.search(r"<(button|a)\b[^>]*>", corps)
                self.assertIsNotNone(premier, p.name)
                self.assertNotIn("secondaire", premier.group(0), f"{p.name} : le bouton principal vient en premier")
                self.assertNotIn('class="lien"', premier.group(0), p.name)
                for lien in re.finditer(r"<a\b[^>]*>\s*\{% libelle \"(commun|espaces\.nouveau)\.annuler\" %\}", corps):
                    self.assertIn("bouton secondaire", lien.group(0), f"{p.name} : « Annuler » est un bouton secondaire")
        self.assertGreaterEqual(vues, 30)

    def test_formulaire_long_collant_formulaire_court_sous_les_champs(self):
        for chemin in ("collecte/templates/collecte/_kpi_fiche.html", "collecte/templates/collecte/administration/_compte.html",
                       "collecte/templates/collecte/administration/_organisation.html", "parametres/templates/parametres/_identite.html",
                       "parametres/templates/parametres/langues.html", "collecte/templates/collecte/echanges/exporter.html",
                       "parametres/templates/parametres/installer_kpi.html"):
            self.assertIn('class="barre-enregistrement collante"', gabarit(chemin), chemin)
        for chemin in ("collecte/templates/collecte/mon_compte.html", "collecte/templates/collecte/administration/_remplacer.html",
                       "parametres/templates/parametres/referentiel_copier.html", "espaces/templates/espaces/nouveau.html"):
            html = gabarit(chemin)
            self.assertIn('class="barre-enregistrement"', html, chemin)
            self.assertNotIn("collante", html, chemin)

    def test_hebergement_le_bouton_passe_sous_les_champs(self):
        html = gabarit("parametres/templates/parametres/hebergement.html")
        self.assertEqual(html.count('<div class="barre-enregistrement"><button type="submit" name="action" value="reglage'), 5)  # corbeille, historique des connexions, conservation des preuves, gros exports, sauvegardes

    def test_installation_meme_ordre_aux_deux_etapes(self):
        for chemin, action in (("parametres/templates/parametres/installer_kpi.html", 'value="continuer"'),
                               ("parametres/templates/parametres/installer_resume.html", 'value="installer"')):
            html = gabarit(chemin)
            barre = html[html.index('class="barre-enregistrement collante"'):]
            self.assertLess(barre.index(action), barre.index("commun.annuler"), chemin)


class ChoixOptionTests(TestCase):
    CHOISIES = (".puce input:checked + span", ".puce-reponse input:checked + span", ".puce-catalogue:has(input:checked)",
                ".choix-forme:has(input:checked)", ".carte-choix:has(input:checked)", ".carte-role:has(input:checked)",
                ".palette-choix:has(input:checked)", ".modele-niveaux:has(input:checked)", ".choix-ligne:has(input:checked)",
                ".choix-theme button.choisi")

    def test_une_seule_regle_pour_l_option_choisie(self):
        (commune,) = regles_css(self.CHOISIES[0])[:1]
        self.assertIn("border-color: var(--principale-bord)", commune)
        self.assertIn("background: var(--principale-teinte)", commune)  # fond teinté PLEIN : la carte choisie n'est pas « transparente »
        for sel in self.CHOISIES:
            regles = regles_css(sel)
            self.assertIn(commune, regles, sel)
            for r in regles:  # aucune règle propre ne redonne un fond, un bord ou un halo à l'option choisie
                if r is not commune and r != commune:
                    self.assertNotIn("background", r, sel)
                    self.assertNotIn("border-color", r, sel)
                    self.assertNotIn("0 0 0 3px", r, sel)

    def test_jamais_la_couleur_principale_pleine_ni_un_fond_pale(self):
        for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", CSS):
            if re.search(r"(carte-choix|carte-role|palette-choix|puce-reponse|puce-catalogue|choix-forme|modele-niveaux|choix-ligne)[^,{]*:checked", m.group(1)):
                self.assertNotIn("background: var(--principale);", m.group(2), m.group(1))
                self.assertNotIn("background: var(--principale-pale)", m.group(2), m.group(1))
                self.assertNotIn("background: var(--surface)", m.group(2), m.group(1))


class TitresCartesTableauxTests(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        self.client.force_login(self.admin)

    def test_une_seule_introduction_de_page(self):
        absent_partout(self, ("intro-rubrique", "chapeau-installation", "chapeau-donnees", "intro-espaces"))
        (regle,) = regles_css(".intro-page")
        self.assertIn("font-size: var(--taille-corps)", regle)  # taille normale
        self.assertIn("max-width: 80ch", regle)

    def test_administration_sans_introduction_qui_repete_les_onglets(self):
        # tri des textes : la phrase qui répétait le nom des onglets est retirée de la vue d'ensemble
        html = html_de(self.client, reverse("collecte:admin_accueil"))
        self.assertIn('id="rubriques-admin"', html)
        self.assertNotIn('class="intro-page"', html)
        self.assertNotIn("discret m-0 mt-4", gabarit("collecte/templates/collecte/administration/_nav.html"))
        autre = html_de(self.client, reverse("collecte:admin_comptes"))
        self.assertNotIn('class="intro-page"', autre)  # plus répétée en petit sous le titre de chaque rubrique

    def test_coherence_et_regles_introduction_hors_de_l_entete(self):
        for chemin in ("collecte/templates/collecte/coherence/liste.html", "collecte/templates/collecte/coherence/regles.html",
                       "collecte/templates/collecte/forcages.html"):
            html = gabarit(chemin)
            self.assertIn('<p class="intro-page">', html, chemin)
            self.assertNotIn("discret m-0 mt-4", html, chemin)

    def test_deux_marges_de_carte(self):
        racine = re.search(r":root\s*\{[^}]*\}", CSS).group(0)
        self.assertIn("--marge-carte: 16px 20px", racine)
        self.assertIn("--marge-bloc: 12px 14px", racine)
        for sel, marge in ((".carte", "carte"), ("section.bloc", "carte"), (".page-cellule", "carte"), ("dialog.confirmation", "carte"),
                           (".carte-role", "bloc"), (".carte-choix", "bloc"), (".tuile", "bloc"), (".carte-langue", "bloc"),
                           (".zone-danger", "bloc"), (".volet-it", "bloc")):
            self.assertTrue(any(f"padding: var(--marge-{marge})" in r for r in regles_css(sel)), sel)

    def test_tableau_encadre_et_en_tetes_en_13_px(self):
        (cadre,) = regles_css("table.carte-table")
        self.assertIn("border: 1px solid var(--bord)", cadre)
        for sel in ("table.tdb", "table.table-mep"):
            self.assertEqual(regles_css(sel)[0], cadre, sel)  # le même cadre, dans la même règle
        self.assertIn("font-size: var(--taille-petite)", regles_css("thead th")[0])
        for sel in (".arbre-orgs thead th", ".table-comptes thead th", ".table-alertes thead th", ".grille-attr thead th"):
            for r in regles_css(sel):
                self.assertNotIn("font-size", r, sel)  # plus de 12 px : la taille commune


class InterrupteursMenusSelecteurTests(TestCase):
    """Les 8 tests lisent seulement (GET, gabarits, feuille de style) : la démo n'est chargée qu'une fois pour la classe."""

    @classmethod
    def setUpTestData(cls):
        call_command("load_demo", "--language", "fr", verbosity=0)
        cls.admin = Utilisateur.objects.get(username="admin")

    def setUp(self):
        self.client.force_login(self.admin)

    def test_case_a_cocher_dans_un_formulaire_avec_enregistrer(self):
        for chemin in ("collecte/templates/collecte/_kpi_fiche.html", "collecte/templates/collecte/administration/_compte.html",
                       "collecte/templates/collecte/administration/_organisation.html", "collecte/templates/collecte/coherence/_regle.html",
                       "collecte/templates/collecte/administration/_remplacer.html", "parametres/templates/parametres/referentiel_reglages.html",
                       "parametres/templates/parametres/hebergement.html"):
            html = gabarit(chemin)
            self.assertNotIn("interrupteur", html, chemin)
            self.assertNotIn("glissiere", html, chemin)
            self.assertIn('<label class="case-option"', html, chemin)

    def test_interrupteur_garde_pour_ce_qui_s_applique_tout_de_suite(self):
        self.assertIn('class="bascule-statut', gabarit("collecte/templates/collecte/coherence/regles.html"))  # pause d'une règle
        self.assertIn("na-interrupteur", gabarit("collecte/templates/collecte/_panneau.html"))
        for r in regles_css("button.bascule-statut .glissiere"):  # le même interrupteur : ni largeur ni hauteur propres
            self.assertNotIn("width", r)

    def test_un_seul_menu(self):
        absent_partout(self, ("menu-theme-liste",))
        html = gabarit("parametres/templates/parametres/_contenu_theme.html")
        self.assertIn('<details class="menu-deroulant menu-theme"><summary class="bouton-menu"', html)
        menu = html[html.index('class="menu-liste"'):html.index("</details>")]
        self.assertLess(menu.index("data-renommer"), menu.index("theme_supprimer"))  # la suppression en dernier
        self.assertIn('{% icone "supprimer" %}', menu)

    def test_visualisation_filtre_organisation_avec_le_selecteur_de_la_saisie(self):
        html = html_de(self.client, reverse("collecte:visu"))
        filtre = html[html.index('id="l-org"'):html.index('data-filtre-optionnel="ref"')]
        self.assertIn('class="selecteur-org selecteur-champ" data-selecteur-champ hidden', filtre)
        self.assertIn('<select name="org" id="f-org" data-selecteur-repli>', filtre)  # reste le champ envoyé (et le repli sans script)

        self.assertIn('class="niveau niveau-', filtre)  # étiquettes de niveau, comme dans la Saisie
        self.assertRegex(filtre, r'<option value="\d+" selected>')
        # un script qui change la liste prévient le sélecteur
        self.assertIn('dispatchEvent(new Event("selecteur:maj"))', (RACINE / "static/js/visualisation.js").read_text(encoding="utf-8"))
        self.assertIn('repli.addEventListener("selecteur:maj"', script_des_pages())

    def test_import_le_selecteur_garde_toutes_les_organisations(self):
        html = html_de(self.client, reverse("collecte:echanges_importer"))
        self.assertIn('<select name="org" data-selecteur-repli aria-label=', html)
        self.assertIn('<option value="" selected>', html)

    def test_visualisation_une_seule_action_principale(self):
        html = html_de(self.client, reverse("collecte:visu"))
        self.assertIn('class="bouton secondaire compact nouvelle-vue"', html)
        self.assertNotIn('class="bouton nouvelle-vue"', html)

    def test_organisations_colonne_etat_assez_large_pour_inactive(self):
        self.assertIn('<col class="mq-xs l-120"><col class="l-150">', gabarit("collecte/templates/collecte/administration/organisations.html"))

    def test_entete_referentiel_boutons_compacts(self):
        html = gabarit("parametres/templates/parametres/_entete_referentiel.html")
        actions = html[html.index('class="actions-referentiel"'):html.index("</header>")]
        self.assertEqual(actions.count("compact"), 4)
        self.assertNotRegex(actions, r'class="(bouton )?secondaire"')


class MenageTests(TestCase):
    def test_aucune_classe_orpheline_dans_la_feuille_de_style(self):
        spec = importlib.util.spec_from_file_location("css_orphelins", RACINE / "qa" / "css_orphelins.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _classes, orphelines, _dynamiques = module.analyser()
        self.assertEqual(sorted(orphelines), [])

    def test_styles_morts_retires(self):
        for nom in ("petit-bouton", "carte-fourni", "preset", "filtre-elements", "helptext", "retirer-element", "zero-mep",
                    "etapes-fichier", "bandeau-comptes", "table-referentiels", "colonne-bibliotheque", "vues-saisie"):
            self.assertIsNone(re.search(r"\." + re.escape(nom) + r"(?![\w-])", CSS), nom)

    def test_obligatoire_et_facultatif_definis_une_fois(self):
        self.assertEqual(len(regles_css(".obligatoire")), 1)
        self.assertEqual(len(regles_css(".facultatif")), 2)  # la forme commune des étiquettes, et une seule teinte
