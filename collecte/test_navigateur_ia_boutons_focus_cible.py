"""Dans un vrai navigateur (Playwright, Chromium ; ignoré s'il manque) : boutons de l'assistant IA (seconde recette, B10).
- Sur téléphone (390 px), « Expliquer avec l'IA » et « Proposer avec l'IA » font au moins 44 px de haut (DESIGN.md : cible
  tactile) ; avant, la règle des boutons compacts (30 px) l'emportait.
- Après « Proposer avec l'IA » (Traductions), le focus revient sur le bouton (il était désactivé pendant la demande et le
  focus retombait sur ``body``)."""
from parametres.aides_tests.ia import AvecIA
from parametres.models import Langue

from .aides_tests.navigateur import NavigateurBase


class BoutonsIATests(AvecIA, NavigateurBase):
    def setUp(self):
        super().setUp()
        Langue.objects.get_or_create(code="es", defaults={"libelle": "Español", "ordre": 3})
        self.allumer()

    def test_focus_rendu_au_bouton_et_cible_de_44_px(self):
        page = self.page()
        self.aller(page, "/administration/parametres/langues/es/traductions/?section=kpi")
        bouton = page.locator("[data-ia-traductions]")
        bouton.wait_for(state="visible")
        bouton.focus()
        page.keyboard.press("Enter")
        page.locator("#ia-traductions-etat .ia-etat").wait_for(state="visible")
        page.wait_for_function("() => !document.querySelector('[data-ia-traductions]').disabled")
        self.assertEqual(page.evaluate("document.activeElement && document.activeElement.matches('[data-ia-traductions]')"), True)
        tel = self.page(largeur=390, hauteur=800, tactile=True)
        self.aller(tel, "/administration/parametres/langues/es/traductions/?section=kpi")
        b = tel.locator("[data-ia-traductions]")
        b.wait_for(state="visible")
        self.assertGreaterEqual(b.bounding_box()["height"], 44)
        self.assertEqual(page.erreurs + tel.erreurs, [])
