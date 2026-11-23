"""Renommer un espace (page Espaces, action « renommer ») : nom vide refusé, nom déjà pris par un autre espace refusé (sans
tenir compte de la casse), espace introuvable signalé ; dans chaque cas le nom ne change pas et un message le dit. Garder
son propre nom (casse changée) est permis."""
from parametres.libelles import libelle
from referentiel.models import Utilisateur

from .essais import EspacesTestCase
from .models import Espace
from .aides_tests import creer

URL = "/administration/espaces/"


class RenommerEspaceTests(EspacesTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.gestionnaire = creer("gestion@exemple.example", "admin")  # premier compte : gestionnaire

    def setUp(self):
        self.client.force_login(Utilisateur.objects.get(pk=self.gestionnaire.pk))
        self.nom_principal = Espace.objects.get(code="principal").nom

    def renommer(self, code, nom):
        rep = self.client.post(URL, {"code": code, "action": "renommer", "nom": nom}, follow=True)  # messages lus par la page
        self.assertEqual(rep.redirect_chain[-1][1], 302)
        return [str(m) for m in rep.context["messages"]]

    def nom(self, code="essai"):
        return Espace.objects.get(code=code).nom

    def test_nom_vide_refuse(self):
        self.assertEqual(self.renommer("essai", "   "), [libelle("espaces.erreur.nom_vide")])
        self.assertEqual(self.nom(), "Achats")

    def test_nom_deja_pris_refuse(self):
        pris = self.nom_principal.upper()  # même nom, autre casse : pris quand même
        self.assertEqual(self.renommer("essai", pris), [libelle("espaces.erreur.nom_pris", nom=pris)])
        self.assertEqual(self.nom(), "Achats")

    def test_espace_introuvable(self):
        self.assertEqual(self.renommer("inconnu", "Nouveau"), [libelle("espaces.erreur.introuvable")])
        self.assertEqual(sorted(Espace.objects.values_list("nom", flat=True)), sorted([self.nom_principal, "Achats"]))

    def test_renomme_et_garde_son_propre_nom(self):
        self.assertEqual(self.renommer("essai", "  Achats groupe  "), [libelle("espaces.liste.renomme", nom="Achats groupe")])
        self.assertEqual(self.nom(), "Achats groupe")
        self.assertEqual(self.renommer("essai", "ACHATS GROUPE"), [libelle("espaces.liste.renomme", nom="ACHATS GROUPE")])
        self.assertEqual(self.nom(), "ACHATS GROUPE")
