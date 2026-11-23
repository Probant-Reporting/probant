"""Dans un vrai navigateur (Playwright, Chromium ; ignoré s'il manque) : « Pour moi », au clavier, contributeur. Entrée sur une
ligne ouvre le panneau et met le focus dans le panneau, sur le premier champ, pour chaque format de réponse (nombre,
pourcentage, oui / non, liste, texte rédigé, tableau) ; à la fermeture (Échap) le focus revient sur la ligne. Le format
« tableau » cache sa zone Markdown : le focus doit aller à la première cellule, pas rester sur le corps de la page."""
from parametres.models import TypeReponse
from referentiel.models import KPI, Attribution, Niveau, Utilisateur

from .aides_tests.navigateur import NavigateurBase, _hors_boucle


class PourMoiFocusPanneauNavigateurTests(NavigateurBase):
    def test_entree_sur_une_ligne_met_le_focus_dans_le_panneau(self):
        with _hors_boucle():
            contrib = Utilisateur.objects.create(username="contrib", email="contrib@exemple.test", role=Utilisateur.Role.CONTRIBUTEUR)
            liste = TypeReponse.objects.create(code="CHOIX", libelle="Choix", format="liste", valeurs=["A", "B", "C"])
            types = {
                "K_POURC": TypeReponse.objects.create(code="PCT", libelle="Pourcentage", format="pourcentage"),
                "K_OUINON": TypeReponse.objects.create(code="ON", libelle="Oui non", format="oui_non"),
                "K_LISTE": liste,
                "K_TEXTE": TypeReponse.objects.create(code="TXT", libelle="Texte", format="texte"),
                "K_TABLE": TypeReponse.objects.create(code="TAB", libelle="Tableau", format="tableau", colonnes=[
                    {"code": "nom", "libelle": {"fr": "Nom"}, "type": "texte"},
                    {"code": "val", "libelle": {"fr": "Valeur"}, "type": "nombre", "unite": "kg"}]),
            }
            for code, t in types.items():
                k = KPI.objects.create(code=code, libelle=code, type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                                       type_reponse=t, methode_agregation="Aucune")
                Attribution.objects.create(kpi=k, organisation=self.e1, utilisateur=contrib)
            Attribution.objects.create(kpi=self.eff, organisation=self.e1, utilisateur=contrib)
        page = self.page(contrib)
        self.aller(page, "/pour-moi/?tous=0")
        lignes = page.locator("#liste tr.ligne[data-url]")
        self.assertEqual(lignes.count(), 6)
        for i in range(lignes.count()):
            ligne = lignes.nth(i)
            adresse = ligne.get_attribute("data-url")
            ligne.focus()
            page.keyboard.press("Enter")
            page.wait_for_selector("body.panneau-ouvert")
            page.wait_for_function("document.activeElement && document.activeElement.closest('#panneau')")
            dedans = page.evaluate("(() => { const a = document.activeElement; return a.tagName + ' ' + (a.id || a.name || a.dataset.colonne || ''); })()")
            self.assertNotEqual(page.evaluate("document.activeElement.tagName"), "BODY", adresse)
            self.assertTrue(page.evaluate("!!document.activeElement.closest('#panneau')"), f"{adresse} : {dedans}")
            if "K_TABLE" in adresse:
                self.assertEqual(page.evaluate("document.activeElement.dataset.colonne"), "nom")  # première cellule du tableau
            elif "K_TEXTE" in adresse:
                self.assertEqual(page.evaluate("document.activeElement.tagName"), "TEXTAREA")
            page.keyboard.press("Escape")
            page.wait_for_function("!document.body.classList.contains('panneau-ouvert')")
            self.assertTrue(ligne.evaluate("el => el === document.activeElement"), f"{adresse} : le focus ne revient pas sur la ligne")
        self.assertEqual(page.erreurs, [])
