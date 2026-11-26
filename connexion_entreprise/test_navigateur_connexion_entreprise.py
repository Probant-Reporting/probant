"""Navigateur (Chromium, ignoré s'il manque sauf REQUIRE_BROWSER_TESTS=1) : parcours complet de la connexion d'entreprise
contre le faux fournisseur (vrai HTTP, vraies signatures) : bouton de la page de connexion atteint au clavier, aller
vers le fournisseur, retour, arrivée connecté ; à 1 440 et 390 px, sans défilement horizontal, zones cliquables d'au
moins 24 × 24 px, sans erreur de script ni violation de la politique de sécurité des contenus (``surveiller_politique``).
Écran de réglage au clavier et à 390 px. Accessibilité axe-core si AXE_JS."""
import os

from collecte.aides_tests.navigateur import AXE, NavigateurBase, _hors_boucle
from collecte.test_navigateur_cibles_tactiles import MESURE

from .aides_tests import regler
from .aides_tests.faux_fournisseur import FauxFournisseur

REGLES_AXE = """async () => { const r = await axe.run(document, {runOnly: {type: 'tag', values:
    ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']}});
    return r.violations.filter(v => ['serious', 'critical'].includes(v.impact)).map(v => v.id + ' ' + v.nodes.map(n => n.target).join(','))}"""
# zones cliquables de moins de 24 × 24 px (DESIGN.md, « Touch targets ») : même mesure que le test des cibles tactiles
# (la zone d'une case à cocher est celle de son libellé ; liens au milieu d'une phrase exemptés)


class ConnexionEntrepriseNavigateurTests(NavigateurBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.faux = FauxFournisseur()

    @classmethod
    def tearDownClass(cls):
        cls.faux.arreter()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        from espaces.models import Compte
        from referentiel.models import Utilisateur

        with _hors_boucle():
            self.contrib = Utilisateur.objects.create(username="contrib", email="contrib@exemple.example",
                                                      role=Utilisateur.Role.CONTRIBUTEUR)
            Compte.objects.filter(pk=self.admin.pk).update(gestionnaire=True)
            regler(self.faux, libelle_bouton="")

    def sans_connexion(self, largeur):
        page = self.page(largeur=largeur, tactile=largeur < 500)
        page.context.clear_cookies()
        return page

    def test_parcours_complet_au_clavier(self):
        from referentiel.models import HistoriqueConnexion

        for largeur in (1440, 390):
            page = self.sans_connexion(largeur)
            self.aller(page, "/connexion/")
            bouton = page.locator("#bouton-entreprise")
            self.assertTrue(bouton.is_visible())
            self.assertEqual(page.evaluate(MESURE), [], largeur)
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), largeur, largeur)
            for _ in range(10):  # premier arrêt du clavier sur la carte : le champ e-mail (autofocus) ou le bouton
                if page.evaluate("document.activeElement.id") == "bouton-entreprise":
                    break
                page.keyboard.press("Shift+Tab" if page.evaluate("document.activeElement.id") == "id_username" else "Tab")
            self.assertEqual(page.evaluate("document.activeElement.id"), "bouton-entreprise", largeur)
            self.assertNotEqual(page.evaluate("getComputedStyle(document.activeElement).outlineStyle"), "none")
            with page.expect_navigation(url=lambda u: "/connexion/" not in u):
                page.keyboard.press("Enter")
            page.wait_for_load_state("networkidle")
            self.assertTrue(page.url.startswith(self.live_server_url), page.url)
            self.assertEqual(page.locator("input[name=password]").count(), 0)  # arrivée dans l'outil, plus la page de connexion
            self.assertEqual(page.erreurs, [])
        with _hors_boucle():
            self.assertEqual(list(HistoriqueConnexion.objects.values_list("utilisateur_id", "methode", "resultat")),
                             [(self.contrib.pk, "entreprise", "reussie")] * 2)

    def test_refus_message_sur_la_page_de_connexion(self):
        self.faux.claims = {"email": "personne@exemple.example"}
        try:
            page = self.sans_connexion(390)
            self.aller(page, "/connexion/")
            with page.expect_navigation(url=lambda u: u.rstrip("/").endswith("/connexion")):
                page.locator("#bouton-entreprise").click()
            self.assertEqual(page.locator("#message-connexion .encart-erreur").count(), 1)
            self.assertEqual(page.erreurs, [])
        finally:
            self.faux.claims = {}

    def test_ecran_de_reglage_au_clavier_et_au_telephone(self):
        for largeur in (1440, 390):
            page = self.page(self.admin, largeur=largeur, tactile=largeur < 500)
            self.aller(page, "/administration/parametres/connexion-entreprise/")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), largeur, largeur)
            self.assertEqual(page.evaluate(MESURE), [], largeur)
            self.assertEqual(page.locator("#ce-secret").input_value(), "")  # secret jamais réaffiché
            with page.expect_navigation():
                page.locator("button[value=essayer]").click()
            self.assertEqual(page.locator(".liste-essai-ce li.ok").count(), 2)
            self.assertEqual(page.evaluate("document.activeElement.id"), "", largeur)  # le bloc du résultat a le focus
            self.assertTrue(page.evaluate("document.activeElement.classList.contains('resultat-essai-ce')"))
            self.assertEqual(page.erreurs, [])

    def test_accessibilite_axe(self):
        if not AXE or not os.path.exists(AXE):
            self.skipTest("axe-core absent (variable AXE_JS)")
        with open(AXE, encoding="utf-8") as f:
            axe = f.read()
        for largeur in (1440, 390):
            page = self.sans_connexion(largeur)
            self.aller(page, "/connexion/")
            page.add_script_tag(content=axe)
            self.assertEqual(page.evaluate(REGLES_AXE), [], largeur)
            page = self.page(self.admin, largeur=largeur, tactile=largeur < 500)
            self.aller(page, "/administration/parametres/connexion-entreprise/")
            page.add_script_tag(content=axe)
            self.assertEqual(page.evaluate(REGLES_AXE), [], largeur)
