"""Dans un vrai navigateur (Playwright, Chromium ; ignoré s'il manque) : Administration › Attributions, choix
« Validateurs » (règle du projet). Au clavier seul : choisir Validateurs dans la barre de filtres, cocher
une case, « Attribuer un validateur… », choisir la personne ; seuls les validateurs et administrateurs sont proposés ; la
case du pays nomme le validateur, celles des entités du dessous disent « via Pays » ; axe-core sans défaut grave (si
AXE_JS) ; sur téléphone (390 px), la page ne défile pas en largeur."""
import os
import re

from referentiel.models import Attribution, Utilisateur

from .aides_tests.navigateur import AXE, NavigateurBase
from .models import Journal


class ChoixValidateursTests(NavigateurBase):
    def setUp(self):
        super().setUp()
        self.vera = Utilisateur.objects.create(username="vera", first_name="Vera", last_name="Valide", email="vera@exemple.test",
                                               role=Utilisateur.Role.VALIDATEUR)
        self.camille = Utilisateur.objects.create(username="camille", first_name="Camille", last_name="Contrib",
                                                  email="camille@exemple.test")

    def axe(self, page, ou):
        if not (AXE and os.path.exists(AXE)):
            return
        from .test_navigateur_tableaux import REGLES_AXE

        with open(AXE, encoding="utf-8") as f:
            page.add_script_tag(content=f.read())
        self.assertEqual(page.evaluate(REGLES_AXE), [], ou)

    def test_au_clavier_donner_un_validateur(self):
        page = self.page()
        self.aller(page, "/administration/attributions/?niveau=Entity")
        self.assertEqual(page.locator("[data-grille]").get_attribute("data-role-attr"), "contributeur")
        # choix « Validateurs » au clavier : la page se recharge sur la grille des validateurs, le focus revient au champ
        page.locator("#filtre-role-bouton").focus()
        page.keyboard.press("ArrowDown")
        choix = page.get_by_role("radio", name=re.compile("Validat"))
        choix.focus()
        page.keyboard.press("Space")
        page.wait_for_url("**role=validateur*")
        page.wait_for_load_state("networkidle")
        self.assertEqual(page.locator("[data-grille]").get_attribute("data-role-attr"), "validateur")
        self.assertEqual(page.evaluate("document.activeElement && document.activeElement.id"), "filtre-role-bouton")
        self.assertTrue(page.locator("#intro-validateurs").is_visible())
        self.axe(page, "1 440 px, Validateurs")
        # onglet du pays (lien des cartes de niveau), puis une case cochée au clavier et « Attribuer un validateur… »
        self.aller(page, "/administration/attributions/?niveau=Country")
        case = page.locator(f'td[data-cle="EFF|{self.p.pk}"] .choix-case')
        case.focus()
        page.keyboard.press("Space")
        bouton = page.locator("#barre-masse [data-masse=attribuer]")
        bouton.wait_for(state="visible")
        self.assertIn("validat", bouton.inner_text().lower())
        bouton.focus()
        page.keyboard.press("Enter")
        page.locator("#choix-spoc.ouvert").wait_for()
        noms = page.locator("#choix-spoc ul button .nom-personne").all_inner_texts()
        self.assertTrue(any("Vera" in n for n in noms), noms)
        self.assertFalse(any("Camille" in n for n in noms), noms)  # un contributeur n'est jamais proposé comme validateur
        page.keyboard.type("Vera")
        page.keyboard.press("ArrowDown")
        page.keyboard.press("Enter")
        page.wait_for_function(f"document.querySelector('td[data-cle=\"EFF|{self.p.pk}\"]').dataset.spocs === '{self.vera.pk}'")
        self.assertTrue(Attribution.objects.filter(kpi_id="EFF", organisation=self.p, utilisateur=self.vera,
                                                   role=Attribution.Role.VALIDATEUR).exists())
        self.assertEqual(Journal.objects.filter(action="attribution_validateur").count(), 1)
        # entités du dessous : couvertes par le pays, « via Pays »
        self.aller(page, "/administration/attributions/?niveau=Entity")
        via = page.locator(f'td.par-dessus[data-cle="EFF|{self.e1.pk}"] .via-dessus')
        self.assertIn("Pays", via.inner_text())
        self.axe(page, "1 440 px, entités couvertes")
        tel = self.page(largeur=390, hauteur=800, tactile=True)
        self.aller(tel, "/administration/attributions/?role=validateur&niveau=Entity")
        self.assertTrue(tel.locator("#filtre-role-bouton").is_visible())
        self.assertLessEqual(tel.evaluate("document.documentElement.scrollWidth"), 390)
        self.assertEqual(page.erreurs + tel.erreurs, [])
