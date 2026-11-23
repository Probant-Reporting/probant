"""Page Paramètres › Unités : les thématiques d'unités que les modèles fournis écrivent (« Facteur d'émission », « Conversion »,
« Comptage ») se rangent dans la thématique du catalogue qui leur correspond, donc se traduisent ; la ligne de résumé d'une
thématique montre le symbole dans la langue de l'interface (« Tage », pas « jours »)."""
from django.test import SimpleTestCase

from . import catalogue_unites as CU
from .aides_tests.referentiel import URL, Base
from .models import Langue, Unite


class ThematiquesHistoriquesTests(SimpleTestCase):
    def test_correspondance_avec_le_catalogue(self):
        self.assertEqual(CU.theme_du_catalogue("Facteur d'émission"), "Intensités")
        self.assertEqual(CU.theme_du_catalogue(" conversion "), "Intensités")
        self.assertEqual(CU.theme_du_catalogue("Comptage"), "Comptages")
        self.assertEqual(CU.theme_du_catalogue("Durée"), "Durée")
        self.assertIsNone(CU.theme_du_catalogue("Ma thématique"))
        self.assertEqual(CU.nom_theme("Facteur d'émission", "en"), "Intensities")
        self.assertEqual(CU.nom_theme("Comptage", "de"), "Anzahlen")


class PageUnitesEnAllemandTests(Base):
    def test_thematiques_et_symboles_dans_la_langue_de_l_interface(self):
        Langue.objects.get_or_create(code="de", defaults={"libelle": "Deutsch", "ordre": 4})
        Unite.objects.update_or_create(code="jours", defaults=dict(symbole="jours", libelle="jours", famille="Durée",
                                                                   traductions={"de": {"symbole": "Tage"}}))
        Unite.objects.update_or_create(code="cas", defaults=dict(symbole="cas", libelle="cas", famille="Comptage", entier=True,
                                                                 traductions={"de": {"symbole": "Fälle"}}))
        Unite.objects.update_or_create(code="kWh/L", defaults=dict(symbole="kWh/L", libelle="kilowattheure par litre", famille="Conversion"))
        Unite.objects.update_or_create(code="kgCO2e/L", defaults=dict(symbole="kgCO2e/L", libelle="kilogramme par litre",
                                                                      famille="Facteur d'émission"))
        self.admin.langue = "de"
        self.admin.save()
        self.client.force_login(self.admin)
        page = self.client.get(f"{URL}?section=unites").content.decode()
        resumes = page.split('<span class="nom-theme">')[1:]
        noms = [r.split("</span>")[0] for r in resumes]
        self.assertIn("Anzahlen", noms)
        self.assertIn("Intensitäten", noms)
        self.assertEqual(len(noms), len(set(noms)), noms)  # une seule rangée par thématique, pas de doublon
        for francais in ("Facteur d'émission", "Conversion", "Comptage"):
            self.assertNotIn(f'<span class="nom-theme">{francais}</span>', page)
        symboles = " ".join(s.split("</span>")[0] for s in page.split('class="symboles-theme">')[1:])
        self.assertIn("Tage", symboles)
        self.assertIn("Fälle", symboles)
        self.assertNotIn("jours", symboles)
