"""Accessibilité, téléphone et textes : lignes ouvrables au clavier, choix du SPOC, contrastes,
menus sur téléphone, erreurs reliées aux champs, titres des pages plein écran, textes à l'écran."""
import re
from decimal import Decimal
from pathlib import Path

from django.test import TestCase
from django.urls import reverse

from parametres.referentiel import unite_depuis_symbole as U
from referentiel.models import KPI, Attribution, Niveau, Organisation, Utilisateur

from . import saisie as S
from .models import Alerte, Campagne, RegleCoherence, Reponse
from .outils_tests import script_des_pages
from .aides_tests.referentiels import Base as BaseReferentiels
from parametres.models import Langue

D = Decimal


class Base(TestCase):
    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.p)
        self.c0 = Campagne.objects.create(exercice=2025, statut=Campagne.Statut.CLOTUREE)
        self.c = Campagne.objects.create(exercice=2026, statut=Campagne.Statut.OUVERTE, seuil_ecart=D("0.2"))
        self.eff = KPI.objects.create(code="EFF", libelle="Effectif", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                                      unite=U("employees"), methode_agregation="Somme")
        self.form = KPI.objects.create(code="FORM", libelle="Formés", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                                       unite=U("employees"), methode_agregation="Somme")
        self.contrib = Utilisateur.objects.create(username="contrib", email="contrib@exemple.test", first_name="Lucas",
                                                  last_name="Bernard")
        self.valid = Utilisateur.objects.create(username="valid", email="valid@exemple.test", role=Utilisateur.Role.VALIDATEUR)
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        for k in (self.eff, self.form):
            Attribution.objects.create(kpi=k, organisation=self.e1, utilisateur=self.contrib)
        Reponse.objects.create(periode=self.c0.periode, kpi=self.eff, organisation=self.e1, valeur=D(100),
                               statut=Reponse.Statut.VALIDE, origine=Reponse.Origine.IMPORT)

    def page(self, nom, user=None, *args):
        self.client.force_login(user or self.admin)
        rep = self.client.get(reverse(f"collecte:{nom}", args=args))
        self.assertEqual(rep.status_code, 200, nom)
        return rep.content.decode()


def lignes_ouvrables(html):
    """Les balises <tr …> qui portent data-url (lignes qui ouvrent un panneau)."""
    return [m.group(0) for m in re.finditer(r"<tr\b[^>]*\bdata-url=[^>]*>", html, re.S)]


class AvecAlerte(Base):
    def setUp(self):
        super().setUp()
        S.enregistrer(self.contrib, self.c, self.eff, self.e1, "150", False, "")  # écart N-1 : une alerte
        RegleCoherence.objects.create(nom="Formés ≤ effectif", gauche="[FORM]", operateur="<=", droite="[EFF]",
                                      niveau_id=Niveau.ENTITY)
        self.assertTrue(Alerte.objects.exists())


class LignesAuClavierTests(AvecAlerte):
    """A1 : chaque ligne qui ouvre un panneau est atteignable au clavier (tabindex) et porte un nom accessible."""

    def verifier(self, html, attendu):
        lignes = lignes_ouvrables(html)
        self.assertTrue(lignes, "aucune ligne")
        for tr in lignes:
            self.assertIn('tabindex="0"', tr)
            self.assertRegex(tr, r'aria-label="[^"]+ : ouvrir \(Entrée\)"')
        self.assertTrue(any(attendu in tr for tr in lignes), attendu)

    def test_campagnes(self):
        self.verifier(self.page("admin_campagnes"), 'aria-label="Exercice 2026')

    def test_comptes(self):
        self.verifier(self.page("admin_comptes"), 'aria-label="Lucas Bernard')

    def test_organisations(self):
        self.verifier(self.page("admin_organisations"), 'aria-label="E1')

    def test_catalogue_des_kpi(self):
        self.verifier(self.page("referentiel"), 'aria-label="EFF – Effectif')

    def test_alertes_de_coherence(self):
        self.verifier(self.page("coherence"), 'aria-label="Effectif – E1')
        self.verifier(self.page("coherence", self.contrib), 'aria-label="Effectif – E1')

    def test_regles(self):
        self.verifier(self.page("regles"), 'aria-label="Formés ≤ effectif')


