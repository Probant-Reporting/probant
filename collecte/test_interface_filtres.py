"""Filtres et design, un seul modèle (retenu sur maquettes ; DESIGN.md, « Filters »).

1. Une barre de filtres (.barre-filtres) : recherche, champs avec libellé (select[data-panneau-filtre]), compteur et
   « Effacer les filtres » ; plus de pastille grise pour filtrer.
2. Cohérence et Historique : plusieurs valeurs à la fois, appliquées par le serveur (?controle=a&controle=b).
3. Deux niveaux d'onglets au plus ; onglets soulignés au Tableau de bord et dans la Visualisation.
4. En-tête de tableau teinté partout ; chevron fin des listes ; cases de 18 px.
5. Introductions qui répétaient l'écran retirées ; explications longues repliées.
6. Page vide : un seul composant (_vide.html), sans barre de filtres au-dessus."""
import re
from pathlib import Path

from django.test import TestCase
from django.urls import reverse

from parametres.libelles import libelle
from referentiel.models import KPI, Attribution, Niveau, Organisation, Utilisateur

from .models import Campagne, Journal
from .outils_tests import script_des_pages
from .aides_tests.coherence import BaseCoherence

RACINE = Path(__file__).resolve().parent.parent
CSS = re.sub(r"/\*.*?\*/", "", (RACINE / "static/css/outil.css").read_text(encoding="utf-8"), flags=re.S)
SCRIPT = script_des_pages()
T = "collecte/templates/collecte/"
PAGES_FILTREES = (T + "saisie.html", T + "pour_moi.html", T + "coherence/liste.html", T + "referentiel.html",
                  T + "administration/attributions.html", T + "administration/organisations.html",
                  T + "administration/comptes.html", T + "administration/journal.html")


def gabarit(chemin):
    """Source d'un gabarit, avec le texte des fragments communs de la barre de filtres à la place de leur inclusion
    (templates/_recherche.html, templates/_menu_affichage.html et ses options), pour lire la barre telle qu'elle s'affiche."""
    def deplier(m):
        texte = (RACINE / "templates" / m.group(1)).read_text(encoding="utf-8")
        options = re.search(r'options="([^"]+)"', m.group(0))
        if options:
            texte = texte.replace("{% include options %}", gabarit(f"collecte/templates/{options.group(1)}"))
        return texte
    return re.sub(r'\{% include "(_recherche\.html|_menu_affichage\.html)"[^%]*%\}', deplier,
                  (RACINE / chemin).read_text(encoding="utf-8"))


