"""Une même action, un même libellé : « Save changes » (et son équivalent dans chacune des sept langues) sur la fiche KPI,
le compte, l'organisation, les langues, le contenu d'un référentiel et les exports enregistrés."""
import json
from pathlib import Path

from django.test import SimpleTestCase

LIBELLES = Path(__file__).resolve().parent.parent / "libelles"
CLES = {
    "saisie": "saisie.fiche.enregistrer_modifs",
    "admin": ["admin.compte.enregistrer_modifs", "admin.organisation.enregistrer_modifs", "admin.langues.enregistrer"],
    "referentiels": "referentiels.reglable.enregistrer",
    "suivi": "suivi.echanges.export.enregistrer_modifs",
}
LANGUES = ("en", "fr", "es", "de", "it", "nl", "pt")


class LibelleEnregistrerLesModificationsTests(SimpleTestCase):
    def test_meme_texte_partout_dans_chaque_langue(self):
        for langue in LANGUES:
            textes = {}
            for zone, cles in CLES.items():
                donnees = json.loads((LIBELLES / f"{zone}.{langue}.json").read_text(encoding="utf-8"))
                for cle in [cles] if isinstance(cles, str) else cles:
                    textes[cle] = donnees[cle]
            self.assertEqual(len(set(textes.values())), 1, f"{langue} : {textes}")

    def test_anglais_et_francais(self):
        def lire(zone, langue):
            return json.loads((LIBELLES / f"{zone}.{langue}.json").read_text(encoding="utf-8"))

        self.assertEqual(lire("saisie", "en")["saisie.fiche.enregistrer_modifs"], "Save changes")
        self.assertEqual(lire("saisie", "fr")["saisie.fiche.enregistrer_modifs"], "Enregistrer les modifications")
