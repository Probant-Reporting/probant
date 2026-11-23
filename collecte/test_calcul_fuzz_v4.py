"""Quatrième passe du moteur de calcul : quelques cas aléatoires des formes ajoutées au générateur de
``qa/calculation_fuzz.py`` (option ``--v4``), rejoués à chaque passage de la suite avec le contrôle ``--full-check`` :

- une période rouverte (« garder » ou « recalculer »), corrigée, reclôturée, l'arbre changé après la reclôture, puis
  rouverte une seconde fois dans l'un des deux modes et corrigée (README : une deuxième clôture après « garder » garde
  l'arbre de la première ; après « recalculer », la clôture suivante note l'arbre de ce jour) ;
- la forme du modèle de transparence des rémunérations : effectifs additionnés, moyennes sans valeur au-dessus, totaux
  calculés additionnés, écart recalculé à chaque niveau (agrégation « Formule »), N/A d'un employeur qui ne déclare pas.

Graines choisies pour couvrir ces formes en peu de temps (``qa/calculation_fuzz.py --v3 --v4`` en essaie des milliers
hors de la suite). Données inventées."""
import sys
from pathlib import Path
from unittest import mock

from django.test import TestCase

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "qa"))


class CasAuHasardV4Tests(TestCase):
    def test_formes_de_la_quatrieme_passe(self):
        import calculation_fuzz as CF

        with mock.patch.object(CF, "V3", True), mock.patch.object(CF, "V4", True), \
                mock.patch.object(CF, "PLEIN_DEMANDE", True):
            formes = set()
            for graine in (73, 141, 349):
                cas = CF.generate(graine)
                changements = cas["changes"]
                i = next(j for j, ch in enumerate(changements) if ch.get("type") == "reclose")
                modes = [ch["mode"] for ch in changements if ch.get("type") == "reopen"]
                formes |= {f"{modes[0]} puis {modes[1]}"}
                formes |= {"déplacée après la reclôture"} if any(ch.get("type") == "move" for ch in changements[i:]) else set()
                formes |= {"transparence"} if any(k["agg"] == "Formule" and k["formula"].startswith("([")
                                                  for k in cas["kpis"]) else set()
                with self.subTest(graine=graine):
                    differences, compte = CF.verifier(cas)
                    self.assertEqual(differences, {})
                    self.assertGreater(compte["full recalculations compared"], 0)
        # le test couvre bien les formes ajoutées
        self.assertTrue({"garder puis garder", "recalculer puis garder", "garder puis recalculer",
                         "déplacée après la reclôture", "transparence"} <= formes, formes)

    def test_saisie_ancienne_d_un_kpi_calcule_remplacee_a_la_reouverture_recalculer(self):
        """Graine 14986 : un KPI calculé (``[K5@P-1]``) porte une ancienne saisie dans une année close ; rouverte en
        « recalculer », l'année remplace cette saisie par le résultat de la formule (README, « Recalculation ») ; à la
        reclôture, c'est ce résultat qui se fige : l'année suivante, qui le cite, est incomplète. Le second calcul
        relisait l'ancienne saisie après la reclôture."""
        import calculation_fuzz as CF

        with mock.patch.object(CF, "V3", True), mock.patch.object(CF, "V4", True):
            cas = CF.generate(14986)
            self.assertTrue(any(ch.get("type") == "reclose" for ch in cas["changes"]))
            differences, _ = CF.verifier(cas)
        self.assertEqual(differences, {})

    def test_reduction_garde_la_recloture(self):
        """La réduction d'un cas (``--minimize``) garde une reclôture dont la période existe encore."""
        import calculation_fuzz as CF

        cas = {"orgs": [{"id": "O0", "parent": None}], "kpis": [], "periods": [{"type": "annee", "debut": "2023-01-01"}],
               "inputs": [], "changes": [{"type": "reopen", "p": "annee:2023-01-01", "mode": "recalculer"},
                                         {"type": "reclose", "p": "annee:2023-01-01"}]}
        self.assertEqual([ch["type"] for ch in CF._coherent(cas)["changes"]], ["reopen", "reclose"])
