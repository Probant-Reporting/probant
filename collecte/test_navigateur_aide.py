"""Navigateur (Chromium, ignoré s'il manque) : page d'aide (collecte/aide.py) : le lien « Aide » de la barre du haut amène à
la bonne section, les images se chargent, au clavier (Tab atteint le lien d'aide et le sommaire), sans défilement
horizontal à 390 px, accessibilité axe-core (si AXE_JS) à 1 440 et 390 px, sans erreur de script."""
from .aides_tests.navigateur import AXE, NavigateurBase, attendre_images

REGLES_AXE = """async () => { const r = await axe.run(document, {runOnly: {type: 'tag', values:
    ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']}});
    return r.violations.filter(v => ['serious', 'critical'].includes(v.impact)).map(v => v.id + ' ' + v.nodes.map(n => n.target).join(','))}"""


class AideNavigateurTests(NavigateurBase):
    def test_lien_d_aide_au_clavier_puis_page_du_guide(self):
        page = self.page()
        self.aller(page, "/tableau-de-bord/")
        lien = page.locator("a.aide-haut")
        self.assertEqual(lien.count(), 1)
        for _ in range(40):  # le lien d'aide est atteignable au clavier
            page.keyboard.press("Tab")
            if page.evaluate("document.activeElement.classList.contains('aide-haut')"):
                break
        self.assertTrue(page.evaluate("document.activeElement.classList.contains('aide-haut')"))
        with page.expect_navigation():
            page.keyboard.press("Enter")
        page.wait_for_load_state("networkidle")
        self.assertIn("/aide/#", page.url)
        self.assertGreater(page.locator(".guide-corps h2").count(), 3)
        self.assertEqual(page.erreurs, [])

    def test_images_chargees_sans_defilement_horizontal(self):
        for largeur in (1440, 390):
            page = self.page(largeur=largeur, tactile=largeur < 500)
            self.aller(page, "/aide/")
            page.evaluate("document.querySelectorAll('.guide-figure img').forEach(i => i.loading = 'eager')")
            attendre_images(page, ".guide-figure img")
            casses = page.evaluate("[...document.querySelectorAll('.guide-figure img')].filter(i => i.naturalWidth === 0).length")
            self.assertEqual(casses, 0, largeur)
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), largeur, largeur)
            self.assertEqual(page.erreurs, [])

    def test_accessibilite_axe(self):
        import os

        if not AXE or not os.path.exists(AXE):
            self.skipTest("axe-core absent (variable AXE_JS)")
        with open(AXE, encoding="utf-8") as f:
            axe = f.read()
        for largeur in (1440, 390):
            page = self.page(largeur=largeur, tactile=largeur < 500)
            self.aller(page, "/aide/")
            page.add_script_tag(content=axe)
            self.assertEqual(page.evaluate(REGLES_AXE), [], largeur)

    def test_guide_et_images_dans_chacune_des_sept_langues(self):
        """Le guide s'ouvre dans la langue de la personne, avec ses captures (celles de sa langue) et la bonne langue de texte."""
        from . import aide as AI

        for langue in AI.LANGUES_GUIDES:
            page = self.page(largeur=390, tactile=True)
            self.aller(page, "/aide/")
            with page.expect_navigation():  # bouton de langue de la barre du haut (même geste que la personne)
                page.evaluate(f"document.querySelector('button[name=langue][value=\"{langue}\"]').click()")
            page.wait_for_load_state("networkidle")
            self.aller(page, "/aide/")
            self.assertEqual(page.evaluate("document.querySelector('.guide-corps').lang"), langue)
            self.assertIn(f"/aide/images/{langue}/", page.evaluate("document.querySelector('.guide-figure img').src"), langue)
            page.evaluate("document.querySelectorAll('.guide-figure img').forEach(i => i.loading = 'eager')")
            attendre_images(page, ".guide-figure img")
            self.assertEqual(page.evaluate("[...document.querySelectorAll('.guide-figure img')].filter(i => i.naturalWidth === 0).length"),
                             0, langue)
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 390, langue)
            self.assertEqual(page.erreurs, [], langue)