class ChoixSpocAuClavierTests(Base):
    """A2 : le bouton SPOC porte un nom en clair ; dans la fenêtre, chaque personne est un vrai bouton et Échap rend le
    focus au bouton d'origine."""

    def test_nom_du_bouton_spoc(self):
        html = self.page("saisie")
        self.assertIn('<span class="visually-hidden">Choisir le SPOC – Lucas Bernard</span>', html)
        self.assertRegex(html, r'class="bouton-spoc"[^>]*><span class="avatar"[^>]*aria-hidden="true">LB</span>')

    def test_personnes_en_boutons_et_focus_rendu(self):
        js = script_des_pages()
        self.assertIn('const b = document.createElement("button");', js)
        self.assertIn('e.target.closest("[data-id]")', js)
        self.assertIn("ouvreurSpoc", js)


CSS = (Path(__file__).resolve().parent.parent / "static/css/outil.css").read_text(encoding="utf-8")


def regles_css(selecteur):
    """Déclarations des règles dont l'un des sélecteurs est exactement ``selecteur``."""
    return [m.group(2) for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", CSS)
            if selecteur in [x.strip() for x in m.group(1).split(",")]]


class ContrastesTests(TestCase):
    """A3 et A4 : bords des champs, interrupteur, puces, organisations décochées et thème vide au-dessus des minimums
    (var(--contour) : 3:1 pour un élément d'interface ; var(--texte-doux) : 4,5:1 pour un texte)."""

    def test_champs_jamais_bordes_du_bord_pale(self):
        fautifs = [m.group(1).strip() for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", CSS)
                   if re.search(r"(?<![-\w])(input|select|textarea)\b", m.group(1)) and "border: 1px solid var(--bord)" in m.group(2)]
        self.assertEqual(fautifs, [])

    def test_interrupteur_puces_et_textes_lisibles(self):
        self.assertIn("background: var(--texte-doux)", regles_css(".glissiere")[0])
        self.assertIn("border: 1.5px solid var(--texte-doux)", regles_css(".puce > span::before")[0])
        self.assertIn("border: 1px solid var(--contour)", regles_css(".puce > span")[0])
        self.assertIn("color: var(--texte-doux)", regles_css(".case-org:has(input:not(:checked)) .nom-org")[0])
        niveau = regles_css(".case-org:has(input:not(:checked)) .niveau")[0]
        self.assertNotIn("opacity", niveau)
        self.assertIn("color: var(--texte-doux)", niveau)
        self.assertIn("color: var(--texte-doux)", regles_css(".vide-theme")[0])


class MenusDansLEcranTests(TestCase):
    """A5 : les menus « Exporter » et « ⋯ » d'un thème ne dépassent jamais la largeur de l'écran (téléphone, zoom 200 %)."""

    def test_largeur_bornee_et_recadrage(self):
        self.assertIn("max-width: calc(100vw - 16px)", regles_css(".menu-liste")[0])
        # désormais (un seul menu), le « ⋯ » d'un thème est un .menu-deroulant comme les autres
        self.assertEqual(regles_css(".menu-theme-liste"), [])
        self.assertIn("max-width: 100%", regles_css(".menu-liste select")[0])
        js = script_des_pages()
        self.assertIn('d.matches?.("details.menu-deroulant")', js)
        gabarit = (Path(__file__).resolve().parent.parent / "parametres/templates/parametres/_contenu_theme.html").read_text(encoding="utf-8")
        self.assertIn('<details class="menu-deroulant menu-theme">', gabarit)


