"""Validation d'un thème (``Theme.clean``) : un sous-thème normal (nouveau ou déjà enregistré, à plusieurs niveaux) est
accepté ; seul un parent qui ramène au thème lui-même (boucle) ou un parent d'un autre référentiel est refusé."""
from django.core.exceptions import ValidationError
from django.test import TestCase

from .models import Referentiel, Theme


class ThemeCleanTests(TestCase):
    def setUp(self):
        self.ref = Referentiel.objects.create(code="REF", nom="Référentiel", frequence="annee")
        self.env = Theme.objects.create(referentiel=self.ref, code="ENV", nom="Environnement")

    def test_sous_themes_normaux_acceptes(self):
        nouveau = Theme(referentiel=self.ref, code="EAU", nom="Eau", parent=self.env)
        nouveau.full_clean()  # sous-thème pas encore enregistré
        nouveau.save()
        petit = Theme.objects.create(referentiel=self.ref, code="EAU-P", nom="Eau potable", parent=nouveau)
        petit.full_clean()  # sous-sous-thème déjà enregistré, revalidé
        nouveau.full_clean()

    def test_boucle_et_autre_referentiel_refuses(self):
        eau = Theme.objects.create(referentiel=self.ref, code="EAU", nom="Eau", parent=self.env)
        self.env.parent = eau  # Environnement sous Eau, elle-même sous Environnement
        with self.assertRaises(ValidationError):
            self.env.full_clean()
        autre = Referentiel.objects.create(code="AUTRE", nom="Autre", frequence="annee")
        with self.assertRaises(ValidationError):
            Theme(referentiel=autre, code="X", nom="X", parent=eau).full_clean()
