"""Dans un vrai navigateur (Playwright, Chromium ; ignoré s'il manque) : Administration › Attributions d'un grand groupe
(seconde recette, B8). Changer de groupe d'organisations avec des cases cochées les perdait sans avertissement : la page
demande d'abord ; « Annuler » garde la sélection et le groupe affiché ; confirmer recharge sur le nouveau groupe."""
import re
from unittest import mock

from . import administration as A
from .aides_tests.navigateur import NavigateurBase


class GroupeAvecSelectionTests(NavigateurBase):
    def choisir_lyon(self, page):
        page.locator("#filtre-groupe-bouton").focus()
        page.keyboard.press("ArrowDown")
        choix = page.get_by_role("radio", name=re.compile("Lyon"))
        choix.focus()
        page.keyboard.press("Space")

    def test_avertit_avant_de_perdre_la_selection(self):
        with mock.patch.object(A, "MAX_COLONNES_ATTRIBUTIONS", 1):
            page = self.page()
            self.aller(page, "/administration/attributions/?niveau=Entity")
            case = page.locator("td.cellule-attr").first
            case.hover()
            case.locator("input[type=checkbox]").click()
            self.choisir_lyon(page)
            dialogue = page.locator("#confirmation")
            dialogue.wait_for(state="visible")
            self.assertIn("désélectionnée", page.locator("#confirmation-texte").inner_text())
            dialogue.locator("[data-annuler]").click()
            page.wait_for_timeout(300)
            self.assertNotIn("groupe=", page.url)  # pas de rechargement
            self.assertEqual(page.locator("td.cellule-attr input[type=checkbox]:checked").count(), 1)
            self.assertIn("Lille", page.locator("#filtre-groupe-bouton").inner_text())
            self.choisir_lyon(page)
            dialogue.wait_for(state="visible")
            dialogue.locator("[data-confirmer-ok]").click()
            page.wait_for_url("**groupe=*")
            page.wait_for_load_state("networkidle")
            self.assertIn("Lyon", page.locator("th.col-org").inner_text())
            self.assertEqual(page.erreurs, [])

    def test_sans_selection_aucune_question(self):
        with mock.patch.object(A, "MAX_COLONNES_ATTRIBUTIONS", 1):
            page = self.page()
            self.aller(page, "/administration/attributions/?niveau=Entity")
            self.choisir_lyon(page)
            page.wait_for_url("**groupe=*")
            self.assertFalse(page.locator("#confirmation").is_visible())