class ErreursRelieesTests(Base):
    """A6 : erreurs reliées aux champs (connexion, formulaires) ; libellés et autocomplete de Mon compte gardés après
    une erreur."""

    def test_connexion_erreur_reliee_aux_deux_champs(self):
        self.admin.set_password("Un-Mot-De-Passe-Solide-42")
        self.admin.save()
        html = self.client.post(reverse("login"), {"username": "admin@exemple.test", "password": "faux"}).content.decode()
        self.assertIn('<p class="encart encart-erreur" id="erreur-connexion" role="alert">', html)
        self.assertRegex(html, r'id="id_username" aria-describedby="erreur-connexion" aria-invalid="true"')
        self.assertRegex(html, r'id="id_password" aria-describedby="erreur-connexion" aria-invalid="true"')
        sans_erreur = self.client.get(reverse("login")).content.decode()
        self.assertNotRegex(sans_erreur, r'<input[^>]*aria-invalid')

    def test_mon_compte_libelles_apres_une_erreur(self):
        self.client.force_login(self.admin)
        for rep in (self.client.get(reverse("collecte:mon_compte")),
                    self.client.post(reverse("collecte:mon_compte"), {"old_password": "x", "new_password1": "Abcdefgh-1234-xyz",
                                                                       "new_password2": "Abcdefgh-1234-xya"})):
            html = rep.content.decode()
            self.assertIn(">Mot de passe actuel</label>", html)
            self.assertIn(">Nouveau mot de passe (confirmation)</label>", html)
            self.assertNotIn("Ancien mot de passe", html)
            self.assertRegex(html, r'autocomplete="current-password"[^>]*id="id_old_password"|id="id_old_password"[^>]*autocomplete="current-password"'
                             r'|name="old_password" autocomplete="current-password"')
            self.assertEqual(html.count('autocomplete="new-password"'), 2)

    def test_erreurs_des_formulaires_reliees_par_le_script(self):
        js = script_des_pages()
        self.assertIn("function relierErreurs(racine)", js)
        self.assertIn("relierErreurs(racine);", js)


class RecetteAuVertTests(Base):
    """A7 : « Marquer relancé » garde son texte visible au début de son nom accessible (2.5.3) ; à 1 440 px, les marges
    du bandeau sont resserrées pour garder les libellés Import / Export et Administration (E15)."""

    def test_marquer_relance(self):
        html = self.page("relances")
        self.assertIn('aria-label="Marquer relancé : Lucas Bernard">Marquer relancé</button>', html)
        self.assertNotIn("comme relancé", html)

    def test_bandeau_resserre_sous_1600_px(self):
        bloc = re.search(r"@media \(max-width: 1599px\) \{(.*?)\}\s*\}", CSS, re.S).group(1)
        self.assertIn("nav.onglets a { padding: 8px 8px;", bloc)
        self.assertIn(".haut .barre-haut { gap: 14px; }", bloc)
        self.assertIn(".compte-haut { gap: 8px; }", bloc)


class SansDefilementHorizontalTests(TestCase):
    """A8 : Niveaux de l'arbre à 375 px et filtres des Comptes au zoom 200 % sans défilement horizontal."""

    def test_niveaux_et_segments(self):
        self.assertIn("grid-template-columns: minmax(0, 1fr) minmax(0, 1fr)", regles_css(".noms-niveau")[0])
        self.assertIn("min-width: 0", regles_css(".noms-niveau input")[0])
        self.assertIn("flex-wrap: wrap", regles_css(".actions-niveau")[0])
        self.assertIn("flex-wrap: wrap", regles_css(".segments")[0])
        self.assertIn("grid-template-columns: minmax(0, 1fr) auto", regles_css(".ligne-niveau")[-1])


