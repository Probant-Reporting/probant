"""Historique des connexions, Mon compte (dernières connexions) et Santé de l'installation dans un vrai navigateur
 à 1 440 et 390 px, sans défilement horizontal ni erreur de script, accessibilité axe-core (si AXE_JS)."""
import os

from .aides_tests.navigateur import AXE, NavigateurBase, _hors_boucle
from .test_navigateur_aide import REGLES_AXE

PAGES = ("/administration/comptes/connexions/", "/mon-compte/", "/administration/parametres/sante/",
         "/administration/parametres/hebergement/")


class ConnexionsSanteNavigateurTests(NavigateurBase):
    def setUp(self):
        super().setUp()
        from referentiel import historique_connexions as HC

        with _hors_boucle():
            HC.noter("reussie", utilisateur=self.admin)
            HC.noter("echec", "admin@exemple.test")
            HC.noter("bloquee", "<b>inconnu</b>")

    def test_pages_sans_debordement_ni_erreur(self):
        for largeur in (1440, 390):
            page = self.page(largeur=largeur, tactile=largeur < 500)
            for chemin in PAGES:
                self.aller(page, chemin)
                self.assertFalse(page.evaluate("document.documentElement.scrollWidth > window.innerWidth"), (chemin, largeur))
                self.assertEqual(page.erreurs, [], chemin)
            self.aller(page, PAGES[0])
            self.assertEqual(page.locator(".table-connexions tbody tr").count(), 3)
            self.assertEqual(page.locator("text=<b>inconnu</b>").count(), 0)  # l'identifiant tapé n'est jamais affiché

    def test_accessibilite(self):
        if not AXE or not os.path.exists(AXE):
            self.skipTest("axe-core absent (variable AXE_JS)")
        with open(AXE, encoding="utf-8") as f:
            axe = f.read()
        for largeur in (1440, 390):
            page = self.page(largeur=largeur, tactile=largeur < 500)
            for chemin in PAGES:
                self.aller(page, chemin)
                page.add_script_tag(content=axe)
                self.assertEqual(page.evaluate(REGLES_AXE), [], (chemin, largeur))
