"""Dans un vrai navigateur (Playwright, Chromium ; ignoré s'il manque) : Paramètres › Santé sur téléphone (390 et 360 px), dans
les sept langues : la page ne défile pas de côté (en allemand et en néerlandais, le tableau des points dépassait de 10 à 14 px ;
viewport sans émulation tactile, qui élargirait la fenêtre au lieu de signaler le dépassement)."""
from . import aide as AI
from .aides_tests.navigateur import NavigateurBase


class SanteTelephoneSeptLanguesNavigateurTests(NavigateurBase):
    def test_pas_de_defilement_horizontal_dans_les_sept_langues(self):
        self.assertEqual(len(AI.LANGUES_GUIDES), 7)
        for largeur in (390, 360):
            for langue in AI.LANGUES_GUIDES:
                page = self.page(largeur=largeur, hauteur=800)
                self.aller(page, "/aide/")
                with page.expect_navigation():  # bouton de langue de la barre du haut (même geste que la personne)
                    page.evaluate(f"document.querySelector('button[name=langue][value=\"{langue}\"]').click()")
                page.wait_for_load_state("networkidle")
                self.aller(page, "/administration/parametres/sante/")
                self.assertEqual(page.evaluate("document.documentElement.lang"), langue)
                self.assertGreater(page.locator("table.table-sante tbody tr").count(), 0)
                self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), page.evaluate("window.innerWidth"),
                                     (langue, largeur))
                self.assertEqual(page.erreurs, [], (langue, largeur))
                page.context.close()
