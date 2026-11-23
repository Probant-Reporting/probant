"""Guide d'installation, « Capacity » (règle du projet) : les deux mesures (petite base de démo, grosse
base de qa/load) et le conseil de passer à PostgreSQL au-delà d'une vingtaine de personnes actives, en anglais et en
français ; le nombre de réponses de la grosse base est celui que donne qa/load/make_big_data.py aujourd'hui (1 273 762,
recompté), pas un nombre plus ancien."""
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

RACINE = Path(settings.BASE_DIR)


def lire(chemin):
    return (RACINE / chemin).read_text(encoding="utf-8")


def section(texte, titre):
    debut = texte.index(titre)
    return texte[debut:texte.index("\n### ", debut + 1)]


class CapaciteTests(SimpleTestCase):
    def test_deux_mesures_et_conseil(self):
        en = section(lire("docs/installation.md"), "### Capacity")
        for attendu in ("about 100 people", "1.27 million answers", "10 very active people", "15 to 20", "50 people",
                        "more than about twenty people"):
            self.assertIn(attendu, en)
        fr = section(lire("docs/fr/installation.md"), "### Capacité")
        for attendu in ("une centaine de personnes", "1,27 million de réponses", "10 personnes très actives", "15 à 20",
                        "50 personnes", "au-delà d'une vingtaine de personnes actives"):
            self.assertIn(attendu, fr)

    def test_nombre_de_reponses_de_la_grosse_base(self):
        self.assertIn("1,273,762 answers", lire("qa/load/README.md"))
        self.assertNotIn("2,587,458 answers (most", lire("qa/load/README.md"))
        if (RACINE / "docs/acceptance_testing.md").is_file():  # sauté quand ce fichier est absent
            self.assertNotIn("2.6 million answers", lire("docs/acceptance_testing.md"))
