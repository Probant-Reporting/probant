"""``docker/test_installation.sh`` (test « machine vierge », guide d'installation, section 11) : le texte qu'il cherche sur
la première étape de l'assistant est celui de la langue d'une installation neuve.

Constaté à l'essai de l'installation Docker : le script cherchait « Compte administrateur », alors qu'une
installation neuve est en anglais désormais (DEFAULT_LANGUAGE=en) ; il échouait à l'étape « wizard » sur une
installation correcte."""
import json
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

RACINE = Path(settings.BASE_DIR)


class TexteDeLAssistantTests(SimpleTestCase):
    def test_texte_cherche_dans_la_langue_d_une_installation_neuve(self):
        script = (RACINE / "docker" / "test_installation.sh").read_text(encoding="utf-8")
        cherche = re.search(r'grep -q "([^"]+)" <<<"\$PAGE"', script)
        self.assertIsNotNone(cherche, "contrôle de l'assistant introuvable dans docker/test_installation.sh")
        exemple = (RACINE / ".env.example").read_text(encoding="utf-8")
        langue = re.search(r"^DEFAULT_LANGUAGE=(\w*)", exemple, re.M).group(1) or "en"
        textes = json.loads((RACINE / "libelles" / f"referentiels.{langue}.json").read_text(encoding="utf-8"))
        self.assertEqual(cherche.group(1), textes["referentiels.mep.etape.compte.titre"])

    def test_le_test_docker_attend_le_message_que_le_script_ecrit(self):
        """``parametres.test_hebergement`` (TESTER_DOCKER=1, guide section 11) attendait « RÉUSSI » ; le script écrit
        « PASSED: … » depuis le passage de ses messages en anglais : le test échouait sur une installation réussie."""
        script = (RACINE / "docker" / "test_installation.sh").read_text(encoding="utf-8")
        test = (RACINE / "parametres" / "test_hebergement.py").read_text(encoding="utf-8")
        bloc = test[test.index("class InstallationMachineVierge"):]
        attendu = re.search(r'self\.assertIn\("([^"]+)", r\.stdout\)', bloc).group(1)
        self.assertIn(f'echo "{attendu}', script)
