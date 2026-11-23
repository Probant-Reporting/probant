"""Répétition de la mise à jour (qa/migration_rehearsal.py) : le ménage voulu de collecte/0035 : un mois ne
calcule que les KPI de ses campagnes) n'est attendu que pour les cases vides, calculées, « incomplet », d'un mois à
campagne non clôturée, d'un KPI hors de son périmètre, sans commentaire, saisie, validation ni preuve. Toute autre ligne
supprimée reste un écart."""
from django.test import SimpleTestCase

from qa import migration_rehearsal as MR

MOIS = "octobre 2026"


def ligne(periode=MOIS, kpi="HORS", org="Site A", valeur="", texte="", na=False, commentaire="", statut="incomplet",
          origine="agregation", saisi="", valide=""):
    return [periode, kpi, org, valeur, texte, na, commentaire, statut, origine, saisi, valide, "", "2026-11-14"]


class CasesHorsPerimetre(SimpleTestCase):

    def apres(self, *gardees):
        return {"perimetres_mois": {MOIS: ["DANS"], "#7": ["DANS"]}, "reponses": list(gardees)}

    def test_seule_la_case_vide_hors_perimetre_est_attendue(self):
        attendue = ligne()
        autres = [
            ligne(kpi="DANS"),  # KPI du périmètre du mois
            ligne(periode="2026"),  # pas un mois à campagne non clôturée
            ligne(org="Site B", valeur="12"),  # une valeur
            ligne(org="Site C", texte="oui"),
            ligne(org="Site D", na=True),
            ligne(org="Site E", commentaire="à voir"),
            ligne(org="Site F", statut="calcule"),
            ligne(org="Site G", origine="saisie"),
            ligne(org="Site H", saisi="a@exemple.test"),
            ligne(org="Site I", valide="a@exemple.test"),
            ligne(org="Site J"),  # une preuve sur cette case
        ]
        a = {"reponses": [attendue, *autres], "preuves": [["HORS", "Site J", "p.pdf", 3, "x", True]]}
        self.assertEqual(MR.cases_hors_perimetre(a, self.apres()), 1)
        self.assertEqual(a["reponses"], autres)  # toujours signalées par la comparaison
        self.assertFalse(MR.comparer_listes("reponses", a["reponses"], [])["identique"])

    def test_case_encore_presente_apres_non_retiree(self):
        a = {"reponses": [ligne()], "preuves": []}
        self.assertEqual(MR.cases_hors_perimetre(a, self.apres(ligne())), 0)
        self.assertEqual(len(a["reponses"]), 1)

    def test_lignes_sql(self):
        base = dict(periode_id=7, kpi_id="HORS", statut="incomplet", origine="agregation", valeur=None, non_applicable=0,
                    texte="", commentaire="", saisi_par_id=None, valide_par_id=None)
        lignes = [dict(base, id=1), dict(base, id=2, kpi_id="DANS"), dict(base, id=3, periode_id=8),
                  dict(base, id=4, valeur=5), dict(base, id=5, commentaire="x"), dict(base, id=6, origine="saisie"),
                  dict(base, id=7), dict(base, id=8, saisi_par_id=3), dict(base, id=9, non_applicable=1),
                  dict(base, id=10)]
        # 7 : une preuve ; 10 : encore là après
        self.assertEqual(MR.ids_hors_perimetre(lignes, {7}, {10}, {"#7": ["DANS"]}), {1})
