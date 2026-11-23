"""Dossier d'audit, parcours de l'auditeur dans un vrai navigateur (1 440 et 390 px) : Import / Export, nouvel export, choix
du dossier d'audit, téléchargement, ouverture du fichier par openpyxl ; sans erreur de script ni violation de la politique
des contenus, sans défilement horizontal, cibles d'au moins 24 px, accessibilité axe-core (si AXE_JS). Les captures sont
écrites dans le dossier de la variable DOSSIER_CAPTURES quand elle existe."""
import os
from pathlib import Path

from django.core.files.base import ContentFile
from openpyxl import load_workbook

from referentiel.models import Utilisateur

from .aides_tests.navigateur import AXE, NavigateurBase, _hors_boucle
from .models import Alerte, Campagne, Preuve, Reponse
from .test_navigateur_aide import REGLES_AXE
from .test_navigateur_cibles_tactiles import MESURE

PAGE = "/import-export/exporter/?nouveau=1"


class DossierAuditNavigateurTests(NavigateurBase):
    def setUp(self):
        super().setUp()
        with _hors_boucle():
            self.auditeur = Utilisateur.objects.create(username="auditeur", email="auditeur@exemple.test",
                                                       role=Utilisateur.Role.AUDITEUR)
            self.contrib = Utilisateur.objects.create(username="contrib", email="contrib@exemple.test")
            c = Campagne.objects.get(exercice=2026)
            r = Reponse.objects.create(periode=c.periode, kpi=self.eff, organisation=self.e1, valeur=120, statut="valide",
                                       saisi_par=self.contrib, valide_par=self.contrib, origine="saisie",
                                       commentaire="Embauches de l'été")
            Preuve.objects.create(reponse=r, fichier=ContentFile(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n", name="bilan.pdf"),
                                  nom_fichier="bilan.pdf", taille=30, depose_par=self.contrib)
            Alerte.objects.create(campagne=c, kpi=self.eff, organisation=self.e1, controle=Alerte.Controle.ECART_N1,
                                  message="Écart avec N-1", statut=Alerte.Statut.JUSTIFIEE, justification="Embauches",
                                  justifie_par=self.contrib)

    def _capture(self, page, nom):
        dossier = os.environ.get("DOSSIER_CAPTURES")
        if dossier:
            Path(dossier).mkdir(parents=True, exist_ok=True)
            page.wait_for_timeout(500)  # fin de la transition de la carte choisie
            page.screenshot(path=str(Path(dossier) / nom), full_page=False)

    def test_parcours_de_l_auditeur_jusqu_au_fichier(self):
        for largeur in (1440, 390):
            page = self.page(self.auditeur, largeur=largeur, tactile=largeur < 500)
            self.aller(page, "/import-export/")  # là où sont les exports
            self.assertEqual(page.erreurs, [])
            self.aller(page, PAGE)
            carte = page.locator('label.carte-choix:has(input[value="audit"])')
            self.assertEqual(carte.count(), 1)
            carte.scroll_into_view_if_needed()
            carte.click()
            self.assertTrue(page.locator('input[name=presentation][value=audit]').is_checked())
            self.assertFalse(page.evaluate("document.documentElement.scrollWidth > window.innerWidth"), largeur)
            self.assertEqual(page.evaluate(MESURE), [], largeur)  # cibles d'au moins 24 px
            self._capture(page, f"dossier-audit-{largeur}.png")
            with page.expect_download() as telechargement:
                page.locator('button[name=action][value=telecharger]').click()
            fichier = telechargement.value
            self.assertTrue(fichier.suggested_filename.endswith(".xlsx"), fichier.suggested_filename)
            chemin = Path(self._media) / fichier.suggested_filename
            fichier.save_as(str(chemin))
            wb = load_workbook(chemin)
            self.assertEqual(wb.sheetnames[1:], ["Audit", "Historique", "Preuves"])
            audit = [[c.value for c in r] for r in wb["Audit"].iter_rows()]
            tete = audit[0]
            ligne = next(r for r in audit[1:] if r[tete.index("Code organisation")] == self.e1.code and r[tete.index("Exercice")] == 2026)
            self.assertEqual(ligne[tete.index("Noms des fichiers de preuve")], "bilan.pdf (1 kB)")
            self.assertEqual(ligne[tete.index("Saisi par")], "contrib@exemple.test")
            self.assertIn("Embauches", ligne[tete.index("Justifications (qui, quand, texte)")])
            self.assertEqual(page.erreurs, [])

    def test_aucune_carte_pour_le_contributeur(self):
        page = self.page(self.contrib)
        self.aller(page, PAGE)
        self.assertEqual(page.locator('input[name=presentation]').count(), 3)
        self.assertEqual(page.locator('input[name=presentation][value=audit]').count(), 0)

    def test_accessibilite(self):
        if not AXE or not os.path.exists(AXE):
            self.skipTest("axe-core absent (variable AXE_JS)")
        with open(AXE, encoding="utf-8") as f:
            axe = f.read()
        for largeur in (1440, 390):
            page = self.page(self.auditeur, largeur=largeur, tactile=largeur < 500)
            self.aller(page, PAGE)
            page.locator('label.carte-choix:has(input[value="audit"])').click()
            page.add_script_tag(content=axe)
            self.assertEqual(page.evaluate(REGLES_AXE), [], largeur)
