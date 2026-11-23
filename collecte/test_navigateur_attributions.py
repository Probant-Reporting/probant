"""Dans un vrai navigateur (Playwright, Chromium ; ignoré s'il manque) : grille des attributions (Administration ›
Attributions, écran large). Un clic au centre du bouton d'une case ouvre le choix de la personne ; la case de sélection
(invisible hors survol) ne le recouvre pas. Avant : elle portait la classe des lignes d'option (.choix-ligne, en
grille avec marges) et couvrait le bouton (140 × 13 px) : le clic la cochait. La sélection de plusieurs cases marche."""
import re

from .aides_tests.navigateur import NavigateurBase


class GrilleAttributionsTests(NavigateurBase):
    def test_clic_au_centre_ouvre_le_choix_et_selection_multiple(self):
        page = self.page()
        self.aller(page, "/administration/attributions/")
        bouton = page.locator("td.cellule-attr .bouton-spoc").first
        bouton.scroll_into_view_if_needed()
        b = bouton.bounding_box()
        x, y = b["x"] + b["width"] / 2, b["y"] + b["height"] / 2
        sous = page.evaluate("([x, y]) => document.elementFromPoint(x, y).closest('.bouton-spoc') !== null", [x, y])
        self.assertTrue(sous)  # rien ne recouvre le centre du bouton
        page.mouse.click(x, y)
        page.locator("#choix-spoc").wait_for(state="visible")
        self.assertEqual(page.locator("td.cellule-attr input[type=checkbox]:checked").count(), 0)
        page.keyboard.press("Escape")
        page.mouse.click(5, 5)
        cases = page.locator("td.cellule-attr")
        for i in (0, 1):
            cases.nth(i).hover()
            cases.nth(i).locator("input[type=checkbox]").click()
        self.assertEqual(page.locator("td.cellule-attr input[type=checkbox]:checked").count(), 2)
        self.assertTrue(page.locator("#barre-masse.visible").is_visible())
        self.assertEqual(page.erreurs, [])

    def test_grand_groupe_un_groupe_d_organisations_a_la_fois(self):
        """Échelle (P-A4) : au-delà de la limite de colonnes, le champ « Organisations » de la barre de filtres choisit le
        groupe montré, au clavier ; la page se recharge sur ce groupe, le focus revient sur le champ ; sur téléphone, la
        page ne défile pas en largeur ; axe-core sans défaut grave (si AXE_JS)."""
        import os
        from unittest import mock

        from . import administration as A
        from .test_navigateur_tableaux import REGLES_AXE
        from .aides_tests.navigateur import AXE

        with mock.patch.object(A, "MAX_COLONNES_ATTRIBUTIONS", 1):  # deux entités : deux groupes d'une colonne
            page = self.page()
            self.aller(page, "/administration/attributions/?niveau=Entity")
            self.assertEqual(page.locator("th.col-org").count(), 1)
            self.assertIn("Lille", page.locator("th.col-org").inner_text())
            bouton = page.locator("#filtre-groupe-bouton")
            bouton.focus()
            page.keyboard.press("ArrowDown")  # ouvre le panneau
            choix = page.get_by_role("radio", name=re.compile("Lyon"))
            choix.focus()
            page.keyboard.press("Space")
            page.wait_for_url("**groupe=*")
            page.wait_for_load_state("networkidle")
            self.assertIn("Lyon", page.locator("th.col-org").inner_text())
            self.assertEqual(page.evaluate("document.activeElement && document.activeElement.id"), "filtre-groupe-bouton")
            if AXE and os.path.exists(AXE):
                with open(AXE, encoding="utf-8") as f:
                    page.add_script_tag(content=f.read())
                self.assertEqual(page.evaluate(REGLES_AXE), [], "1 440 px")
            tel = self.page(largeur=390, hauteur=800, tactile=True)
            self.aller(tel, "/administration/attributions/?niveau=Entity")
            self.assertTrue(tel.locator("#filtre-groupe-bouton").is_visible())
            self.assertLessEqual(tel.evaluate("document.documentElement.scrollWidth"), 390)
            self.assertEqual(page.erreurs + tel.erreurs, [])
