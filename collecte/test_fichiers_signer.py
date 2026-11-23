"""Classeurs exportés : l'auteur (propriétés du fichier) est le nom de l'outil de l'installation, pas « openpyxl », par
les deux chemins d'écriture (classeur ordinaire, écriture seule) et pour un classeur créé ailleurs (``reponse_excel``)."""
import io

from django.test import TestCase
from openpyxl import Workbook, load_workbook

from parametres.models import Instance

from . import fichiers as X


def auteur(octets):
    return load_workbook(io.BytesIO(octets)).properties.creator


class AuteurDesClasseursTests(TestCase):
    def setUp(self):
        Instance.courante()
        Instance.objects.filter(pk=Instance.courante().pk).update(titre="Mon outil")

    def test_deux_chemins_et_classeur_cree_ailleurs(self):
        ordinaire = X.classeur()
        ordinaire.create_sheet("A")["A1"] = "x"
        rapide = X.classeur(ecriture_seule=True)
        rapide.create_sheet("A").append(["x"])
        for wb in (ordinaire, rapide, Workbook()):
            with self.subTest(wb=wb):
                self.assertEqual(auteur(X.reponse_excel(wb, "essai").content), "Mon outil")

    def test_nom_par_defaut(self):
        Instance.objects.filter(pk=Instance.courante().pk).update(titre="Probant")
        flux = io.BytesIO()
        X.classeur(ecriture_seule=True).save(flux)
        self.assertEqual(auteur(flux.getvalue()), "Probant")
