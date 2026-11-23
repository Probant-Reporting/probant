"""Tableaux « .defile-x » : un texte réservé aux lecteurs d'écran (``.visuellement-cache``, en position absolue) ne fait pas
défiler la page à 390 px (cadre du défilement = bloc de référence de ce texte)."""
from django.core.files.base import ContentFile

from parametres.models import Instance

from .aides_tests.navigateur import NavigateurBase
from .models import Preuve, Reponse


class DefileXTexteCacheTests(NavigateurBase):
    def setUp(self):
        super().setUp()
        self.eff.confidentialite = self.eff.Confidentialite.RESTREINT
        self.eff.save()
        i = Instance.courante()
        i.preuves_sensibles_mois = 1
        i.save()
        for k in range(8):
            r = Reponse.objects.get(periode=self.campagnes[0].periode, kpi=self.eff, organisation=self.e1)
            nom = f"facture-numero-{k}-avec-un-nom-de-fichier-assez-long.pdf"
            Preuve.objects.create(reponse=r, fichier=ContentFile(b"%PDF-1.4 essai", name=nom), nom_fichier=nom, depose_par=self.admin)

    def test_pas_de_defilement_horizontal_de_la_page(self):
        page = self.page(self.admin, largeur=390, hauteur=844, tactile=True)
        self.aller(page, "/administration/preuves/")
        self.assertGreater(page.locator("table.table-preuves tbody tr, table.table-preuves tr").count(), 2)
        self.assertEqual(page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth"), 0)

    def test_le_cadre_du_defilement_est_le_bloc_de_reference(self):
        page = self.page(self.admin, largeur=390, hauteur=844)
        self.aller(page, "/administration/preuves/")
        fautifs = page.evaluate("""() => [...document.querySelectorAll('.defile-x')].filter(
            e => getComputedStyle(e).position === 'static' && e.querySelector('.visuellement-cache')).length""")
        self.assertEqual(fautifs, 0)
