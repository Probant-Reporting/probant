"""Textes récents qui portent un nombre : le pluriel suit le nombre (« 1 appel », « 1 mois », « 1 cellule »), dans les sept
langues."""
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from referentiel.models import Utilisateur

from . import libelles as LB

LANGUES = ("en", "fr", "es", "de", "it", "nl", "pt")
# clé → (paramètres, mots qui ne doivent pas suivre « 1 » : formes du pluriel, par langue)
A_UN = {
    "admin.ia.refus.plafond": ({"n": 1}, ["calls)", "appels)", "llamadas)", "Aufrufe)", "chiamate)", "aanroepen)", "pedidos)"]),
    "admin.a_traiter.preuves_detail": ({"n": 1}, ["months", "mois ", "meses", "Monate", "mesi", "maanden", "meses"]),
    "mcp.refus.debit": ({"n": 1}, ["seconds", "secondes", "segundos", "Sekunden", "secondi", "seconden", "segundos"]),
    "saisie.js.tableau_lignes": ({"n": 1}, ["rows", "lignes", "filas", "Zeilen", "righe", "rijen", "linhas"]),
}


class Pluriel1Tests(SimpleTestCase):
    def test_un_au_singulier_dans_chaque_langue(self):
        for cle, (valeurs, pluriels) in A_UN.items():
            for langue, pluriel in zip(LANGUES, pluriels):
                if langue == "fr" and cle == "admin.a_traiter.preuves_detail":
                    continue  # « mois » ne change pas
                with self.subTest(cle=cle, langue=langue):
                    texte = LB.libelle(cle, langue, **valeurs)
                    self.assertIn("1", texte)
                    self.assertNotIn(f"1 {pluriel}", texte)

    def test_plusieurs_au_pluriel(self):
        self.assertEqual(LB.libelle("admin.ia.refus.plafond", "fr", n=5).split(".")[0], "Limite du jour atteinte (5 appels)")
        self.assertIn("2 seconds", LB.libelle("mcp.refus.debit", "en", n=2))

    def test_utilisation_du_jour_sans_nom_pluriel_attache_au_nombre(self):
        """« 5 appels utilisés sur 1 » : le nom ne suit plus un nombre ; le plafond peut valoir 1."""
        for langue in LANGUES:
            with self.subTest(langue=langue):
                texte = LB.libelle("admin.ia.etat_allume", langue, n=5, max=1)
                self.assertIn("5", texte)
                self.assertNotRegex(texte, r"5 \w+ \w+ 1\b")  # pas « 5 appels sur 1 » : le nom précède les nombres
        self.assertEqual(LB.libelle("admin.ia.etat_allume", "fr", n=5, max=1),
                         "Allumé. Appels utilisés aujourd'hui dans cet espace : 5 sur 1.")


class CellulesEnregistreesTests(TestCase):
    def test_un_seuil_de_une_cellule_et_un_jour(self):
        admin = Utilisateur.objects.create(username="admin", email="a@exemple.test", role=Utilisateur.Role.ADMIN)
        self.client.force_login(admin)
        rep = self.client.post(reverse("parametres:hebergement"), {"action": "reglage_exports_fond", "exports_fond_cellules": "1",
                                                                    "exports_fond_jours": "1"}, follow=True)
        self.assertContains(rep, "Les exports de plus de 1 cellule sont préparés sur le serveur et gardés 1 jour.")
        rep = self.client.post(reverse("parametres:hebergement"), {"action": "reglage_exports_fond", "exports_fond_cellules": "250000",
                                                                    "exports_fond_jours": "3"}, follow=True)
        self.assertContains(rep, "Les exports de plus de 250\u202f000 cellules sont préparés sur le serveur et gardés 3 jours")
