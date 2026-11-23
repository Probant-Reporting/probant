"""Répétition de la mise à jour (qa/migration_rehearsal.py), étape 6 : cibles des « migrate <application> <cible> » qui
ramènent une base PostgreSQL mise à jour aux migrations de l'archive « before-update » (retour vers une version sans
« restore --rebuild », docs/installation.md)."""
from django.test import SimpleTestCase

from qa import migration_rehearsal as MR


class CiblesRetour(SimpleTestCase):

    def test_mise_a_jour_du_week_end(self):
        archive = [["collecte", "0033_x"], ["collecte", "0034_journal_index_action_objet"],
                   ["parametres", "0030_tableau_colonnes"], ["referentiel", "0018_y"]]
        base = {tuple(m) for m in archive} | {("collecte", "0035_a"), ("collecte", "0037_b"),
                                               ("parametres", "0031_c"), ("serveur_mcp", "0001_initial"),
                                               ("serveur_mcp", "0002_d")}
        self.assertEqual(MR.cibles_retour(archive, base), [
            ("collecte", "0034_journal_index_action_objet"), ("parametres", "0030_tableau_colonnes"),
            ("serveur_mcp", "zero")])

    def test_rien_a_defaire(self):
        archive = [["collecte", "0034_a"]]
        self.assertEqual(MR.cibles_retour(archive, {("collecte", "0034_a")}), [])
