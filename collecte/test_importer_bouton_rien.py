"""Import : quand il n'y a rien à importer, le bouton le dit (désactivé) au lieu d'afficher « Importer 0 ligne »."""
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from . import configuration as C
from .aides_tests.echanges import Base
from .outils_tests import xlsx


class BoutonRienAImporterTests(Base):
    def test_import_de_valeurs_sans_ligne_valide(self):
        self.client.force_login(self.contrib)
        f = xlsx([["ID KPI", "Organisation", "Valeur"], ["INCONNU", "E1", 130]])
        rep = self.client.post(reverse("collecte:echanges_importer"), {"action": "verifier", "fichier": f, "campagne": self.c.pk})
        self.assertContains(rep, "Rien à importer")
        self.assertNotContains(rep, "Importer 0 ligne")

    def test_configuration_sans_changement(self):
        self.client.force_login(self.admin)
        fichier = SimpleUploadedFile("config.xlsx", C.exporter().content)
        rep = self.client.post(reverse("collecte:admin_fichiers"), {"action": "verifier", "fichier": fichier})
        self.assertContains(rep, "Rien à importer")
        self.assertNotContains(rep, "Importer 0 changement")
