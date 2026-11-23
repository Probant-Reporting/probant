"""Colonnes d'un tableau décrites avec les mots de l'exemple affiché : l'exemple anglais (repris en allemand et en
néerlandais) écrit « list » et « number » ; ces mots sont acceptés comme « liste » et « nombre »."""
import json
from pathlib import Path

from django.conf import settings
from django.test import TestCase

from collecte.tableaux import TYPES_COLONNE
from parametres import views as V


class LireColonnesTests(TestCase):
    def test_mots_anglais_acceptes(self):
        cols = V._lire("colonnes", "pollutant ; Pollutant ; list ; POLL\nair ; Emissions to air ; Number ; kg\nnote ; Note ; text")
        self.assertEqual([c["type"] for c in cols], ["liste", "nombre", "texte"])
        self.assertEqual((cols[0]["liste"], cols[1]["unite"]), ("POLL", "kg"))

    def test_mot_inconnu_garde_pour_le_refus(self):
        self.assertEqual(V._lire("colonnes", "a ; A ; date")[0]["type"], "date")

    def test_exemple_de_chaque_langue_lisible(self):
        for p in sorted(Path(settings.BASE_DIR, "libelles").glob("referentiels.*.json")):
            exemple = json.loads(p.read_text(encoding="utf-8"))["referentiels.reglable.colonnes_exemple"]
            with self.subTest(fichier=p.name):
                self.assertTrue(all(c["type"] in TYPES_COLONNE for c in V._lire("colonnes", exemple)))
