"""Répétition de la mise à jour (qa/migration_rehearsal.py) : les extractions découpées sur disque et comparées clé par
clé donnent exactement la même comparaison, et le même détail des écarts, que les extractions entières en mémoire ; les
empreintes des étapes 5 et 6 voient la moindre différence."""
import copy
import json
import shutil
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from qa import migration_rehearsal as MR

ENTETES_AVANT = ["Exercice", "ID KPI", "Organisation", "Valeur", "N/A", "Unité", "Statut"]
ENTETES_APRES = ["Exercice", "ID KPI", "Organisation", "Ajoutée", "Valeur", "N/A", "Unité", "Statut"]


def reponse(periode, kpi, org, valeur="", statut="valide"):
    return [periode, kpi, org, valeur, "", False, "", statut, "saisie", "a@exemple.test", "", "", "2026-01-02"]


def extraction(apres=False):
    lignes = [["2025", "K1", "Site A", "12", "", "t", "Validé"], ["2025", "K1", "Site B", "", "", "t", "Brouillon"],
              ["2025", "K2", "Site A", "", "oui", "%", "Validé"], ["2025", "K2", "Site AB", "3", "", "%", "Validé"],
              ["2025", "K2", "Site A\x01", "4", "", "%", "Validé"]]
    if apres:
        lignes = [l[:3] + ["x"] + l[3:] for l in lignes]
    d = {
        "perimetres_mois": {},
        "tableaux": [[1, 2]], "vues": [[2, "a@exemple.test", False, 1]] if apres else [],
        "version": "nouvelle" if apres else "ancienne",
        "kpis": {"K1": {"unite": "t", "decimales": 1, "unite_entiere": False},
                 "K2": {"unite": "%", "decimales": 0, "unite_entiere": False}},
        "organisations": [["Site A", 1, "", True, 0], ["Site B", 1, "", True, 1]],
        "comptes": [["a@exemple.test", "admin", True, "", "", ""]],
        "attributions": [["K1", "Site A", "a@exemple.test", "spoc"]],
        "campagnes": {"2025": ["cloturee", "", "", "", ""]},
        "reponses": sorted([reponse("2025", "K1", "Site A", "12"), reponse("2025", "K1", "Site B"),
                            reponse("2025", "K2", "Site A", "", "brouillon")]),
        "preuves": [["K1", "Site A", "p.pdf", 3, "evidence/p.pdf", True]],
        "journal": 10 if apres else 9,
        "exports": {"powerbi": [ENTETES_APRES if apres else ENTETES_AVANT] + lignes,
                    "manquantes": [["Exercice", "ID KPI", "Organisation"], ["2025", "K1", "Site B"]]},
    }
    return d


class ComparaisonEnFlux(SimpleTestCase):

    def setUp(self):
        self.dossier = Path(tempfile.mkdtemp(prefix="test-repetition-"))
        self.addCleanup(shutil.rmtree, self.dossier, True)

    def decoupee(self, d, nom):
        chemin = self.dossier / f"{nom}.json"
        chemin.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        empreintes = MR.decouper(chemin, self.dossier / nom)
        return MR.Extraction(self.dossier / nom), empreintes

    def deux_facons(self, a, b):
        """(comparaison, écarts) en mémoire, puis sur disque."""
        sorties = []
        for sur_disque in (False, True):
            MR.ECARTS.clear()
            if sur_disque:
                x, _ = self.decoupee(a, "a")
                y, _ = self.decoupee(b, "b")
            else:
                x, y = copy.deepcopy(a), copy.deepcopy(b)
            c = MR.comparer(x, y, frozenset())
            sorties.append((c, list(MR.ECARTS), MR.tout_identique(c)))
        MR.ECARTS.clear()
        return sorties

    def test_meme_resultat_sans_ecart(self):
        memoire, disque = self.deux_facons(extraction(), extraction(apres=True))
        self.assertEqual(memoire, disque)
        self.assertTrue(disque[2])
        self.assertEqual(disque[0]["exports"]["powerbi"]["nouvelles_colonnes"], 1)

    def test_ecarts_introduits_detectes_et_detailles_pareil(self):
        b = extraction(apres=True)
        b["exports"]["powerbi"][4][4] = "30"  # valeur de « Site AB » changée dans l'export
        b["reponses"][0][3] = "13"  # une réponse changée
        b["kpis"]["K2"]["decimales"] = 2
        memoire, disque = self.deux_facons(extraction(), b)
        self.assertEqual(memoire, disque)
        c, ecarts, identique = disque
        self.assertFalse(identique)
        self.assertEqual(c["exports"]["powerbi"]["differences"], {"Valeur": 1})
        self.assertIn("export powerbi, column Valeur: '3' → '30'", ecarts)
        self.assertFalse(c["listes"]["reponses"]["identique"])
        self.assertEqual(c["kpis"]["ecarts"], {"decimales": 1})

    def test_tri_des_lignes_jointes_comme_des_tuples(self):
        lignes = [["a", "b"], ["ab", ""], ["a", ""], ["", "z"], ["a\x01", "b"], ["a", "b\x01"]]
        attendu = sorted(tuple(l) for l in lignes)
        self.assertEqual([tuple(MR._deplier(x)) for x in MR._reduire([0, 1], lignes)], attendu)
        mixtes = lignes + [["a", "\x00"]]  # caractère nul : ligne gardée en tuple, tri sur les tuples
        self.assertEqual([tuple(MR._deplier(x)) for x in MR._reduire([0, 1], mixtes)], sorted(tuple(l) for l in mixtes))

    def test_empreintes_par_cle(self):
        a = extraction()
        _, h = self.decoupee(a, "a")
        dans_le_desordre = dict(reversed(list(a.items())))
        dans_le_desordre["kpis"] = {k: dict(reversed(list(v.items()))) for k, v in a["kpis"].items()}
        _, h2 = self.decoupee(dans_le_desordre, "a2")
        self.assertEqual(h, {k: h2[k] for k in h})
        modifiee = copy.deepcopy(a)
        modifiee["exports"]["powerbi"][2][3] = "0"
        _, h3 = self.decoupee(modifiee, "a3")
        self.assertEqual([k for k in h if h[k] != h3[k]], ["exports"])

    def test_dans_un_enfant(self):
        chemin = self.dossier / "e.json"
        chemin.write_text(json.dumps(extraction()), encoding="utf-8")
        attendu = {k: MR.empreinte_valeur(v) for k, v in extraction().items()}
        self.assertEqual(MR.sur_disque(chemin, None), attendu)
        self.assertFalse(chemin.exists())
