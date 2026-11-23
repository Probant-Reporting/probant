"""Textes écrits à l'écran par le script de la Visualisation : aucun mot de l'interface en dur (« vs » d'une carte), tout passe
par les fichiers de langue, dans chaque langue complète."""
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from parametres import libelles as LB

SCRIPT = Path(settings.BASE_DIR) / "static" / "js" / "visualisation.js"
CLES = ("visu.chiffre.comparaison", "visu.chiffre.comparaison_ecart")


class TextesDuScriptTests(SimpleTestCase):
    def test_pas_de_vs_en_dur(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn('" vs "', source)
        for cle in CLES:
            self.assertIn(f'"{cle}"', source)

    def test_comparaison_d_une_carte_dans_chaque_langue(self):
        for langue in LB.langues_disponibles():
            with self.subTest(langue=langue):
                for cle in CLES:
                    texte = LB.libelle(cle, langue)
                    self.assertNotEqual(texte, cle)
                    self.assertIn("{libelle}", texte)
                    self.assertIn("{texte}", texte)
                self.assertNotEqual(LB.libelle(CLES[0], langue), LB.libelle(CLES[1], langue))
