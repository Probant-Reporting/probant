"""Troisième passe du moteur de calcul : quelques cas aléatoires des formes ajoutées au générateur de
``qa/calculation_fuzz.py`` (option ``--v3``), rejoués à chaque passage de la suite avec les contrôles ``--full-check`` et
``--pages`` :

- formes : référentiel semestriel, deux campagnes sur un même exercice (une clôturée, l'autre ouverte), format
  « tableau », validation, valeur forcée puis retour au calcul, lot de saisies (comme un import), correction importée
  dans une campagne clôturée, écritures après une réouverture « garder les chiffres de l'époque » (les périodes
  gardées qui lisent la période changée suivent, README) ;
- contrôles : chaque case contre le second calcul indépendant ; après chaque changement, l'état laissé par l'outil
  (recalcul ciblé) = le recalcul complet de toutes les périodes non figées ; à la fin, les chiffres de la Visualisation
  (et du serveur MCP pour un lecteur), d'un visuel limité à un KPI, et le détail de chaque total = les cases enregistrées.

Graines choisies pour couvrir ces formes en peu de temps (``qa/calculation_fuzz.py --v3`` en essaie des centaines hors
de la suite). Données inventées."""
import sys
from pathlib import Path
from unittest import mock

from django.test import TestCase

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "qa"))


class CasAuHasardV3Tests(TestCase):
    def test_formes_de_la_troisieme_passe(self):
        import calculation_fuzz as CF

        with mock.patch.object(CF, "V3", True), mock.patch.object(CF, "PLEIN_DEMANDE", True), \
                mock.patch.object(CF, "PAGES_DEMANDE", True):
            formes = set()
            for graine in (32, 56, 98):
                cas = CF.generate(graine)
                formes |= {ch.get("type") for ch in cas["changes"]}
                formes |= {"semestre"} & set(cas["frequencies"])
                formes |= {"bis"} if any(p.get("bis") for p in cas["periods"]) else set()
                with self.subTest(graine=graine):
                    differences, compte = CF.verifier(cas)
                    self.assertEqual(differences, {})
                    self.assertGreater(compte["full recalculations compared"], 0)
        # le test couvre bien les formes ajoutées
        self.assertTrue({"semestre", "bis", "force", "unforce", "batch", "import", "reopen", "fix"} <= formes, formes)
