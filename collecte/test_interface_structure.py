"""Uniformisation de l'interface, lot 2 : même fonction = une seule apparence.

1. Onglets et bascules : onglet souligné (.sous-onglets) pour changer de page, pastille grise (.segments) pour changer
   l'affichage ; la bascule pleine couleur et les cartes-onglets n'existent plus.
2. Chiffres clés : tuiles au Tableau de bord seulement ; légende qui filtre (Saisie), chiffres dans le filtre (Cohérence),
   phrase de chiffres (Organisations).
3. Étiquettes : une seule règle de forme ; « Actif » écrit de la même façon dans Comptes et dans Espaces.
4. Aides repliables : .aide-repliable (aide) et .options-repliables (options).
5. Barres en deux hauteurs, état vide en une phrase grise, étapes en ronds numérotés."""
import re
from pathlib import Path

from django.test import TestCase
from django.urls import reverse

from collecte.models import Organisation, Utilisateur
from collecte.outils_tests import html_de

RACINE = Path(__file__).resolve().parent.parent
CSS = re.sub(r"/\*.*?\*/", "", (RACINE / "static/css/outil.css").read_text(encoding="utf-8"), flags=re.S)  # sans les commentaires
GABARITS = [p for dossier in ("collecte", "parametres", "espaces", "templates") for p in (RACINE / dossier).rglob("*.html")]


def regles_css(selecteur):
    """Déclarations des règles dont l'un des sélecteurs est exactement ``selecteur``."""
    return [m.group(2) for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", CSS)
            if selecteur in [x.strip() for x in m.group(1).split(",")]]


def gabarit(chemin):
    return (RACINE / chemin).read_text(encoding="utf-8")


