"""Navigateur : réponse en tableau dans le panneau de saisie (ajouter, remplir au clavier, filtrer une liste, supprimer une
ligne, brouillon enregistré, valeurs relues, N/A qui désactive le tableau) et page Import / Export › Formats officiels ;
accessibilité (axe-core si AXE_JS) à 1 440 et 390 px, sans erreur de script."""
import os

from parametres.models import TypeReponse
from referentiel.models import KPI, Niveau, Utilisateur

from . import paquets as P
from .aides_tests.navigateur import AXE, NavigateurBase, _hors_boucle
from .models import Campagne, Reponse

REGLES_AXE = """async () => { const r = await axe.run(document, {runOnly: {type: 'tag', values:
    ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']}});
    return r.violations.filter(v => ['serious', 'critical'].includes(v.impact)).map(v => v.id + ' ' + v.nodes.map(n => n.target).join(','))}"""


class TableauNavigateurTests(NavigateurBase):
    def setUp(self):
        super().setUp()
        TypeReponse.objects.create(code="POLL", libelle="Polluant", format="liste", valeurs=["Ammoniac", "Benzène", "Plomb"],
                                   traductions={"en": {"valeurs": ["Ammonia", "Benzene", "Lead"]}})
        tab = TypeReponse.objects.create(code="REJETS", libelle="Rejets", format="tableau", colonnes=[
            {"code": "polluant", "libelle": {"fr": "Polluant", "en": "Pollutant"}, "type": "liste", "liste": "POLL"},
            {"code": "air", "libelle": {"fr": "Rejets dans l'air", "en": "Emissions to air"}, "type": "nombre", "unite": "kg"}])
        self.rej = KPI.objects.create(code="REJ", libelle="Rejets par polluant", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                                      type_reponse=tab, methode_agregation="Aucune")
        self.c = Campagne.objects.get(exercice=2026)
        self.url = f"/saisie/{self.c.pk}/REJ/{self.e1.pk}/"

    def axe(self, page, contexte):
        if not AXE or not os.path.exists(AXE):
            return
        with open(AXE, encoding="utf-8") as f:
            page.add_script_tag(content=f.read())
        self.assertEqual(page.evaluate(REGLES_AXE), [], contexte)

    def test_saisir_un_tableau_au_clavier(self):
        page = self.page()
        self.aller(page, self.url)
        editeur = page.locator("[data-editeur-tableau]")
        self.assertTrue(editeur.locator("[data-tableau-saisie]").is_visible())
        self.assertFalse(editeur.locator("[data-zone-tableau]").is_visible())  # la zone Markdown est cachée par le script
        lignes = editeur.locator("[data-lignes-tableau] tr")
        self.assertEqual(lignes.count(), 1)  # une ligne vide prête à remplir
        lignes.nth(0).locator("input").nth(0).fill("Ammoniac")
        lignes.nth(0).locator("input").nth(1).fill("12,5")
        page.keyboard.press("Tab")
        bouton = editeur.locator("[data-ajouter-ligne]")
        bouton.focus()
        page.keyboard.press("Enter")
        self.assertEqual(lignes.count(), 2)
        self.assertEqual(page.evaluate("document.activeElement.dataset.colonne"), "polluant")  # le focus va dans la nouvelle ligne
        page.keyboard.type("Lead")  # valeur écrite dans une autre langue de l'installation : relue par le serveur
        page.keyboard.press("Tab")
        page.keyboard.type("3")
        self.assertIn("2 lignes remplies", editeur.locator("[data-compte-lignes]").inner_text())
        self.axe(page, "éditeur rempli, 1 440 px")
        # supprimer la première ligne : le focus reste dans le tableau
        lignes.nth(0).locator("[data-supprimer-ligne]").click()
        self.assertEqual(lignes.count(), 1)
        page.locator("button[name=action][value=enregistrer]").first.click()
        page.wait_for_selector("text=Brouillon enregistré")
        with _hors_boucle():
            r = Reponse.objects.get(kpi=self.rej, organisation=self.e1)
        self.assertEqual(r.texte.split("\n")[2], "| Plomb | 3 |")
        # rouvert : la ligne revient, nombre avec la virgule ; N/A désactive le tableau
        self.aller(page, self.url)
        self.assertEqual([i.input_value() for i in editeur.locator("[data-lignes-tableau] input").all()], ["Plomb", "3"])
        page.locator("[data-na]").check(force=True)
        self.assertTrue(editeur.locator("[data-ajouter-ligne]").is_disabled())
        self.assertTrue(editeur.locator("[data-lignes-tableau] input").first.is_disabled())
        self.assertEqual(page.erreurs, [])

    def test_telephone_et_lecture_seule(self):
        with _hors_boucle():
            Reponse.objects.create(periode=self.c.periode, kpi=self.rej, organisation=self.e1, texte="| Polluant | Air |\n|---|---|\n| Benzène | 1.5 |")
        page = self.page(largeur=390, hauteur=844)
        self.aller(page, self.url)
        self.assertTrue(page.locator("[data-tableau-saisie]").is_visible())
        largeur = page.evaluate("document.documentElement.scrollWidth")
        self.assertLessEqual(largeur, 390)  # le tableau défile dans son cadre, pas la page
        self.axe(page, "éditeur, 390 px")
        with _hors_boucle():
            auditeur = Utilisateur.objects.create(username="auditeur", email="auditeur@exemple.test", role=Utilisateur.Role.AUDITEUR)
        lecteur = self.page(auditeur)  # lecture seule : le tableau est affiché, sans champ
        self.aller(lecteur, self.url)
        self.assertEqual(lecteur.locator(".reponse-redigee td").all_inner_texts(), ["Benzène", "1,5"])
        self.assertEqual(lecteur.locator(".reponse-redigee input").count(), 0)
        self.axe(lecteur, "lecture seule")
        self.assertEqual(page.erreurs + lecteur.erreurs, [])

    def test_page_formats_officiels(self):
        with _hors_boucle():
            for f in ("vs_base.json", "vs_complet.json"):
                P.appliquer(None, P.analyser(P.fourni(f).paquet, fourni=True))
        for largeur in (1440, 390):
            page = self.page(largeur=largeur)
            self.aller(page, "/import-export/formats-officiels/")
            self.assertTrue(page.locator("select[name=format]").is_visible())
            self.axe(page, f"formats officiels, {largeur} px")
            page.locator("button[value=verifier]").click()
            page.wait_for_load_state("networkidle")
            self.axe(page, f"rapport, {largeur} px")
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), largeur)
            self.assertEqual(page.erreurs, [])
