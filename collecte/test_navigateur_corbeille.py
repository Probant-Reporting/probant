"""Dans un vrai navigateur (Playwright, Chromium ; ignoré s'il manque) : « Supprimé : X. Annuler » après une suppression
sans question (focus sur « Annuler », reste tant qu'il a le focus, puis 10 secondes, Échap le ferme), et colonnes
triables (bouton dans l'en-tête, aria-sort, adresse, arbre trié par niveau, vides en dernier)."""
from .models import ReglageExport, SelectionKPI
from .aides_tests.navigateur import _hors_boucle
from .aides_tests.navigateur import ATTENTE_LONGUE, NavigateurBase


class AnnulationTests(NavigateurBase):
    def test_supprimer_un_export_puis_annuler_au_clavier(self):
        with _hors_boucle():
            r = ReglageExport.objects.create(nom="Pour le comité", proprietaire=self.admin, parametres={}, ordre=99)
        page = self.page()
        page.clock.install()
        page.clock.resume()  # le temps passe normalement ; run_for avance d'un coup (minuteur du message)
        self.aller(page, "/import-export/")
        page.get_by_role("button", name="Supprimer « Pour le comité »").click()
        page.wait_for_load_state("networkidle")
        zone = page.locator("#annulation")
        zone.locator("button").wait_for(timeout=ATTENTE_LONGUE)
        self.assertEqual(zone.get_attribute("role"), "status")
        self.assertIn("Pour le comité", zone.inner_text())
        self.assertEqual(page.locator(".nom-export", has_text="Pour le comité").count(), 0)
        self.assertEqual(page.evaluate("document.activeElement.className"), "lien-annulation")  # focus sur « Annuler »
        page.clock.run_for(15000)
        self.assertTrue(zone.locator("button").is_visible())  # reste tant qu'il a le focus
        page.keyboard.press("Tab")
        page.clock.run_for(5000)
        self.assertTrue(zone.locator("button").is_visible())
        page.clock.run_for(6000)
        self.assertEqual(zone.locator("button").count(), 0)  # 10 secondes après avoir quitté le message
        with _hors_boucle():
            self.assertFalse(ReglageExport.objects.filter(pk=r.pk).exists())
            r.restaurer()
        page.reload()
        # de nouveau, et cette fois « Annuler » au clavier : l'export revient
        page.get_by_role("button", name="Supprimer « Pour le comité »").click()
        page.wait_for_load_state("networkidle")
        zone.locator("button").wait_for(timeout=ATTENTE_LONGUE)
        with page.expect_navigation():
            page.keyboard.press("Enter")
        self.assertEqual(page.locator(".nom-export", has_text="Pour le comité").count(), 1)
        self.assertIn("Pour le comité", page.locator(".messages").inner_text())
        self.assertEqual(page.erreurs, [])

    def test_constructeur_sans_supprimer_la_liste_et_coller_des_codes(self):
        """Une liste se supprime seulement dans l'onglet Listes de KPI ; « Coller des codes KPI »
        coche les KPI reconnus et nomme les codes inconnus."""
        with _hors_boucle():
            s = SelectionKPI.objects.create(nom="Essentiels", proprietaire=self.admin)
            s.kpis.set(["EFF"])
        page = self.page()
        self.aller(page, "/import-export/exporter/?nouveau=1")
        page.locator('input[name="choix_kpi"][value="liste"]').check(force=True)
        self.assertEqual(page.locator("[data-supprimer-liste]").count(), 0)
        page.locator('input[name="choix_kpi"][value="choix"]').check(force=True)
        page.locator(".si-choix .coller-codes summary").click()
        page.locator("[data-codes-colles]").fill("eff ; INCONNU-1")
        page.locator("[data-cocher-codes]").click()
        self.assertTrue(page.locator('input[name="kpis"][value="EFF"]').is_checked())
        self.assertIn("INCONNU-1", page.locator("[data-codes-resultat]").inner_text())
        self.assertEqual(page.erreurs, [])


class TriTests(NavigateurBase):
    def test_tableau_de_bord_trie_dans_l_arbre(self):
        page = self.page()
        self.aller(page, "/tableau-de-bord/")
        entete = page.locator('#table-orgs th[data-tri-col="organisation"]')
        bouton = entete.locator("button.tri-entete")
        self.assertIsNone(entete.get_attribute("aria-sort"))
        bouton.click()
        self.assertEqual(entete.get_attribute("aria-sort"), "ascending")
        bouton.click()
        self.assertEqual(entete.get_attribute("aria-sort"), "descending")
        self.assertIn("tri-table-orgs=-organisation", page.url)
        noms = page.eval_on_selector_all("#table-orgs tbody tr", "l => l.map(tr => tr.cells[0].dataset.tri)")
        self.assertEqual(noms, ["Groupe", "Pays", "Lyon", "Lille"])  # la hiérarchie reste, chaque niveau trié
        page.reload()
        self.assertEqual(entete.get_attribute("aria-sort"), "descending")  # gardé dans l'adresse
        # le tri annoncé aux lecteurs d'écran ; au clavier, Entrée sur le titre
        bouton.focus()
        page.keyboard.press("Enter")
        self.assertEqual(entete.get_attribute("aria-sort"), "ascending")
        self.assertEqual(page.erreurs, [])

    def test_comptes_par_derniere_connexion_vides_en_dernier(self):
        from django.utils import timezone

        from referentiel.models import Utilisateur

        with _hors_boucle():
            Utilisateur.objects.filter(pk=self.admin.pk).update(last_login=timezone.now())
            Utilisateur.objects.create(username="zoe", first_name="Zoé", email="zoe@exemple.test", is_active=True)
        page = self.page()
        self.aller(page, "/administration/comptes/")
        bouton = page.locator('#table-comptes th[data-tri-col="connexion"] button')
        bouton.click()
        bouton.click()  # décroissant : les vides restent en dernier
        ordre = page.eval_on_selector_all("#table-comptes tbody tr", "l => l.map(tr => tr.cells[4].dataset.tri)")
        self.assertTrue(ordre[0])
        self.assertEqual(ordre[-1], "")
        page.locator('#table-comptes th[data-tri-col="personne"] button').click()
        noms = page.eval_on_selector_all("#table-comptes tbody tr", "l => l.map(tr => tr.cells[1].dataset.tri)")
        self.assertEqual(noms, sorted(noms, key=lambda n: n.lower()))
        self.assertEqual(page.erreurs, [])
