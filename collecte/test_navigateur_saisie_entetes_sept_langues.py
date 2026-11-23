"""Dans un vrai navigateur (Playwright, Chromium ; ignoré s'il manque) : Saisie à 1 440 px, administrateur, dans les sept langues :
aucun en-tête de colonne n'est tronqué par « … » (en espagnol, « Desviación respecto a N-1 » et « Justificantes » dépassaient
leur colonne ; en-têtes courts du glossaire : « Desv. N-1 », « Justif. »)."""
from . import aide as AI
from .aides_tests.navigateur import NavigateurBase


class SaisieEntetesSeptLanguesNavigateurTests(NavigateurBase):
    def test_aucun_entete_tronque_dans_les_sept_langues(self):
        for langue in AI.LANGUES_GUIDES:
            page = self.page(largeur=1440, hauteur=900)
            self.aller(page, "/aide/")
            with page.expect_navigation():  # bouton de langue de la barre du haut (même geste que la personne)
                page.evaluate(f"document.querySelector('button[name=langue][value=\"{langue}\"]').click()")
            page.wait_for_load_state("networkidle")
            self.aller(page, "/saisie/")
            self.assertEqual(page.evaluate("document.documentElement.lang"), langue)
            self.assertGreater(page.locator("table th.nombre").count(), 0)
            tronques = page.evaluate("""[...document.querySelectorAll('table th')]
                .filter(t => t.offsetParent && t.scrollWidth > t.clientWidth + 1).map(t => t.innerText.trim())""")
            self.assertEqual(tronques, [], langue)
            page.context.close()
