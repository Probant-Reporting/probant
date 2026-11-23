"""Navigateur (Chromium) : sur téléphone (390 px), chaque ligne d'une réponse en tableau est une carte (une cellule par rangée,
le libellé de sa colonne devant), en saisie comme en lecture ; sur ordinateur, le tableau reste un tableau.

- 390 px : aucune cellule coupée à droite, aucun cadre qui défile horizontalement (ni le tableau, ni la page), libellé de
  chaque cellule écrit par la feuille de style (``data-label``), ajouter et supprimer une ligne possibles, rôles ARIA gardés.
- 1 440 px : mise en page d'origine (``display: table``).
- Tableau Markdown d'un texte rédigé et valeur de l'exercice précédent : mêmes cartes."""
import os

from parametres.models import TypeReponse
from referentiel.models import KPI, Niveau, Utilisateur

from .aides_tests.navigateur import AXE, NavigateurBase, _hors_boucle
from .models import Campagne, Reponse

REGLES_AXE = """async () => { const r = await axe.run(document, {runOnly: {type: 'tag', values:
    ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']}});
    return r.violations.filter(v => ['serious', 'critical'].includes(v.impact)).map(v => v.id + ' ' + v.nodes.map(n => n.target).join(','))}"""

MESURE = """(selecteur) => {
  const t = document.querySelector(selecteur);
  const coupes = [...t.querySelectorAll('input, td, button')].filter(e => { const q = e.getBoundingClientRect(); return q.width > 0 && (q.right > innerWidth + 1 || q.left < -1); }).length;
  const defilent = []; let el = t;
  while (el && el !== document.body) { if (el.scrollWidth > el.clientWidth + 1 && /(auto|scroll)/.test(getComputedStyle(el).overflowX)) defilent.push(el.className || el.tagName); el = el.parentElement; }
  return {coupes, defilent, page: document.documentElement.scrollWidth - innerWidth, affichage: getComputedStyle(t).display,
          etiquettes: [...t.querySelectorAll('tbody td[data-label]')].map(td => getComputedStyle(td, '::before').content),
          roles: [t.getAttribute('role'), t.querySelector('tbody tr').getAttribute('role'), t.querySelector('tbody td').getAttribute('role')]};
}"""


