"""Page « Copie externe des sauvegardes » (Paramètres › Hébergement) dans un vrai navigateur, à 1 440 et 390 px : sans
défilement horizontal, sans erreur de script ni écart à la politique de sécurité des contenus, cibles d'au moins
24 × 24 px (DESIGN.md « Touch targets »), clavier : chaque champ a son libellé et se joint par Tab ; accessibilité
axe-core (si AXE_JS). États montrés : aucune destination, formulaire S3, formulaire SFTP avec une clé de serveur à
confirmer, échec de copie."""
import os

from django.utils import timezone

from .aides_tests.navigateur import AXE, NavigateurBase, _hors_boucle
from .test_navigateur_aide import REGLES_AXE
from .test_navigateur_cibles_tactiles import MESURE

URL = "/administration/parametres/hebergement/copie-externe/"
CLE = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"


class CopieExterneNavigateurTests(NavigateurBase):
    def setUp(self):
        super().setUp()
        self.chemins = [URL, URL + "?type=s3", "/administration/parametres/hebergement/"]

    def regler_sftp(self):
        from espaces.models import DestinationCopie, EtatCopie
        from parametres import copie_externe as CE

        with _hors_boucle():
            CE.enregistrer(None, "sftp", {"hote": "nas.exemple.lan", "port": 22, "identifiant": "copie", "chemin": "/backups",
                                          "conserver": 0}, secret="Mdp-navigateur")
            DestinationCopie.objects.filter(pk=1).update(cle_proposee=CLE, cle_proposee_le=timezone.now())
            EtatCopie.objects.update_or_create(pk=1, defaults={"echec_le": timezone.now(), "echec": "delai",
                                                               "echec_resume": "TimeoutError"})

    def verifier(self, largeur, chemins):
        page = self.page(largeur=largeur, tactile=largeur < 500)
        for chemin in chemins:
            self.aller(page, chemin)
            self.assertFalse(page.evaluate("document.documentElement.scrollWidth > window.innerWidth"), (chemin, largeur))
            self.assertEqual(page.evaluate(MESURE), [], (chemin, largeur))
            # chaque champ visible a un libellé (label for=… ou englobant)
            sans_libelle = page.evaluate("""() => [...document.querySelectorAll('.page-copie input:not([type=hidden]), .page-copie select, .page-copie textarea')]
                .filter(e => !(e.labels && e.labels.length) && !e.getAttribute('aria-label')).map(e => e.name)""")
            self.assertEqual(sans_libelle, [], chemin)
        self.assertEqual(page.erreurs, [])
        return page

    def test_pages_sans_debordement_ni_erreur(self):
        for largeur in (1440, 390):
            self.verifier(largeur, self.chemins)
        self.regler_sftp()
        for largeur in (1440, 390):
            page = self.verifier(largeur, [URL])
            self.assertEqual(page.locator("code.empreinte-copie").count(), 1)
            self.assertEqual(page.locator("button", has_text="Confirmer cette clé").count(), 1)

    def test_clavier(self):
        page = self.page()
        self.aller(page, URL + "?type=s3")
        page.locator("#id_adresse").focus()
        vus = []
        for _ in range(8):
            vus.append(page.evaluate("document.activeElement.name || document.activeElement.id"))
            page.keyboard.press("Tab")
        self.assertEqual(vus[:4], ["adresse", "region", "compartiment", "chemin"])
        self.assertIn("secret", vus)

    def test_accessibilite(self):
        if not AXE or not os.path.exists(AXE):
            self.skipTest("axe-core absent (variable AXE_JS)")
        with open(AXE, encoding="utf-8") as f:
            axe = f.read()
        self.regler_sftp()
        for largeur in (1440, 390):
            page = self.page(largeur=largeur, tactile=largeur < 500)
            for chemin in (URL, URL + "?type=s3"):
                self.aller(page, chemin)
                page.add_script_tag(content=axe)
                self.assertEqual(page.evaluate(REGLES_AXE), [], (chemin, largeur))