class PagesPleinEcranTests(AvecAlerte):
    """A10 : pages plein écran (sans JavaScript, nouvel onglet) avec un titre propre et un h1 ; onglet actif annoncé
    (aria-current)."""

    def titre_et_h1(self, nom, args, attendu, user=None):
        html = self.page(nom, user, *args)
        self.assertIn(f"<title>{attendu} – ", html)
        self.assertIn(f'<h1 class="visually-hidden">{attendu}</h1>', html)
        return html

    def test_titres(self):
        a = Alerte.objects.first()
        r = RegleCoherence.objects.first()
        self.titre_et_h1("admin_compte", [self.contrib.pk], "Lucas Bernard – Compte")
        self.titre_et_h1("admin_organisation", [self.e1.pk], "E1 – Organisation")
        self.titre_et_h1("admin_campagne", [self.c.pk], "Exercice 2026 – Campagne")
        self.titre_et_h1("admin_compte_nouveau", [], "Nouveau compte")
        self.titre_et_h1("regle", [r.pk], "Formés ≤ effectif – Règle de cohérence")
        self.titre_et_h1("regle_nouvelle", [], "Nouvelle règle de cohérence")
        html = self.titre_et_h1("alerte", [a.pk], "Effectif – E1 – Alerte de cohérence", self.contrib)
        self.assertIn("← Retour à la cohérence", html)  # le contributeur n'a pas accès à l'administration
        self.assertIn('<h1 class="visually-hidden">Effectif – E1</h1>', self.page("cellule", None, self.c.pk, "EFF", self.e1.pk))
        self.assertIn('<h1 class="visually-hidden">KPI EFF – Effectif</h1>', self.page("referentiel_kpi", None, "EFF"))

    def test_onglet_actif_annonce(self):
        html = self.page("admin_comptes")
        self.assertRegex(html, r'href="/administration/" aria-current="page" class="actif')
        self.assertRegex(html, r'href="/administration/comptes/" aria-current="page" class="actif"')
        self.assertEqual(len(re.findall(r'<nav class="onglets"[^>]*>.*?</nav>', html, re.S)[0].split('aria-current="page"')), 2)


