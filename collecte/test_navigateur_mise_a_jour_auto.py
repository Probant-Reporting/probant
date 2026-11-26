"""Navigateur (Chromium) : bloc « Mises à jour automatiques » de Paramètres › Hébergement (parametres/mise_a_jour_auto.py),
à 1 440 et 390 px : sans erreur de script ni violation de la politique des contenus, sans défilement horizontal, cibles
d'au moins 24 px, choix au clavier (flèches dans les boutons radio, Entrée envoie), accessibilité axe-core (si AXE_JS).
Les captures sont écrites dans le dossier de la variable DOSSIER_CAPTURES quand elle existe."""
import os
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.test import override_settings
from django.utils import timezone

from parametres import mise_a_jour_auto as MA

from .aides_tests.navigateur import AXE, NavigateurBase
from .test_navigateur_aide import REGLES_AXE
from .test_navigateur_cibles_tactiles import MESURE

PAGE = "/administration/parametres/hebergement/#mise-a-jour-auto"


class MiseAJourAutoNavigateurTests(NavigateurBase):
    def setUp(self):
        super().setUp()
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        reglage = override_settings(DOSSIER_DONNEES=tmp)
        reglage.enable()
        self.addCleanup(reglage.disable)
        docker = mock.patch.dict(os.environ, {"DANS_DOCKER": "1"})
        docker.start()
        self.addCleanup(docker.stop)
        MA.ecrire_choix("notify", 3)
        maintenant = timezone.now().strftime("%Y-%m-%dT%H:%M:%SZ")
        (MA.dossier() / MA.RESULTAT).write_text(
            f"format=1\ntask=systemd\ntime=04:00\nchecked={maintenant}\nstate=rolled_back\nreason=health\ninstalled=1.0.1\n"
            "available=1.0.2\nrestored=yes\n", encoding="utf-8")

    def _capture(self, page, nom):
        dossier = os.environ.get("DOSSIER_CAPTURES")
        if dossier:
            Path(dossier).mkdir(parents=True, exist_ok=True)
            page.locator("#mise-a-jour-auto").screenshot(path=str(Path(dossier) / nom))

    def test_bloc_sur_ordinateur_et_telephone_et_choix_au_clavier(self):
        for largeur in (1440, 390):
            page = self.page(largeur=largeur, tactile=largeur < 500)
            self.aller(page, PAGE)
            self.assertEqual(page.locator("#mise-a-jour-auto input[name=mode]").count(), 3)
            self.assertFalse(page.evaluate("document.documentElement.scrollWidth > window.innerWidth"), largeur)
            self.assertEqual(page.evaluate(MESURE), [], largeur)  # cibles d'au moins 24 px
            self._capture(page, f"mise-a-jour-auto-{largeur}.png")
            page.focus("input[name=mode]:checked")
            self.assertEqual(page.evaluate("document.activeElement.value"), "notify")
            page.keyboard.press("ArrowUp")
            self.assertEqual(page.evaluate("document.querySelector('input[name=mode]:checked').value"), "automatic")
            with page.expect_navigation():
                page.keyboard.press("Enter")
            page.wait_for_load_state("networkidle")
            self.assertEqual(MA.lire_choix(), {"mode": "automatic", "delai": 3, "ecrit": True})
            self.assertTrue(page.locator("#resultat-maj-auto .encart").is_visible())
            self.assertEqual(page.erreurs, [])
            MA.ecrire_choix("notify", 3)

    def test_accessibilite(self):
        if not AXE or not os.path.exists(AXE):
            self.skipTest("axe-core absent (variable AXE_JS)")
        with open(AXE, encoding="utf-8") as f:
            axe = f.read()
        for largeur in (1440, 390):
            page = self.page(largeur=largeur, tactile=largeur < 500)
            self.aller(page, PAGE)
            page.add_script_tag(content=axe)
            self.assertEqual(page.evaluate(REGLES_AXE), [], largeur)
