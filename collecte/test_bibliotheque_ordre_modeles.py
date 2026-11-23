"""Ordre des modèles de la bibliothèque à l'écran (``vues_installation.fournis_decrits`` : page « Installer depuis la
bibliothèque », page Référentiels) : celui des
définitions (``SOCLE["ordre"]``), soit ESRS 2, E1 à E5, S1 à S4, G1 (ordre de la norme). Avant : l'ordre alphabétique
des fichiers (G1 avant S1). Message d'un paramètre hérité modifié : « Paramètre hérité modifié », pas le libellé du type
de saisie (« Facteur d'émission » pour un facteur de conversion)."""
from django.test import TestCase

from parametres import langues as L
from parametres.libelles import libelle

ESRS = ["ESRS_2", "ESRS_E1", "ESRS_E2", "ESRS_E3", "ESRS_E4", "ESRS_E5", "ESRS_S1", "ESRS_S2", "ESRS_S3", "ESRS_S4", "ESRS_G1"]


class OrdreModelesTests(TestCase):
    def test_ordre_de_la_norme(self):
        from parametres.vues_installation import fournis_decrits

        codes = [f.paquet.code for f in fournis_decrits()]
        self.assertEqual([c for c in codes if c.startswith("ESRS")], ESRS)
        self.assertLess(codes.index("VS_BASE"), codes.index("ESRS_2"))

    def test_message_parametre_herite(self):
        with L.activer("en"):
            texte = libelle("saisie.coherence.msg.fe_modifie", type="Emission factor", comparaison="2025", ecart="+5%")
        self.assertEqual(texte, "Inherited parameter changed compared with 2025 (+5%).")