def regles_css(selecteur):
    return [m.group(2) for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", CSS) if selecteur in [x.strip() for x in m.group(1).split(",")]]


class BarreDeFiltresTests(TestCase):
    def test_chaque_page_filtree_a_la_meme_barre(self):
        for chemin in PAGES_FILTREES:
            with self.subTest(page=chemin):
                html = gabarit(chemin)
                self.assertIn('class="barre-filtres', html)
                self.assertIn('{% libelle "commun.filtres.recherche" %}', html)  # la recherche a son libellé, en premier
                self.assertLess(html.index('type="search"'), html.index("filtres-droite"))  # actions à droite, après les champs
                self.assertNotIn("outils-orgs", html)  # l'ancienne barre d'outils
        for chemin in PAGES_FILTREES[:-1]:  # l'Historique écrit son compteur lui-même (liste coupée à 300 lignes)
            self.assertIn('{% include "_etat_filtres.html"', gabarit(chemin), chemin)

    def test_un_champ_de_filtre_est_une_liste_avec_son_libelle(self):
        for chemin in PAGES_FILTREES + (T + "_filtres_saisie.html", T + "_choix_referentiel.html"):
            html = gabarit(chemin)
            for m in re.finditer(r"<select[^>]*data-panneau-filtre[^>]*>", html):
                ident = re.search(r'id="([^"]+)"', m.group(0))
                self.assertIsNotNone(ident, f"{chemin} : {m.group(0)}")
                self.assertIn(f'<label for="{ident.group(1)}">', html, f"{chemin} : libellé de {ident.group(1)}")

    def test_plus_de_pastille_grise_pour_filtrer(self):
        for chemin in PAGES_FILTREES:
            html = gabarit(chemin)
            for ancien in ("filtre-controles", "data-filtre-compte", "data-type-seg", "chiffre-filtre", "nb-seg"):
                self.assertNotIn(ancien, html, f"{ancien} dans {chemin}")
        for ancien in ("data-filtre-compte", "data-type-seg", "data-filtre-niveau"):
            self.assertNotIn(ancien, SCRIPT)
        self.assertEqual(regles_css(".segments .nb-seg"), [])

    def test_script_du_champ_de_filtre(self):
        for morceau in ("function initChampsFiltre(", "function valeursFiltre(", "function majEtatFiltres(", "function viderFiltres(",
                        'setAttribute("aria-haspopup", "dialog")', 'e.key === "Escape"', "commun.filtres.tout_selectionner"):
            self.assertIn(morceau, SCRIPT)

    def test_libelles_dans_les_trois_langues(self):
        for cle in ("recherche", "affichage", "effacer_tout", "effacer", "tout_selectionner", "appliquer", "aucun_choix"):
            for langue in ("fr", "en", "es"):
                self.assertNotEqual(libelle("commun.filtres." + cle, langue), "commun.filtres." + cle, f"{cle} en {langue}")
        self.assertEqual(libelle("commun.filtres.compte", "fr", n=1, nombre="1", total="1 823"), "1 résultat sur 1 823")
        self.assertEqual(libelle("commun.filtres.compte", "en", n=37, nombre="37", total="1,823"), "37 results of 1,823")

    def test_apparence(self):
        actif = regles_css("button.liste-filtre.actif")[0]  # (une seconde règle : contraste forcé)
        self.assertIn("background: var(--principale-teinte)", actif)  # filtré : teinté et entouré, jamais comme « Tous »
        self.assertIn("border-color: var(--principale-bord)", actif)
        recherche = regles_css(".barre-filtres > .champ-filtre > input[type=search]")[0]  # (une seconde règle : téléphone)
        self.assertIn("width: 320px", recherche)  # une seule largeur de recherche


class AutresPagesTests(TestCase):
    def test_contenu_d_un_referentiel_meme_barre(self):
        html = gabarit("parametres/templates/parametres/referentiel_contenu.html")
        barre = html.split('class="barre-filtres outils-contenu"')[1].split("</div>\n    </div>")[0]
        self.assertIn('<label for="recherche-contenu">{% libelle "commun.filtres.recherche" %}</label>', barre)
        self.assertIn('class="secondaire" data-tout-deplier', barre)  # des boutons, plus des liens
        self.assertLess(barre.index("data-filtre-contenu"), barre.index("filtres-droite"))

    def test_tableau_de_bord_seulement_en_retard_est_une_case_ordinaire(self):
        (regle,) = regles_css(".filtre-retard")
        self.assertNotIn("orange", regle)
        self.assertNotIn("font-weight", regle)

    def test_consolidation_garde_ses_cases_visibles(self):
        conso = gabarit(T + "consolidation.html")  # elles changent les chiffres affichés : pas dans un menu « Affichage »
        self.assertIn('name="brouillons" value="1"', conso)
        self.assertNotIn("menu-affichage", conso)


class OptionsDAffichageTests(TestCase):
    def test_les_options_d_affichage_sont_dans_le_menu_affichage(self):
        for chemin in (T + "saisie.html", T + "pour_moi.html", T + "coherence/liste.html", T + "administration/attributions.html"):
            html = gabarit(chemin)
            menu = html.split('class="menu-deroulant menu-affichage"')[1].split("</details>")[0]
            self.assertIn('class="case-menu"', menu, chemin)
            self.assertIn('{% libelle "commun.filtres.affichage" %}', menu, chemin)
        self.assertIn("data-montrer-codes", gabarit(T + "saisie.html").split("menu-affichage")[1])

    def test_la_legende_cliquable_de_la_saisie_reste(self):
        self.assertIn("data-filtre-statut", gabarit(T + "_resume.html"))
        self.assertIn("filtresStatut.clear();", SCRIPT)  # « Effacer les filtres » remet aussi la légende à « Total »


class FiltresDuServeurTests(TestCase):
    setUp, saisir, alertes = BaseCoherence.setUp, BaseCoherence.saisir, BaseCoherence.alertes

    def test_coherence_plusieurs_controles(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse("collecte:coherence"), {"controle": ["ecart_n1", "format", "inconnu", "ecart_n1"]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["controles"], ["ecart_n1", "format"])  # inconnu ignoré, doublon retiré
        self.assertEqual(r.context["qs_controles"], "&controle=ecart_n1&controle=format")
        self.assertContains(r, 'data-valeurs="ecart_n1,format"')
        self.assertContains(r, 'data-defaut="a_traiter"')  # « À traiter » n'est pas un filtre actif

    def test_coherence_un_controle_filtre_les_alertes(self):
        self.client.force_login(self.admin)
        self.saisir(self.eff, 300)  # +200 % : écart avec N-1
        self.assertTrue(self.alertes(controle="ecart_n1").exists())
        ici = self.client.get(reverse("collecte:coherence"), {"controle": "ecart_n1"})
        ailleurs = self.client.get(reverse("collecte:coherence"), {"controle": "format"})
        self.assertTrue(all(a.controle == "ecart_n1" for a in ici.context["alertes"]) and ici.context["alertes"])
        self.assertEqual(list(ailleurs.context["alertes"]), [])

    def test_historique_plusieurs_personnes_et_types(self):
        self.client.force_login(self.admin)
        for u, action in ((self.contrib, "creation_campagne"), (self.autre, "reglage_kpi"), (self.admin, "reglage_kpi")):
            Journal.objects.create(utilisateur=u, action=action, objet="Campagne", objet_id="1")
        url = reverse("collecte:admin_journal")
        r = self.client.get(url, {"vue": "admin", "personne": [str(self.contrib.pk), str(self.autre.pk)]})
        self.assertEqual(r.context["personnes_choisies"], [str(self.contrib.pk), str(self.autre.pk)])
        self.assertEqual(len(r.context["entrees"]), 2)
        self.assertEqual(r.context["compte"], "2 résultats sur 3")
        self.assertContains(r, "lien-effacer")
        r = self.client.get(url, {"vue": "admin", "famille": ["referentiel", "inconnue"], "personne": str(self.autre.pk)})
        self.assertEqual(r.context["familles_choisies"], ["referentiel"])
        self.assertEqual(len(r.context["entrees"]), 1)
        # nombre de lignes de chaque choix, écrit dans le panneau
        self.assertIn(("referentiel", 2), [(f, n) for f, _, n in r.context["familles"]])
        sans = self.client.get(url, {"vue": "admin"})
        self.assertEqual(sans.context["compte"], "")
        self.assertNotContains(sans, "lien-effacer")  # aucun filtre : ni compteur ni « Effacer les filtres »

    def test_historique_le_journal_est_un_champ_de_filtre(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse("collecte:admin_journal")).content.decode()
        self.assertNotIn("onglets-journal", html)  # deux niveaux d'onglets au plus
        self.assertIn('id="filtre-journal"', html)
        self.assertIn('data-url="?vue=admin"', html)


class OngletsEnTetesEtChampsTests(TestCase):
    def test_deux_niveaux_d_onglets_au_plus(self):
        self.assertNotIn("onglets-referentiels", gabarit(T + "referentiel.html"))
        self.assertIn('id="filtre-ref-catalogue"', gabarit(T + "referentiel.html"))
        self.assertNotIn("onglets-journal", gabarit(T + "administration/journal.html"))

    def test_onglets_soulignes_dans_la_visualisation(self):
        (actif,) = regles_css('.onglet-vue[aria-current="page"]')
        self.assertIn("border-bottom-color: var(--principale-bord)", actif)
        self.assertNotIn("box-shadow", actif)  # plus d'onglet « dossier »

    def test_un_seul_en_tete_de_colonnes(self):
        for sel in ("thead th", ".grille-attr thead th", ".table-conso thead th", ".table-donnees-visu thead th", ".entete-journal"):
            self.assertTrue(any("background: var(--principale-pale)" in r for r in regles_css(sel)), sel)

    def test_listes_et_cases(self):
        liste = regles_css("select:not([multiple]):not([size])")[0]  # (une seconde règle : contraste forcé)
        self.assertIn("appearance: none", liste)
        self.assertIn("background-image: var(--svg-chevron-liste)", liste)
        self.assertIn(":is(.barre-outils, .barre-filtres, .options-conso, .outils-tdb, .menu-liste) input[type=checkbox] { width: 18px; height: 18px;", CSS)

    def test_action_principale_au_bout_de_la_premiere_rangee(self):
        for chemin, action in ((T + "referentiel.html", "referentiels.contenu.nouveau_kpi"), (T + "administration/journal.html", "admin.journal.exporter"),
                               (T + "administration/attributions.html", "admin.attributions.remplacer"), (T + "administration/comptes.html", "admin.comptes.nouveau")):
            droite = gabarit(chemin).split('class="filtres-droite')[1].split("_etat_filtres")[0].split("etat-filtres")[0]
            self.assertIn(action, droite, chemin)


class IntroductionsEtPagesVidesTests(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        self.client.force_login(self.admin)

    def test_introductions_qui_repetaient_l_ecran_retirees(self):
        for cle in ("admin.nav.intro", "referentiels.catalogue.intro", "suivi.echanges.export.intro_modifiable",
                    "admin.journal.onglet_saisies_aide", "admin.journal.onglet_admin_aide"):
            self.assertEqual(libelle(cle, "fr"), cle, cle)  # la clé n'existe plus

    def test_explications_longues_repliees(self):
        for chemin in (T + "administration/attributions.html", T + "administration/organisations.html"):
            self.assertIn('<details class="aide-repliable aide-page">', gabarit(chemin), chemin)
        self.assertNotIn("discret remonte", gabarit(T + "relances.html").split("apercu")[0])  # même taille que les autres introductions

    def test_page_vide_un_seul_composant(self):
        vide = gabarit(T + "_vide.html")
        self.assertIn('class="page-vide{% if compact %} compact{% endif %}"', vide)
        for chemin in (T + "saisie.html", T + "pour_moi.html", T + "forcages.html", T + "_sections_corps.html", T + "administration/supprimes.html"):
            self.assertIn('{% include "collecte/_vide.html"', gabarit(chemin), chemin)
        self.assertIn("compact=True", gabarit(T + "administration/supprimes.html"))

    def test_pour_moi_sans_attribution_ni_resume_ni_filtres(self):
        # campagne ouverte (sinon la page « aucune campagne » remplace la vue) et contributeur sans aucune attribution :
        # la page vide s'affiche, sans résumé ni barre de filtres au-dessus
        Campagne.objects.create(exercice=2026, statut=Campagne.Statut.OUVERTE)
        kpi = KPI.objects.create(code="EFF", libelle="Effectif", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY)
        site = Organisation.objects.create(nom="Site", niveau_id=Niveau.ENTITY)
        sans = Utilisateur.objects.create(username="sans", email="sans@exemple.test")
        self.client.force_login(sans)
        html = self.client.get(reverse("collecte:pour_moi")).content.decode()
        self.assertIn('class="page-vide"', html)
        self.assertNotIn('class="barre-filtres"', html)
        self.assertNotIn("legende-filtre", html)
        self.assertNotIn('id="resume"', html)
        # témoin : avec une attribution, la même page porte résumé et filtres (le contrôle ci-dessus n'est pas vide)
        Attribution.objects.create(kpi=kpi, organisation=site, utilisateur=sans)
        html = self.client.get(reverse("collecte:pour_moi")).content.decode()
        self.assertNotIn('class="page-vide"', html)
        self.assertIn('class="barre-filtres"', html)
        self.assertIn('id="resume"', html)