class Base(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        self.client.force_login(self.admin)


class OngletsEtBasculesTests(Base):
    ANCIENS = ("bascule-segments", "bascule-vues", "onglets-secondaires", "compte-journal", "titre-onglet")

    def test_anciennes_apparences_retirees_des_gabarits_et_du_css(self):
        for nom in self.ANCIENS:
            self.assertNotIn(nom, CSS, nom)
            for p in GABARITS:
                self.assertNotIn(nom, p.read_text(encoding="utf-8"), f"{nom} dans {p.name}")
        # les anciens noms gardés comme repères n'ont plus d'apparence à eux
        for nom in (".onglets-parametres", ".onglets-journal", ".onglets-tdb", ".onglets-refs", ".onglets-referentiels", ".onglets-traduction"):
            self.assertEqual(regles_css(nom), [], nom)

    def test_une_seule_regle_pour_l_onglet_souligne(self):
        actif = regles_css('.sous-onglets > a[aria-current="page"]')
        self.assertEqual(len(actif), 1)
        self.assertIn("border-bottom-color: var(--principale-bord)", actif[0])
        self.assertIn(actif[0], regles_css('.sous-onglets > [role="tab"][aria-selected="true"]'))  # liens et boutons role=tab

    def test_la_pastille_grise_ne_prend_jamais_la_couleur_principale(self):
        for sel in ('.segments > button[aria-pressed="true"]', ".segments > a[aria-current]", ".segments > label:has(input:checked)"):
            (regle,) = regles_css(sel)
            self.assertIn("background: var(--surface)", regle)
            self.assertNotIn("--principale", regle)

    def test_parametres_en_onglets_soulignes_plus_petits(self):
        html = html_de(self.client, reverse("parametres:identite"))
        self.assertIn('<nav class="sous-onglets petits onglets-parametres" id="pages-parametres"', html)
        nav = html.split('id="pages-parametres"')[1].split("</nav>")[0]
        self.assertEqual(nav.count('aria-current="page"'), 1)

    def test_historique_les_deux_journaux_dans_un_champ_de_filtre_avec_compteur(self):
        # deux niveaux d'onglets au plus ; les deux journaux sont un champ de filtre, leur nombre
        # de lignes dans le panneau (data-nb)
        html = html_de(self.client, reverse("collecte:admin_journal"))
        self.assertNotIn("onglets-journal", html)
        champ = html.split('id="filtre-journal"')[1].split("</select>")[0]
        self.assertEqual(champ.count("data-nb="), 2)
        self.assertEqual(champ.count(" selected"), 1)

    def test_tableau_de_bord_onglets_et_pastilles(self):
        tdb = gabarit("collecte/templates/collecte/tableau_de_bord.html")
        self.assertIn('<div class="sous-onglets onglets-tdb" role="tablist"', tdb)
        self.assertIn('<nav class="segments" aria-labelledby="libelle-tri">', tdb)
        # Avancement / Consolidation changent de page, donc des onglets soulignés (plus une pastille)
        self.assertIn('<nav class="sous-onglets vues-tdb"', gabarit("collecte/templates/collecte/_vues_tdb.html"))
        self.assertIn('<span class="segments" role="radiogroup"', gabarit("collecte/templates/collecte/consolidation.html"))

    def test_page_d_un_referentiel_dit_ou_l_on_est(self):
        entete = gabarit("parametres/templates/parametres/_entete_referentiel.html")
        self.assertIn('<nav class="sous-onglets petits"', entete)
        self.assertEqual(entete.count('aria-current="page"'), 3)  # une par onglet, sous condition


class ChiffresClesTests(Base):
    def test_tuiles_seulement_au_tableau_de_bord(self):
        for nom in ("cartes-controles", "carte-controle", "cartes-niveaux", "carte-niveau "):
            self.assertNotIn(nom, CSS, nom)
        self.assertNotIn("carte-controle", gabarit("collecte/templates/collecte/coherence/liste.html"))

    def test_saisie_la_barre_puis_sa_legende(self):
        resume = gabarit("collecte/templates/collecte/_resume.html")
        self.assertLess(resume.index('<div class="progression"'), resume.index('class="pastilles legende-filtre"'))
        for statut in ("", "valide", "brouillon", "a_saisir", "alerte"):
            self.assertIn(f'data-filtre-statut="{statut}" aria-pressed=', resume)
        (choisi,) = regles_css('.pastille[aria-pressed="true"]')
        self.assertIn("background: var(--neutre)", choisi)

    def test_coherence_chiffres_dans_le_filtre(self):
        liste = gabarit("collecte/templates/collecte/coherence/liste.html")
        # les chiffres sont dans le panneau des champs de filtre « Statut » et « Contrôle »
        self.assertNotIn("filtre-controles", liste)
        for champ in ('id="filtre-statut-alerte"', 'id="filtre-controle"'):
            self.assertIn('data-nb="{{ n }}"', liste.split(champ)[1].split("</select>")[0])

    def test_organisations_une_phrase_de_chiffres_et_un_champ_niveau(self):
        html = html_de(self.client, reverse("collecte:admin_organisations"))
        phrase = html.split('<p class="resume-comptes">')[1].split("</p>")[0]
        self.assertIn(f"<strong>{Organisation.objects.count()}</strong>", phrase)
        self.assertNotIn("<button", phrase)  # la phrase rappelle les chiffres ; le filtre est le champ « Niveau »
        self.assertIn('<select id="filtre-niveau" data-panneau-filtre data-multiple>', html)
        self.assertNotIn("carte-niveau", html)


class EtiquettesTests(Base):
    NOMS = ("statut", "etat", "type", "ref-chip", "niveau", "role", "facultatif", "badge-partage", "statut-campagne", "controle", "statut-alerte",
            "origine-ref", "pastille-langue", "lien-kpi", "badge-alerte", "pa-etiquette")

    def test_une_seule_regle_de_forme(self):
        formes = [m for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", CSS) if ".etiquette" in [x.strip() for x in m.group(1).split(",")]]
        self.assertEqual(len(formes), 1)
        selecteurs, forme = [x.strip() for x in formes[0].group(1).split(",")], formes[0].group(2)
        for nom in self.NOMS:
            self.assertIn("." + nom, selecteurs, nom)
        for decl in ("font-size: var(--taille-mini)", "font-weight: 600", "border-radius: var(--coin)", "padding: 2px 8px"):
            self.assertIn(decl, forme)

    def test_les_teintes_ne_redefinissent_pas_la_forme(self):
        for nom in self.NOMS:
            for regle in regles_css("." + nom):
                if ".etiquette" in regle or "font-size: var(--taille-mini); font-weight: 600; line-height" in regle:
                    continue  # la règle de forme elle-même
                for interdit in ("font-size", "border-radius", "padding"):
                    self.assertNotIn(interdit + ":", regle, f".{nom} : {interdit}")

    def test_sept_teintes(self):
        for teinte in ("neutre", "vert", "jaune", "orange", "rouge", "bleu", "accent"):
            self.assertEqual(len(regles_css(".e-" + teinte)), 1, teinte)

    def test_facultatif_defini_une_seule_fois(self):
        self.assertEqual(len([r for r in regles_css(".facultatif") if "padding" not in r]), 1)

    def test_actif_s_ecrit_dans_espaces_comme_dans_comptes(self):
        espaces = gabarit("espaces/templates/espaces/liste.html")
        self.assertIn('<span class="etat {% if l.e.etat == "actif" %}etat-actif{% else %}etat-inactif{% endif %}">{{ l.etat }}</span>', espaces)
        self.assertNotIn("statut-campagne", espaces)
        self.assertEqual(self.client.get(reverse("espaces:liste")).status_code, 200)
        self.assertIn('<span class="etat etat-actif">', gabarit("collecte/templates/collecte/administration/comptes.html"))
        self.assertIn('<span class="etat etat-actif">', gabarit("collecte/templates/collecte/administration/organisations.html"))


class AidesRepliablesTests(Base):
    def test_deux_apparences(self):
        for nom in ("details.avance", ".avance summary", "details.options-import summary", ".aide-suppression summary", ".aide-contenu > summary", ".note-methode > summary"):
            self.assertNotIn(nom, CSS, nom)
        self.assertTrue(any("color: var(--principale-texte)" in x for x in regles_css(".aide-repliable > summary")))
        self.assertIn("border: 1px solid var(--bord)", regles_css(".options-repliables")[0])

    def test_aides_converties(self):
        self.assertIn('<details class="aide-repliable note-methode">', gabarit("collecte/templates/collecte/tableau_de_bord.html"))
        self.assertIn('<details class="aide-repliable aide-suppression">', gabarit("parametres/templates/parametres/_identite.html"))
        self.assertIn('<details class="aide-repliable aide-suppression">', gabarit("parametres/templates/parametres/niveaux.html"))
        self.assertIn('<details class="options-repliables options-import"', gabarit("collecte/templates/collecte/echanges/importer.html"))
        self.assertIn('<details class="options-repliables options-export"', gabarit("collecte/templates/collecte/echanges/exporter.html"))

    def test_bon_a_savoir_toujours_en_dernier(self):
        for chemin in ("parametres/templates/parametres/langues.html", "collecte/templates/collecte/administration/fichiers.html",
                       "collecte/templates/collecte/echanges/importer.html"):
            texte = gabarit(chemin)
            fin = texte.split('class="carte bon-a-savoir')[1].split("</details>", 1)[1]
            for bloc in ("<section", "<details", 'class="carte'):
                self.assertNotIn(bloc, fin, f"{chemin} : un bloc suit « Bon à savoir »")

    def test_aide_des_rubriques_dans_la_carte_qu_elle_explique(self):
        html = html_de(self.client, reverse("collecte:admin_accueil"))
        carte = html.split('class="carte rubriques-admin"')[1].split("</section>")[0]
        self.assertIn('<details class="aide-repliable aide-rubriques">', carte)


class BarresVidesEtapesTests(Base):
    def test_barres_deux_hauteurs_un_seul_fond(self):
        (page,) = [r for r in regles_css(".barre-completude") if "height" in r]
        (ligne,) = [r for r in regles_css(".mini-barre") if "height" in r]
        self.assertIn("height: 8px", page)
        self.assertIn("height: 4px", ligne)
        for regle in (page, ligne):
            self.assertIn("background: var(--neutre)", regle)
        for sel in (".progression", ".barre-onglet", ".chargement-barre"):
            self.assertIn(page, regles_css(sel), sel)
        for sel in (".agregat-barre", ".histo-barre", ".barre-ligne .progression"):
            self.assertIn(ligne, regles_css(sel), sel)
        for sel in (".progression", ".barre-completude", ".barre-onglet", ".chargement-barre", ".mini-barre", ".agregat-barre", ".histo-barre"):
            self.assertEqual(len([r for r in regles_css(sel) if "height:" in r.replace("height: 100%", "")]), 1, sel)  # une seule hauteur

    def test_etat_vide_une_phrase_grise_sans_cadre(self):
        (regle,) = regles_css(".etat-vide")
        self.assertIn("color: var(--texte-doux)", regle)
        self.assertIn("border: 0", regle)
        html = html_de(self.client, reverse("collecte:admin_comptes"))
        self.assertIn('<p class="etat-vide" id="aucun-resultat" hidden>', html)
        self.assertNotIn("vide-coherence >", CSS)  # plus de coche dans un rond vert
        for p in GABARITS:
            self.assertNotIn('<p class="carte" id="aucun-resultat"', p.read_text(encoding="utf-8"), p.name)

    def test_etapes_les_ronds_de_l_installation_partout(self):
        for chemin in ("parametres/templates/parametres/_etapes_installation.html", "collecte/templates/collecte/administration/_campagne.html",
                       "collecte/templates/collecte/administration/reprise.html"):
            texte = gabarit(chemin)
            self.assertIn("etapes-numerotees", texte, chemin)
            self.assertIn('aria-current="step"', texte, chemin)
        (rond,) = [r for r in regles_css(".etapes-numerotees .num") if "width" in r]
        self.assertIn("width: 24px; height: 24px", rond)
        self.assertIn(rond, regles_css(".num-etape"))  # les ronds 1 et 2 de l'Import
        self.assertEqual(regles_css(".etape"), [])     # plus de pastilles d'étape
