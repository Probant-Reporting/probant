"""Coller des organisations (assistant de mise en place ; Administration › Organisations › « Plusieurs organisations ») :
date d'ouverture entre crochets, seule ou avec le niveau.

Données inventées uniquement."""
import datetime

from django.test import TestCase

from parametres import niveaux as N
from parametres.mise_en_place import creer_arbre, lire_arbre
from referentiel.models import Organisation, Utilisateur


class DateOuvertureColleeTests(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        self.niveaux = list(N.tous())
        self.bas = self.niveaux[-1]

    def test_saisie_rapide(self):
        texte = f"Groupe\n  France\n    Lyon [2026-03-01]\n    Paris\n  Nantes [{self.bas.nom}, 15/09/2025]"
        noeuds, erreurs = lire_arbre(texte, self.niveaux)
        self.assertEqual(erreurs, [])
        par_nom = {x.nom: x for x in noeuds}
        self.assertEqual(par_nom["Lyon"].ouverture, datetime.date(2026, 3, 1))
        self.assertIsNone(par_nom["Paris"].ouverture)
        self.assertEqual((par_nom["Nantes"].ouverture, par_nom["Nantes"].niveau.code), (datetime.date(2025, 9, 15), self.bas.code))
        creer_arbre(self.admin, noeuds)
        self.assertEqual(Organisation.objects.get(nom="Lyon").date_ouverture, datetime.date(2026, 3, 1))
        self.assertIsNone(Organisation.objects.get(nom="Paris").date_ouverture)

    def test_collage_excel_une_colonne_par_niveau(self):
        texte = "Groupe\tFrance [2024-01-01]\tLyon\n\t\tParis [2026-02-01]"
        noeuds, erreurs = lire_arbre(texte, self.niveaux)
        self.assertEqual(erreurs, [])
        par_nom = {x.nom: x for x in noeuds}
        self.assertEqual(par_nom["France"].ouverture, datetime.date(2024, 1, 1))
        self.assertEqual(par_nom["Lyon"].parent, "France")  # le nom lu sans la date : la lignée suit
        self.assertEqual(par_nom["Paris"].parent, "France")

    def test_date_impossible_refusee(self):
        noeuds, erreurs = lire_arbre("Groupe\n  France [31/02/2026]", self.niveaux)
        self.assertEqual(len(erreurs), 1)
        self.assertIn("France", erreurs[0])
