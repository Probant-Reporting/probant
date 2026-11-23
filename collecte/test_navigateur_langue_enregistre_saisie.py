"""Dans un vrai navigateur (Playwright, Chromium ; ignoré s'il manque) : une valeur tapée
dans la saisie d'une case (pleine page : le panneau, lui, rend le reste de la page inerte), pas encore enregistrée, n'est plus perdue quand la personne change de langue dans la barre du
haut : elle est enregistrée d'abord (même chemin que l'enregistrement automatique), puis la langue change. Si
l'enregistrement est refusé (valeur illisible), la langue ne change pas et l'erreur reste à l'écran."""
from . import test_navigateur_saisie as TNS
from .models import Reponse


class LangueApresEnregistrementTests(TNS.PanneauNavigateurTests):
    def pleine_page(self):
        from django.urls import reverse

        return reverse("collecte:cellule", args=[self.c.pk, self.nb.code, self.e1.pk])

    def changer_langue(self, page, code):
        menu = page.locator("details.menu-langue:visible").first
        menu.locator("summary").click()
        menu.locator(f'button[name=langue][value="{code}"]').click()

    def test_valeur_tapee_enregistree_avant_le_changement_de_langue(self):
        page = self.page()
        self.aller(page, self.pleine_page())
        ordre = []  # enregistrement terminé AVANT l'envoi du changement de langue : aucune course
        page.on("requestfinished", lambda r: ordre.append("enregistre") if r.method == "POST" and "/saisie/" in r.url else None)
        page.on("request", lambda r: ordre.append("langue") if r.method == "POST" and r.url.rstrip("/").endswith("/langue") else None)
        page.locator(".page-cellule #valeur").fill("4321")
        self.changer_langue(page, "en")
        page.wait_for_function("document.documentElement.lang === 'en'")
        page.wait_for_load_state("networkidle")
        r = Reponse.objects.get(periode=self.c.periode, kpi=self.nb, organisation=self.e1)
        self.assertEqual(r.valeur, 4321)
        self.assertEqual(r.statut, Reponse.Statut.BROUILLON)
        # la page rechargée dans l'autre langue montre la valeur enregistrée (pas l'ancienne)
        self.assertEqual("".join(ch for ch in page.locator(".page-cellule #valeur").input_value() if ch.isdigit()), "4321")
        self.assertEqual(page.dialogues, [])  # aucun « Quitter la page ? »
        self.assertEqual(ordre[:2], ["enregistre", "langue"])

    def test_valeur_refusee_la_langue_ne_change_pas(self):
        page = self.page()
        self.aller(page, self.pleine_page())
        page.locator(".page-cellule #valeur").fill("douze")
        self.changer_langue(page, "en")
        page.wait_for_selector(".page-cellule [data-repere-annonce]:not(:empty)")
        page.wait_for_timeout(500)
        self.assertEqual(page.evaluate("document.documentElement.lang"), "fr")
        self.assertEqual(page.locator(".page-cellule #valeur").input_value(), "douze")
        self.assertTrue(page.evaluate("document.activeElement && document.activeElement.id === 'valeur'"))
        self.assertEqual(page.dialogues, [])


for _nom in dir(TNS.PanneauNavigateurTests):  # les tests de la classe de base tournent dans leur propre fichier
    if _nom.startswith("test_"):
        setattr(LangueApresEnregistrementTests, _nom, None)
