"""Monnaie de référence et sauvegardes : la monnaie suit la base dans l'archive et revient à la
restauration ; une archive d'avant ce réglage (sans le champ) se restaure avec l'euro, le défaut, sans perte."""
import json
import zipfile

from django.test import TransactionTestCase

from . import sauvegardes as SV
from .aides_tests.hebergement import DossiersTemporaires
from .models import Instance


class RestaurerMonnaieTests(DossiersTemporaires, TransactionTestCase):
    def setUp(self):
        super().setUp()
        Instance.objects.filter(pk=Instance.courante().pk).update(monnaie="CHF")

    def test_aller_retour(self):
        a = SV.creer("essai", "json")
        Instance.objects.filter(pk=1).update(monnaie="USD")
        SV.restaurer(a.chemin)
        self.assertEqual(Instance.courante().monnaie, "CHF")

    def test_archive_d_avant_le_reglage(self):
        a = SV.creer("essai", "json")
        ancienne = self.tmp / "ancienne.zip"
        with zipfile.ZipFile(a.chemin) as z, zipfile.ZipFile(ancienne, "w") as sortie:
            for info in z.infolist():
                contenu = z.read(info.filename)
                if info.filename.endswith("database.json"):
                    lignes = json.loads(contenu)
                    for ligne in lignes:
                        if ligne["model"] == "parametres.instance":
                            del ligne["fields"]["monnaie"]  # archive faite par la version d'avant
                    contenu = json.dumps(lignes).encode()
                sortie.writestr(info, contenu)
        SV.restaurer(ancienne)
        self.assertEqual(Instance.courante().monnaie, "EUR")
