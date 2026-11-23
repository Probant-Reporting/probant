"""Mon compte › Assistants, jeton créé : le focus va sur le titre du bloc du jeton (jamais perdu sur ``body``) ; « Copier »
annonce « Copié » dans une zone ``aria-live`` qui existe déjà quand on appuie, au clavier."""
from collecte.aides_tests.navigateur import NavigateurBase

from .models import ReglageMCP


class JetonFocusCopieTests(NavigateurBase):
    def setUp(self):
        super().setUp()
        ReglageMCP.objects.update_or_create(pk=1, defaults={"actif": True, "ecriture": True, "appels_minute": 600})

    def test_focus_sur_le_titre_puis_copie_annoncee(self):
        page = self.page(self.admin)
        page.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=self.live_server_url)
        self.aller(page, "/mon-compte/")
        page.fill("#jeton-nom", "Mon assistant")
        page.focus("#jeton-nom")
        with page.expect_navigation():
            page.keyboard.press("Enter")
        page.wait_for_selector("#jeton-nouveau")
        page.wait_for_function("document.activeElement.id === 'titre-nouveau-jeton'")  # une fois la page chargée
        actif = page.evaluate("({id: document.activeElement.id, tag: document.activeElement.tagName})")
        self.assertEqual(actif, {"id": "titre-nouveau-jeton", "tag": "H3"})
        zone = page.locator("[data-annonce-copie]")
        self.assertEqual(zone.count(), 1)
        self.assertEqual(zone.get_attribute("aria-live"), "polite")
        self.assertEqual(zone.inner_text(), "")
        # au clavier : Tab jusqu'au bouton « Copier » du jeton, puis Entrée
        for _ in range(3):
            page.keyboard.press("Tab")
            if page.evaluate("document.activeElement.dataset.copier") == "#jeton-nouveau":
                break
        self.assertEqual(page.evaluate("document.activeElement.dataset.copier"), "#jeton-nouveau")
        page.keyboard.press("Enter")
        page.wait_for_function("document.querySelector('[data-annonce-copie]').textContent.trim() !== ''")
        self.assertEqual(zone.inner_text(), "Copié")
        self.assertEqual(page.erreurs, [])
