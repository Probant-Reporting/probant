"""Visite guidée de la première connexion, dans un vrai navigateur (1 440 et 390 px) : ouverture à la première connexion, jamais
une seconde fois, jamais sur un lien direct, relance par l'Aide, clavier (Tab, Entrée, Échap, focus qui ne se perd pas), zone
d'annonce, « réduire les animations », stockage indisponible, aucune écriture en base, accessibilité axe-core (si AXE_JS).
Les captures sont écrites dans le dossier de la variable DOSSIER_CAPTURES quand elle existe."""
import os
from pathlib import Path

from django.test import override_settings

from referentiel.models import KPI, Utilisateur

from .aides_tests.navigateur import AXE, NavigateurBase, _hors_boucle
from .models import Alerte, Campagne, Journal, Preuve, Reponse
from .test_navigateur_aide import REGLES_AXE
from .test_navigateur_cibles_tactiles import MESURE

MDP = "visite-guidee-essai-2026"
CARTE = "#visite:not([hidden])"


@override_settings(VISITE_GUIDEE=True)
class VisiteGuideeNavigateurTests(NavigateurBase):
    def setUp(self):
        super().setUp()
        with _hors_boucle():
            for u in (self.admin, self.lecteur):
                u.set_password(MDP)
                u.langue = "en"
                u.save()

    def connecter(self, user, largeur=1440, tactile=False, avant=None):
        """Une personne qui se connecte par le formulaire (la visite ne s'ouvre qu'en arrivant de la page de connexion)."""
        page = self.page(user, largeur=largeur, hauteur=900 if largeur > 500 else 800, tactile=tactile)
        page.context.clear_cookies()
        if avant:
            page.context.add_init_script(avant)
        self.aller(page, "/connexion/")
        page.fill("#id_username", user.email)
        page.fill("#id_password", MDP)
        page.locator("form:has(#id_password) button[type=submit]").first.click()
        page.wait_for_load_state("networkidle")
        return page

    def se_deconnecter_et_reconnecter(self, page, user):
        page.locator("form[action$='/deconnexion/'] button, form[action*='logout'] button, form[action$='/logout/'] button").first.click()
        page.wait_for_load_state("networkidle")
        self.aller(page, "/connexion/")
        page.fill("#id_username", user.email)
        page.fill("#id_password", MDP)
        page.locator("form:has(#id_password) button[type=submit]").first.click()
        page.wait_for_load_state("networkidle")

    def compteurs(self):
        with _hors_boucle():
            return {m.__name__: m.objects.count() for m in (Reponse, Journal, Alerte, Preuve, Campagne, Utilisateur, KPI)}

    def _capture(self, page, nom):
        dossier = os.environ.get("DOSSIER_CAPTURES")
        if dossier:
            Path(dossier).mkdir(parents=True, exist_ok=True)
            page.wait_for_timeout(400)
            page.screenshot(path=str(Path(dossier) / nom), full_page=False)

    def test_premiere_connexion_ouvre_la_visite_et_ne_bloque_rien(self):
        page = self.connecter(self.admin)
        self.assertEqual(page.locator(CARTE).count(), 1)
        self.assertEqual(page.locator("#visite-titre").inner_text(), "See what to do first")
        self.assertEqual(page.locator("#visite-etape").inner_text(), "Step 1 of 4")
        self.assertFalse(page.locator("[data-visite-precedent]").is_visible())  # premier pas : pas de « Back »
        self.assertEqual(page.locator("#visite").get_attribute("role"), "region")
        self.assertEqual(page.locator("dialog[open], [aria-modal=true]:visible").count(), 0)  # jamais une fenêtre modale
        self.assertEqual(page.locator("a.visite-cible").count(), 1)  # l'élément montré
        self.assertEqual(page.locator("#visite-annonce").inner_text(), "Guided tour, step 1 of 4: See what to do first")
        # le focus n'est pas volé : la visite ne le prend pas, et la page reste utilisable
        self.assertFalse(page.evaluate("document.getElementById('visite').contains(document.activeElement)"))
        self._capture(page, "visite-ordinateur.png")
        page.locator('nav.onglets a[href="/tableau-de-bord/"]').click()  # un clic ailleurs fonctionne pendant la visite
        page.wait_for_load_state("networkidle")
        self.assertIn("/tableau-de-bord/", page.url)
        self.assertEqual(page.erreurs, [])

    def test_les_pas_puis_la_fermeture_ne_revient_pas(self):
        page = self.connecter(self.admin)
        avant = self.compteurs()
        for attendu in ("Follow the progress", "Import and export", "Open the guide"):
            page.locator("[data-visite-suivant]").click()
            self.assertEqual(page.locator("#visite-titre").inner_text(), attendu)
        self.assertEqual(page.locator("[data-visite-suivant]").inner_text(), "Done")
        page.locator("[data-visite-precedent]").click()
        self.assertEqual(page.locator("#visite-titre").inner_text(), "Import and export")
        page.locator("[data-visite-suivant]").click()
        page.locator("[data-visite-suivant]").click()  # « Done »
        self.assertEqual(page.locator(CARTE).count(), 0)
        self.assertEqual(page.locator(".visite-cible").count(), 0)
        cle = page.evaluate("JSON.parse(document.getElementById('visite-donnees').textContent).cle")
        self.assertEqual(page.evaluate("(c) => window.localStorage.getItem(c)", cle), "1")
        self.assertEqual(self.compteurs(), avant)  # aucune écriture en base
        self.se_deconnecter_et_reconnecter(page, self.admin)
        self.assertEqual(page.locator(CARTE).count(), 0)  # ne revient pas
        self.assertEqual(page.erreurs, [])

    def test_fermer_d_un_clic_echap_et_ne_plus_afficher(self):
        for geste in ("croix", "echap", "plus"):
            with self.subTest(geste=geste):
                page = self.connecter(self.admin)
                self.assertEqual(page.locator(CARTE).count(), 1)
                if geste == "croix":
                    page.locator("[data-visite-fermer]").click()
                elif geste == "echap":
                    page.locator("[data-visite-suivant]").focus()
                    page.keyboard.press("Escape")
                else:
                    page.locator("[data-visite-plus]").click()
                self.assertEqual(page.locator(CARTE).count(), 0)
                self.assertEqual(page.evaluate("document.getElementById('visite').hidden"), True)
                # le focus ne reste pas dans la bulle fermée
                self.assertFalse(page.evaluate("document.getElementById('visite').contains(document.activeElement)"))
                self.se_deconnecter_et_reconnecter(page, self.admin)
                self.assertEqual(page.locator(CARTE).count(), 0, geste)

    def test_echap_sans_focus_dans_la_bulle_la_ferme_si_rien_d_autre_n_est_ouvert(self):
        page = self.connecter(self.admin)
        page.keyboard.press("Escape")
        self.assertEqual(page.locator(CARTE).count(), 0)

    def test_un_lien_direct_n_ouvre_pas_la_visite(self):
        page = self.page(self.admin)  # session déjà ouverte : on arrive par une adresse, pas depuis la page de connexion
        for chemin in ("/saisie/", "/tableau-de-bord/", "/aide/"):
            self.aller(page, chemin)
            self.assertEqual(page.locator(CARTE).count(), 0, chemin)

    def test_pas_de_visite_hors_des_pages_d_accueil_meme_depuis_la_connexion(self):
        page = self.page(self.admin)
        page.context.clear_cookies()
        self.aller(page, "/connexion/?next=/historique/")
        page.fill("#id_username", self.admin.email)
        page.fill("#id_password", MDP)
        page.locator("form:has(#id_password) button[type=submit]").first.click()
        page.wait_for_load_state("networkidle")
        self.assertEqual(page.locator(CARTE).count(), 0)

    def test_relance_par_l_aide_au_clavier(self):
        page = self.page(self.admin)
        self.aller(page, "/aide/")
        bouton = page.locator("[data-visite-relancer]")
        self.assertEqual(bouton.inner_text().strip(), "Show the tour again")
        bouton.focus()
        page.keyboard.press("Enter")
        self.assertEqual(page.locator(CARTE).count(), 1)
        # le focus est dans la bulle, sur « Next », et ne se perd à aucun pas
        for _ in range(3):
            self.assertTrue(page.evaluate("document.getElementById('visite').contains(document.activeElement)"))
            page.keyboard.press("Enter")
        self.assertTrue(page.evaluate("document.getElementById('visite').contains(document.activeElement)"))
        self.assertEqual(page.locator("#visite-titre").inner_text(), "Open the guide")
        page.keyboard.press("Shift+Tab")  # « Back »
        page.keyboard.press("Enter")
        self.assertEqual(page.locator("#visite-titre").inner_text(), "Import and export")
        page.keyboard.press("Escape")
        self.assertEqual(page.locator(CARTE).count(), 0)
        # retour du focus au bouton qui a relancé la visite
        self.assertTrue(page.evaluate("document.activeElement.hasAttribute('data-visite-relancer')"))
        self.assertEqual(page.erreurs, [])

    def test_retour_au_premier_pas_garde_le_focus(self):
        page = self.page(self.admin)
        self.aller(page, "/aide/")
        page.locator("[data-visite-relancer]").click()
        page.locator("[data-visite-suivant]").click()
        page.locator("[data-visite-precedent]").focus()
        page.keyboard.press("Enter")
        self.assertEqual(page.locator("#visite-titre").inner_text(), "See what to do first")
        self.assertTrue(page.evaluate("document.activeElement.matches('[data-visite-suivant]')"))  # « Back » a disparu

    def test_parametre_visite_lance_la_visite_et_nettoie_l_adresse(self):
        page = self.page(self.lecteur)
        self.aller(page, "/visualisation/?visite=1")
        self.assertEqual(page.locator(CARTE).count(), 1)
        self.assertNotIn("visite=1", page.url)
        self.assertEqual(page.locator("#visite-etape").inner_text(), "Step 1 of 3")  # lecteur : trois pas

    def test_telephone(self):
        page = self.connecter(self.admin, largeur=390, tactile=True)
        self.assertEqual(page.locator(CARTE).count(), 1)
        boite = page.locator("#visite").bounding_box()
        self.assertGreaterEqual(boite["x"], 0)
        self.assertLessEqual(boite["x"] + boite["width"], 390)
        self.assertLessEqual(boite["y"] + boite["height"], 800)
        self.assertFalse(page.evaluate("document.documentElement.scrollWidth > window.innerWidth"))
        self.assertEqual(page.evaluate(MESURE), [])  # cibles d'au moins 24 px
        for _ in range(3):
            page.locator("[data-visite-suivant]").tap()
        page.locator("[data-visite-suivant]").tap()
        self.assertEqual(page.locator(CARTE).count(), 0)
        self.assertEqual(page.erreurs, [])

    def test_telephone_l_element_montre_est_dans_la_zone_visible_de_la_barre(self):
        """La barre d'onglets défile à l'horizontale sur téléphone : chaque étape y fait venir l'élément montré (sans animation
        avec « réduire les animations »)."""
        visible = """() => { const c = document.querySelector('.visite-cible'); if (!c) return null;
            const r = c.getBoundingClientRect(), n = (c.closest('nav.onglets') || document.documentElement).getBoundingClientRect();
            return r.left >= Math.max(0, n.left) - 1 && r.right <= Math.min(window.innerWidth, n.right) + 1; }"""
        page = self.connecter(self.admin, largeur=390, tactile=True)
        page.emulate_media(reduced_motion="reduce")
        etapes = page.evaluate("JSON.parse(document.getElementById('visite-donnees').textContent).etapes.length")
        for i in range(etapes):
            page.wait_for_timeout(150)
            self.assertIn(page.evaluate(visible), (None, True), f"étape {i + 1} : élément montré hors de la zone visible")
            if i < etapes - 1:
                page.locator("[data-visite-suivant]").tap()
        for i in range(etapes - 1, 0, -1):  # et en revenant en arrière
            page.locator("[data-visite-precedent]").tap()
            page.wait_for_timeout(150)
            self.assertIn(page.evaluate(visible), (None, True), f"retour à l'étape {i}")
        self.assertEqual(page.erreurs, [])

    def test_la_bulle_est_atteinte_en_une_tabulation_sans_prendre_le_focus(self):
        page = self.connecter(self.admin)
        self.assertEqual(page.locator(CARTE).count(), 1)
        self.assertFalse(page.evaluate("document.getElementById('visite').contains(document.activeElement)"))  # focus non volé
        page.keyboard.press("Tab")
        self.assertTrue(page.evaluate("document.getElementById('visite').contains(document.activeElement)"))

    def test_boutons_de_la_visite_de_meme_hauteur_et_fermeture_d_au_moins_24_px(self):
        for largeur in (1440, 390):
            page = self.connecter(self.admin, largeur=largeur, tactile=largeur < 500)
            page.locator("[data-visite-suivant]").tap() if largeur < 500 else page.locator("[data-visite-suivant]").click()
            mesures = page.evaluate("""() => ['[data-visite-precedent]', '[data-visite-suivant]', '[data-visite-fermer]'].map(s => {
                const r = document.querySelector(s).getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)]; })""")
            self.assertEqual(mesures[0][1], mesures[1][1], (largeur, mesures))
            self.assertGreaterEqual(min(mesures[2]), 24, (largeur, mesures))

    def test_telephone_capture(self):
        page = self.connecter(self.admin, largeur=390, tactile=True)
        self._capture(page, "visite-telephone.png")

    def test_reduire_les_animations(self):
        page = self.page(self.admin)
        page.emulate_media(reduced_motion="reduce")
        self.aller(page, "/aide/")
        page.locator("[data-visite-relancer]").click()
        duree = page.evaluate("parseFloat(getComputedStyle(document.getElementById('visite')).animationDuration) * "
                              "(getComputedStyle(document.getElementById('visite')).animationDuration.endsWith('ms') ? 0.001 : 1)")
        self.assertLess(duree, 0.001)

    def test_stockage_indisponible_pas_d_ouverture_automatique_mais_relance_possible(self):
        casse = "Object.defineProperty(window, 'localStorage', {get() { throw new Error('stockage refusé'); }});"
        page = self.connecter(self.admin, avant=casse)
        self.assertEqual(page.locator(CARTE).count(), 0)
        self.assertEqual(page.erreurs, [])
        self.aller(page, "/aide/")
        page.locator("[data-visite-relancer]").click()
        self.assertEqual(page.locator(CARTE).count(), 1)
        page.locator("[data-visite-plus]").click()  # fermer sans stockage : aucune erreur
        self.assertEqual(page.locator(CARTE).count(), 0)
        self.assertEqual(page.erreurs, [])

    def test_lecteur_arrive_sur_la_visualisation(self):
        page = self.connecter(self.lecteur)
        self.assertEqual(page.locator(CARTE).count(), 1)
        self.assertEqual(page.locator("#visite-titre").inner_text(), "Follow the progress")
        self.assertEqual(page.locator("#visite-etape").inner_text(), "Step 1 of 3")

    def test_accessibilite(self):
        if not AXE or not os.path.exists(AXE):
            self.skipTest("axe-core absent (variable AXE_JS)")
        with open(AXE, encoding="utf-8") as f:
            axe = f.read()
        for largeur in (1440, 390):
            page = self.connecter(self.admin, largeur=largeur, tactile=largeur < 500)
            self.assertEqual(page.locator(CARTE).count(), 1)
            for _ in range(4):
                page.add_script_tag(content=axe)
                self.assertEqual(page.evaluate(REGLES_AXE), [], largeur)
                if page.locator("[data-visite-suivant]").inner_text() == "Done":
                    break
                page.locator("[data-visite-suivant]").click()
