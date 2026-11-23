"""Aperçu d'un import (``imports.analyser``) : une valeur non applicable s'affiche « N/A » (avant comme après), et un
export lisible de l'outil (onglet « À lire », colonne « ID KPI », sans « Valeur » ni « Organisation ») est reconnu : le
message dit qu'il se lit mais ne se réimporte pas, au lieu de « colonnes introuvables »."""
from parametres.libelles import libelle

from . import imports as I
from .models import Reponse
from .aides_tests.echanges import Base
from .outils_tests import xlsx

ENTETES = ["ID KPI", "Organisation", "Exercice", "Valeur", "Commentaire"]


class ApercuNonApplicableTests(Base):
    def test_na_affiche_dans_l_apercu(self):
        a = I.analyser(self.admin, xlsx([ENTETES, ["EFF", "E2", 2026, "N/A", ""]]), campagne_defaut=self.c.pk)
        self.assertEqual(a.erreur, "")
        l = a.lignes[0]
        self.assertTrue(l.na)
        self.assertEqual((l.avant, l.apres), ("40 ETP", "N/A"))  # E2 valait 40

    def test_na_deja_en_base_affiche_avant(self):
        Reponse.objects.filter(periode=self.c.periode, kpi=self.eff, organisation=self.e2).update(valeur=None, non_applicable=True)
        l = I.analyser(self.admin, xlsx([ENTETES, ["EFF", "E2", 2026, 12, ""]]), campagne_defaut=self.c.pk).lignes[0]
        self.assertEqual((l.avant, l.apres), ("N/A", "12 ETP"))


class ExportLisibleTests(Base):
    def test_export_lisible_reconnu(self):
        a_lire = libelle("suivi.fichier.a_lire", "fr")
        fichier = xlsx({a_lire: [["Export de l'outil"]], "Tableau": [["ID KPI", "Indicateur", "2026"], ["EFF", "Effectif", 150]]})
        a = I.analyser(self.admin, fichier, campagne_defaut=self.c.pk)
        self.assertEqual(a.erreur, libelle("suivi.importer.erreur.export_lisible"))
        self.assertEqual(a.lignes, [])

    def test_fichier_sans_colonnes_connues(self):
        a = I.analyser(self.admin, xlsx([["Nom", "Montant"], ["Lyon", 3]]), campagne_defaut=self.c.pk)
        self.assertEqual(a.erreur, libelle("suivi.importer.erreur.colonnes"))
        # un onglet « À lire » sans colonne « ID KPI » n'est pas un export de l'outil
        a_lire = libelle("suivi.fichier.a_lire", "fr")
        a = I.analyser(self.admin, xlsx({a_lire: [["x"]], "Feuille": [["Nom", "Montant"]]}), campagne_defaut=self.c.pk)
        self.assertEqual(a.erreur, libelle("suivi.importer.erreur.colonnes"))
