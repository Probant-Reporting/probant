"""Dans un vrai navigateur (Playwright, Chromium ; ignoré s'il manque) : « Tout ce qui m'est attribué » d'une longue liste
(échelle, P-A9). Les sections repliées arrivent sans leurs lignes et le script les remplit aussitôt : à la fin, toutes les
lignes sont là, la recherche trouve une ligne d'une section repliée, « Tout déplier » les ouvre, sans erreur de script ;
axe-core sans défaut grave (si AXE_JS)."""
import os
from unittest import mock

from referentiel.models import Attribution, Utilisateur

from . import views as V
from .aides_tests.navigateur import AXE, NavigateurBase, _hors_boucle
from .test_navigateur_tableaux import REGLES_AXE


class SectionsAChargerNavigateurTests(NavigateurBase):
    def test_sections_remplies_apres_la_page(self):
        with _hors_boucle():
            contrib = Utilisateur.objects.create(username="contrib", email="contrib@exemple.test", first_name="Camille")
            for o in (self.e1, self.e2):
                Attribution.objects.create(kpi=self.eff, organisation=o, utilisateur=contrib)
        with mock.patch.object(V, "LIGNES_OUVERTES", 0):  # la première section ouverte, la seconde (Lyon) à charger
            page = self.page(contrib)
            self.aller(page, "/pour-moi/?tous=0&groupe=organisation")
            self.assertEqual(page.locator("#liste[data-url-reste]").count(), 1)  # garde : la page a bien des sections à charger
            page.wait_for_function("!document.querySelector('#liste .chargement-section')")
            self.assertEqual(page.locator("#liste tr.ligne").count(), 2)
            self.assertEqual(page.locator("#liste details.section").count(), 2)
            self.assertFalse(page.locator("#liste details.section").nth(1).evaluate("d => d.open"))
            page.locator("#recherche").fill("lyon")
            page.wait_for_function("document.querySelectorAll('#liste tr.ligne:not([hidden])').length === 1")  # filtre appliqué
            self.assertEqual(page.locator("#liste tr.ligne:not([hidden])").count(), 1)
            self.assertIn("Lyon", page.locator("#liste details.section:not([hidden]) .titre-section").inner_text())
            page.locator("#recherche").fill("")
            page.wait_for_function("document.querySelectorAll('#liste tr.ligne:not([hidden])').length === 2")  # filtre levé
            page.locator("[data-replier]").focus()
            page.keyboard.press("Enter")
            self.assertEqual(page.locator("#liste details.section[open]").count(), 2)
            if AXE and os.path.exists(AXE):
                with open(AXE, encoding="utf-8") as f:
                    page.add_script_tag(content=f.read())
                self.assertEqual(page.evaluate(REGLES_AXE), [])
            self.assertEqual(page.erreurs, [])
