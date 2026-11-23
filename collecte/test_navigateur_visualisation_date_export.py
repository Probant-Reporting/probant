"""Date des images exportées de la Visualisation (PNG) : celle de l'installation (fuseau ``TIME_ZONE``), écrite comme
toute date courte de la langue (``collecte/dates_courtes.py``, clé ``format.date_courte``), comme l'export Excel.

Avant : le nom du fichier prenait la date en temps universel du navigateur (``toISOString``, la veille entre minuit et
1 h ou 2 h à Bruxelles) et la ligne « Source : … exported on … » la date du navigateur dans le format de son moteur
(« 11/16/2026 » en anglais, mois d'abord : le format ambigu que l'outil évite partout ailleurs)."""
from django.utils import timezone

from referentiel.models import Utilisateur

from . import dates_courtes as DC
from .aides_tests.navigateur import _hors_boucle
from .aides_tests.navigateur import NavigateurBase

# horloge du navigateur arrêtée sur une autre date : seule la date donnée par le serveur doit apparaître
HORLOGE = """(() => {
  const Vrai = Date, fixe = Vrai.UTC(2001, 1, 3, 23, 30);
  class Faux extends Vrai { constructor(...a) { super(...(a.length ? a : [fixe])); } static now() { return fixe; } }
  window.Date = Faux;
  window.__textes = [];
  const f = CanvasRenderingContext2D.prototype.fillText;
  CanvasRenderingContext2D.prototype.fillText = function (t, ...r) { window.__textes.push(String(t)); return f.call(this, t, ...r); };
})();"""


class DateDesImagesExportees(NavigateurBase):
    def setUp(self):
        super().setUp()
        from .models import VueVisu

        with _hors_boucle():
            Utilisateur.objects.filter(pk=self.lecteur.pk).update(langue="en")
            self.vue = VueVisu.objects.create(nom="Comite", partage=True, proprietaire=self.admin, visuels=[
                {"id": "a", "type": "chiffre", "kpis": ["EFF"], "largeur": 3, "hauteur": "m"}])

    def test_date_de_l_installation_dans_le_format_de_la_langue(self):
        with _hors_boucle():
            self.lecteur.refresh_from_db()
            jour = timezone.localdate()
            texte = DC.date_courte(jour, "en")
        page = self.page(self.lecteur)
        page.add_init_script(HORLOGE)
        self.aller(page, f"/visualisation/vues/{self.vue.pk}/")
        page.wait_for_selector(".forme-chiffre .valeur-chiffre")
        page.locator(".forme-chiffre summary").click()
        with page.expect_download() as d:
            page.locator('.forme-chiffre [data-action="png"]').click()
        self.assertEqual(d.value.suggested_filename, f"Visualisation_Comite_Effectif_{jour.isoformat()}.png")
        source = [t for t in page.evaluate("window.__textes") if t.startswith("Source")]
        self.assertEqual(len(source), 1, page.evaluate("window.__textes"))
        self.assertTrue(source[0].endswith(f"exported on {texte}"), source[0])
        self.assertEqual(page.erreurs, [])
