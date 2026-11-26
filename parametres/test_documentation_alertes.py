"""Documentation des alertes par e-mail (docs/installation.md, section 9, hébergement géré, demande à l'IT, dossier de
sécurité, en anglais et en français) : les chiffres sont ceux du code (passage toutes les 15 minutes, rappel au plus
une fois par jour, deux passages avant « résolu ») et la commande des hébergements sans tâche de fond est citée."""
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from parametres import alertes as AL

RACINE = Path(settings.BASE_DIR)


def lire(chemin):
    return (RACINE / chemin).read_text(encoding="utf-8")


class DocumentationAlertesTests(SimpleTestCase):
    def test_chiffres_du_code(self):
        minutes = int(AL.INTERVALLE.total_seconds() // 60)
        self.assertEqual((int(AL.RAPPEL.total_seconds() // 3600), AL.ABSENCES), (24, 2))
        en, fr = lire("docs/installation.md"), lire("docs/fr/installation.md")
        self.assertIn(f"The tool checks every {minutes} minutes", en)
        self.assertIn(f"L'outil vérifie toutes les {minutes} minutes", fr)
        self.assertIn("A reminder at most once a day", en)
        self.assertIn("Un rappel au plus une fois par jour", fr)
        self.assertIn("absent at two checks in a row", en)
        self.assertIn("absent à deux vérifications de suite", fr)
        for chemin in ("docs/installation.md", "docs/fr/installation.md", "docs/managed_hosting.md",
                       "docs/fr/hebergement_cle_en_main.md"):
            self.assertIn("python manage.py check_data --alerts", lire(chemin), chemin)

    def test_supervision_externe_presentee_en_plus(self):
        self.assertIn("in addition to the email alerts", lire("docs/installation.md"))
        self.assertIn("en plus des alertes par\ne-mail", lire("docs/fr/installation.md"))
        self.assertIn("in addition to the email alerts of the tool", lire("docs/security_overview.md"))
        self.assertIn("en plus des alertes par e-mail de l'outil", lire("docs/fr/dossier_securite.md"))
        self.assertIn("**Administration › Settings › Health**", lire("docs/it_request.md"))
        self.assertIn("**Administration › Paramètres › Santé**", lire("docs/fr/demande_it.md"))
