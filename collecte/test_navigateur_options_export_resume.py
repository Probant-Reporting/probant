"""Page d'export : le résumé « Plus d'options » ne colle pas son libellé à son détail (le résumé est en flex : l'espace du gabarit
ne compte pas, il faut une marge)."""
from .aides_tests.navigateur import NavigateurBase

MESURE_ECART = """() => {
  const s = document.querySelector('details.options-export > summary');
  const detail = s.querySelector('.discret').getBoundingClientRect();
  const texte = document.createRange(); texte.selectNodeContents([...s.childNodes].find(n => n.nodeType === 3));
  return detail.left - texte.getBoundingClientRect().right;
}"""


class OptionsExportResumeNavigateurTests(NavigateurBase):
    def test_libelle_et_detail_separes_sur_ordinateur_et_telephone(self):
        for largeur in (1440, 390):
            page = self.page(self.admin, largeur=largeur, tactile=largeur < 500)
            self.aller(page, "/import-export/exporter/?nouveau=1")
            self.assertGreaterEqual(page.evaluate(MESURE_ECART), 4, largeur)
