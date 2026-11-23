"""Fichier de couverture partagé par plusieurs modèles de la bibliothèque (famille ESRS : un inventaire maître,
``esrs_coverage.csv``, une colonne ``template``) : chaque modèle ne contrôle que ses lignes, les erreurs donnent le numéro
de ligne du fichier, et un modèle sans aucune ligne est refusé."""
import tempfile
import types
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from referentiel.bibliotheque import controle as C
from referentiel.bibliotheque import definitions as D
from referentiel.bibliotheque import socles as S

SOCLE = {
    "code": "TEST_PARTAGE", "fichier": "test_partage.json", "couleur": "#5A6B85", "version": "1.0", "date": "2026-11-13",
    "thematique": ("Normes de reporting", "Reporting standards"), "nom": ("Essai", "Test"), "description": ("Essai.", "Test."),
    "arbre": [("T1", "Thème", "Theme", [("SOC-EFFECTIF", "§1"), ("SOC-EFF-FEMMES", "§2")])], "regles": [],
    "module": "test_partage", "source": {"titre": "t", "editeur": "e", "version": "v", "url": "u", "consulte_le": "2026-11-13",
                                         "licence": "l"},
}
ENTETE = "reference,requirement,datapoint,status,kpi_codes,note,template\n"


class CouvertureFichierPartageTests(SimpleTestCase):
    def controler(self, contenu):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(C, "controler_libelles"):
            chemin = Path(d) / "commun_coverage.csv"
            chemin.write_text(contenu, encoding="utf-8")
            return C.controler(SOCLE, kpis=S.KPIS, couverture=chemin, propres=set())  # KPI repris : leurs textes ailleurs

    def test_chemin_declare_par_le_modele(self):
        """Un modèle qui déclare ``COUVERTURE`` lit ce fichier ; sans déclaration, ``<nom>_coverage.csv``."""
        avec = types.SimpleNamespace(__name__="referentiel.bibliotheque.definitions.esrs_e9", COUVERTURE="esrs_coverage.csv")
        sans = types.SimpleNamespace(__name__="referentiel.bibliotheque.definitions.vs_base")
        self.assertEqual(D.couverture(avec).name, "esrs_coverage.csv")
        self.assertEqual(D.couverture(sans).name, "vs_base_coverage.csv")

    def test_seules_les_lignes_du_modele(self):
        """Les lignes d'un autre modèle (encore « todo », ou citant des KPI absents de cet arbre) ne comptent pas ; une
        ligne vide entre deux modèles est ignorée."""
        r = self.controler(ENTETE + "A1,mandatory,Effectif,covered,SOC-EFFECTIF,,TEST_PARTAGE\n\n"
                                    "B1,mandatory,Autre,todo,GES-S1,,AUTRE_MODELE\n"
                                    "A2,mandatory,Femmes,covered,SOC-EFF-FEMMES,,TEST_PARTAGE\n")
        self.assertEqual(r.erreurs, [])
        self.assertEqual((r.chiffres["couverture"]["total"], r.chiffres["couverture"]["taux"]), (2, 100))

    def test_numero_de_ligne_du_fichier(self):
        r = self.controler(ENTETE + "B1,mandatory,Autre,todo,,,AUTRE_MODELE\n\n"
                                    "A1,mandatory,Effectif,todo,,,TEST_PARTAGE\n")
        self.assertIn("commun_coverage.csv, ligne 4 : « A1 » encore à traiter (todo)", r.erreurs)

    def test_aucune_ligne_pour_le_modele(self):
        r = self.controler(ENTETE + "B1,mandatory,Autre,covered,GES-S1,,AUTRE_MODELE\n")
        self.assertIn("commun_coverage.csv : aucune exigence listée pour TEST_PARTAGE", r.erreurs)