class TableauxCartesNavigateurTests(NavigateurBase):
    def setUp(self):
        super().setUp()
        TypeReponse.objects.create(code="POLL", libelle="Polluant", format="liste", valeurs=["Ammoniac", "Benzène", "Plomb"])
        tab = TypeReponse.objects.create(code="REJETS", libelle="Rejets", format="tableau", colonnes=[
            {"code": "polluant", "libelle": {"fr": "Polluant", "en": "Pollutant"}, "type": "liste", "liste": "POLL"},
            {"code": "air", "libelle": {"fr": "Rejets dans l'air", "en": "Emissions to air"}, "type": "nombre", "unite": "kg"},
            {"code": "eau", "libelle": {"fr": "Rejets dans l'eau", "en": "Emissions to water"}, "type": "nombre", "unite": "kg"},
            {"code": "note", "libelle": {"fr": "Remarque", "en": "Remark"}, "type": "texte"}])
        self.rej = KPI.objects.create(code="REJ", libelle="Rejets par polluant", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                                      type_reponse=tab, methode_agregation="Aucune")
        self.c = Campagne.objects.get(exercice=2026)
        self.url = f"/saisie/{self.c.pk}/REJ/{self.e1.pk}/"
        with _hors_boucle():
            Reponse.objects.create(periode=self.c.periode, kpi=self.rej, organisation=self.e1, statut="brouillon",
                                   texte="| Polluant | Rejets dans l'air | Rejets dans l'eau | Remarque |\n|---|---|---|---|\n"
                                         "| Benzène | 1,5 | 0,2 | Mesuré en continu sur le site de production principal |\n"
                                         "| Plomb | 3 | 0 | |")

    def test_cartes_en_saisie_sur_telephone(self):
        page = self.page(largeur=390, hauteur=844, tactile=True)
        self.aller(page, self.url)
        t = page.locator("[data-tableau-saisie]")
        self.assertTrue(t.is_visible())
        m = page.evaluate(MESURE, "[data-tableau-saisie]")
        self.assertEqual(m["coupes"], 0, "cellule coupée à droite")
        self.assertEqual(m["defilent"], [], "un cadre défile horizontalement")
        self.assertLessEqual(m["page"], 0)
        self.assertEqual(m["affichage"], "block")
        self.assertEqual(m["roles"], ["table", "row", "cell"])  # l'annonce « tableau, ligne, cellule » est gardée
        self.assertEqual(len(m["etiquettes"]), 8)
        self.assertTrue(all(e not in ("none", "normal", '""') for e in m["etiquettes"]), m["etiquettes"])
        # une carte : le champ de chaque cellule porte toujours son nom accessible
        self.assertEqual(page.locator("[data-lignes-tableau] tr").first.locator("input").evaluate_all("l => l.map(i => i.getAttribute('aria-label'))"),
                         ["Polluant", "Rejets dans l'air (kg)", "Rejets dans l'eau (kg)", "Remarque"])
        # ajouter une ligne, la remplir, supprimer la première
        lignes = page.locator("[data-lignes-tableau] tr")
        self.assertEqual(lignes.count(), 2)
        page.locator("[data-ajouter-ligne]").click()
        self.assertEqual(lignes.count(), 3)
        lignes.nth(2).locator("input").nth(1).fill("4")
        self.assertEqual(lignes.nth(2).locator("input").nth(1).input_value(), "4")
        lignes.nth(0).locator("[data-supprimer-ligne]").click()
        self.assertEqual(lignes.count(), 2)
        m = page.evaluate(MESURE, "[data-tableau-saisie]")
        self.assertEqual((m["coupes"], m["defilent"], m["page"] <= 0), (0, [], True))
        self._axe(page, "cartes, saisie, 390 px")
        self.assertEqual(page.erreurs, [])

    def test_cartes_en_lecture_sur_telephone(self):
        with _hors_boucle():
            auditeur = Utilisateur.objects.create(username="auditeur", email="auditeur@exemple.test", role=Utilisateur.Role.AUDITEUR)
        page = self.page(auditeur, largeur=390, hauteur=844, tactile=True)
        self.aller(page, self.url)
        m = page.evaluate(MESURE, ".reponse-redigee table, [data-tableau-saisie]")
        self.assertEqual((m["coupes"], m["defilent"], m["page"] <= 0), (0, [], True))
        self.assertEqual(page.locator(".reponse-redigee td").all_inner_texts()[:4], ["Benzène", "1,5", "0,2", "Mesuré en continu sur le site de production principal"])
        self._axe(page, "cartes, lecture, 390 px")
        self.assertEqual(page.erreurs, [])

    def test_tableau_inchange_sur_ordinateur(self):
        page = self.page(largeur=1440, hauteur=900)
        self.aller(page, self.url)
        m = page.evaluate(MESURE, "[data-tableau-saisie]")
        self.assertEqual(m["affichage"], "table")
        self.assertTrue(all(e in ("none", "normal") for e in m["etiquettes"]), "libellé de cellule écrit sur ordinateur")
        self.assertEqual(page.evaluate("getComputedStyle(document.querySelector('[data-tableau-saisie] thead')).position"), "static")
        self.assertEqual(page.evaluate("getComputedStyle(document.querySelector('[data-tableau-saisie] td')).display"), "table-cell")

    def test_tableau_markdown_d_un_texte_en_cartes(self):
        """Un tableau Markdown rédigé (texte rédigé, valeur N-1) : cellules étiquetées, cartes sur téléphone."""
        from .markdown import rendu

        html = str(rendu("| Site | Masse (t) |\n|---|---|\n| Nord | 4 |\n| Sud | |"))
        self.assertIn('<td data-label="Site">Nord</td>', html)
        self.assertIn('<td data-label="Masse (t)">4</td>', html)
        self.assertIn('<td data-label="Masse (t)"></td>', html)

    def _axe(self, page, contexte):
        if not AXE or not os.path.exists(AXE):
            return
        with open(AXE, encoding="utf-8") as f:
            page.add_script_tag(content=f.read())
        self.assertEqual(page.evaluate(REGLES_AXE), [], contexte)