SMTP_REFUSE = dict(EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend", EMAIL_HOST="127.0.0.1", EMAIL_PORT=1, EMAIL_TIMEOUT=2)


class RangerAuClavierTests(BaseReferentiels):
    """A9 : un KPI se range dans son thème sans glisser (Alt + flèche haut / bas) : le script envoie l'action « deposer »
    avec « avant » = le KPI précédent (monter) ou celui d'après le suivant, vide en fin de thème (descendre)."""

    def ordre(self, theme):
        from referentiel.models import ElementReferentiel

        return list(ElementReferentiel.objects.filter(referentiel=self.nrg, theme=theme).order_by("ordre").values_list("kpi_id", flat=True))

    def action(self, **corps):
        import json

        rep = self.client.post(reverse("parametres:referentiel_contenu_action", args=["ENERGIE"]), json.dumps(corps),
                               content_type="application/json")
        self.assertEqual(rep.status_code, 200, rep.content)
        return rep.json()

    def test_monter_et_descendre(self):
        from referentiel.models import Theme

        conso = Theme.objects.get(referentiel=self.nrg, nom="Consommations")
        self.assertEqual(self.ordre(conso), ["ELEC", "NRJ"])
        self.action(action="deposer", theme=conso.pk, source={"type": "element", "code": "NRJ"}, avant="ELEC")  # Alt + ↑
        self.assertEqual(self.ordre(conso), ["NRJ", "ELEC"])
        r = self.action(action="deposer", theme=conso.pk, source={"type": "element", "code": "NRJ"}, avant="")  # Alt + ↓
        self.assertEqual(self.ordre(conso), ["ELEC", "NRJ"])
        self.assertIn("ranger (Alt + flèche haut ou bas)", r["html"])
        js = script_des_pages()
        self.assertIn('if (!e.altKey || (e.key !== "ArrowUp" && e.key !== "ArrowDown")) return;', js)
        # au doigt : boutons ▲ ▼ nommés, même action « deposer », visibles sur téléphone et tablette
        self.assertIn('data-ranger="haut" aria-label="Monter NRJ"', r["html"])
        self.assertIn('data-ranger="bas" aria-label="Descendre NRJ"', r["html"])
        self.assertIn("} else if (d.ranger) {", js)
        css = (Path(__file__).parent.parent / "static/css/outil.css").read_text(encoding="utf-8")
        self.assertIn("@media (max-width: 800px), (pointer: coarse) { .kpis-theme td.ranger-doigt { display: table-cell; }", css)


class CiblesTactiles(TestCase):
    """Téléphone : le titre de colonne qui trie et le lien « Données et confidentialité » du pied
    de page mesuraient 23 px et 17 px de haut : au moins 24 px (WCAG 2.2, 2.5.8)."""

    def test_titre_de_colonne_et_lien_du_pied(self):
        css = (Path(__file__).parent.parent / "static/css/outil.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"\.tri-entete, button\.tri-entete \{[^}]*min-height: 24px")
        self.assertRegex(css, r"\.pied-version a \{[^}]*display: inline-block; padding: 4px 2px")


class ListeDansLePanneau(TestCase):
    """Téléphone : la liste de choix du panneau de saisie, à la largeur de son plus long choix, sortait
    du panneau à droite (408 px dans un panneau de 332 px) : elle ne dépasse jamais son conteneur."""

    def test_liste_de_choix_bornee(self):
        css = (Path(__file__).parent.parent / "static/css/outil.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"select\.champ-liste \{[^}]*max-width: 100%")


class FenetreThematique(TestCase):
    """Choix de la thématique (unités, ajout d'une unité) : la fenêtre de suggestion est rangée dans <main> (règle
    « region » d'axe-core) et vraiment masquée quand elle est fermée (sinon un cadre vide traîne en bas de la page)."""

    def test_fenetre_dans_main_et_masquee(self):
        js = script_des_pages()
        self.assertIn('bulles.className = "choix-theme"', js)
        self.assertIn('(document.getElementById("contenu") || document.body).appendChild(bulles);', js)
        self.assertNotIn("document.body.appendChild(bulles);", js)
        # boutons et champ « créer » : un groupe nommé, pas une liste d'options (axe « aria-required-children »)
        self.assertIn('bulles.setAttribute("role", "group");', js)
        self.assertNotIn('b.setAttribute("role", "option")', js)
        self.assertIn("display: none", " ".join(regles_css(".choix-theme[hidden]")))


PAGES = ["/administration/parametres/", "/administration/parametres/niveaux/", "/administration/parametres/seuils/",
         "/administration/parametres/visualisation/", "/administration/parametres/referentiel/",
         "/administration/parametres/referentiel/?section=types-saisie",
         "/administration/parametres/referentiel/?section=types-reponse", "/administration/parametres/hebergement/",
         "/administration/parametres/sante/", "/administration/comptes/connexions/",
         "/coherence/", "/administration/campagnes/", "/administration/organisations/", "/administration/attributions/",
         "/tableau-de-bord/"]


def contenu_principal(html):
    """Le <main> de la page, sans les modèles (<template>) ni le contenu sans JavaScript (<noscript>)."""
    debut = html.index("<main")
    main = html[debut:html.index("</main>", debut)]
    return re.sub(r"<(template|noscript)\b.*?</\1>", "", main, flags=re.S)


class TitresEtEntetesTests(AvecAlerte):
    def setUp(self):
        super().setUp()
        Langue.objects.get_or_create(code="en", defaults={"libelle": "English", "ordre": 2})
        Langue.objects.get_or_create(code="es", defaults={"libelle": "Español", "ordre": 3})

    def pages(self):
        self.client.force_login(self.admin)
        for langue in ("fr", "en", "es"):
            self.client.post("/langue/", {"langue": langue, "suivant": "/"})
            for chemin in PAGES:
                rep = self.client.get(chemin)
                self.assertEqual(rep.status_code, 200, chemin)
                yield langue, chemin, contenu_principal(rep.content.decode())

    def test_titres_sans_saut_de_niveau(self):
        for langue, chemin, main in self.pages():
            niveaux = [int(n) for n in re.findall(r"<h([1-6])\b", main)]
            with self.subTest(langue=langue, page=chemin):
                self.assertTrue(niveaux, chemin)
                sauts = [(a, b) for a, b in zip(niveaux, niveaux[1:]) if b > a + 1]
                self.assertEqual(sauts, [], niveaux)

    def test_entetes_de_tableau_jamais_vides(self):
        for langue, chemin, main in self.pages():
            with self.subTest(langue=langue, page=chemin):
                self.assertEqual(re.findall(r"<th\b[^>]*>\s*</th>", main), [])
