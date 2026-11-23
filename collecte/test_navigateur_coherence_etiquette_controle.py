"""Page Cohérence : l'étiquette de la colonne « Contrôle » passe à la ligne au lieu d'être coupée (Playwright, Chromium ;
ignoré s'il manque, obligatoire avec REQUIRE_BROWSER_TESTS=1).

Défaut corrigé : dans une colonne de 150 px, une étiquette longue (allemand « Vererbter Parameter geändert », portugais
« Parâmetro herdado alterado ») était coupée par « … » sur une seule ligne, à 1 440 px comme sur téléphone."""
from django.utils import timezone

from referentiel.models import Utilisateur

from .aides_tests.navigateur import NavigateurBase, _hors_boucle
from .models import Alerte, Campagne


class EtiquetteControleTests(NavigateurBase):
    def setUp(self):
        super().setUp()
        c = Campagne.objects.get(exercice=2026)
        for org in (self.e1, self.e2):
            Alerte.objects.create(campagne=c, kpi=self.eff, organisation=org, controle=Alerte.Controle.FE, message="x",
                                  date_creation=timezone.now())

    def etiquettes_entieres(self, page):
        """[(texte, largeur du texte, largeur visible, déborde de sa case)] des étiquettes de la colonne."""
        return page.locator("#alertes tbody .controle").evaluate_all("""(els) => els.map((e) => {
            const r = e.getBoundingClientRect(), td = e.closest('td').getBoundingClientRect();
            return [e.textContent, e.scrollWidth, e.clientWidth, r.right > td.right + 0.5 || r.left < td.left - 0.5]; })""")

    def test_etiquette_longue_a_la_ligne(self):
        for langue, texte in (("de", "Vererbter Parameter geändert"), ("pt", "Parâmetro herdado alterado")):
            with _hors_boucle():
                Utilisateur.objects.filter(pk=self.admin.pk).update(langue=langue)
            for largeur in (1440, 390):
                with self.subTest(langue=langue, largeur=largeur):
                    page = self.page(largeur=largeur, hauteur=900, tactile=largeur < 500)
                    self.aller(page, "/coherence/?statut=toutes")
                    etiquettes = self.etiquettes_entieres(page)
                    self.assertTrue(etiquettes)
                    for t, plein, visible, deborde in etiquettes:
                        self.assertEqual(t.strip(), texte)
                        self.assertLessEqual(plein, visible + 1, f"{t} coupée ({plein} > {visible} px)")
                        self.assertFalse(deborde, f"{t} sort de sa case")
                    self.assertEqual(page.erreurs, [])
                    page.context.close()
