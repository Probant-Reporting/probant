"""Page Attributions, ligne de calcul des cartes de niveau (« 1 KPI × 3 Länder = 3 cellules ») : le nom d'un niveau garde sa casse
(en allemand, un nom commun porte une majuscule), le nombre de KPI suit le pluriel de la langue et le nom du niveau suit le
nombre d'organisations."""
from django.test import TestCase
from django.urls import reverse

from parametres.models import Langue, NiveauHierarchique
from referentiel.models import KPI, Niveau, Organisation, Utilisateur


class CalculDesCasesTests(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN, langue="de")
        Langue.objects.get_or_create(code="de", defaults={"libelle": "Deutsch", "ordre": 4})
        g = Organisation.objects.create(nom="Gruppe", niveau_id=Niveau.GROUP)
        p = Organisation.objects.create(nom="Deutschland", niveau_id=Niveau.COUNTRY, parent=g)
        for nom in ("Berlin", "Hamburg"):
            Organisation.objects.create(nom=nom, niveau_id=Niveau.ENTITY, parent=p)
        NiveauHierarchique.objects.filter(code=Niveau.COUNTRY).update(traductions={"de": {"nom": "Land", "nom_pluriel": "Länder"}})
        NiveauHierarchique.objects.filter(code=Niveau.ENTITY).update(traductions={"de": {"nom": "Standort", "nom_pluriel": "Standorte"}})
        KPI.objects.create(code="EFF", libelle="Effectif", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY)
        self.client.force_login(self.admin)

    def calcul(self, code):
        reponse = self.client.get(reverse("collecte:admin_attributions") + f"?niveau={code}")
        return {o["code"]: o for o in reponse.context["onglets"]}, reponse.content.decode()

    def test_les_noms_de_niveau_gardent_leur_casse(self):
        onglets, page = self.calcul(Niveau.ENTITY)
        self.assertEqual(onglets[Niveau.ENTITY]["orgs_libelle"], "Standorte")
        self.assertEqual(onglets[Niveau.COUNTRY]["orgs_libelle"], "Land")  # un seul pays : le singulier
        self.assertIn("1 KPI × 2 Standorte", page)
        self.assertIn("0 KPIs × 1 Land", page)
        self.assertNotIn("standorte", page)

    def test_un_seul_kpi_n_est_pas_au_pluriel(self):
        _, page = self.calcul(Niveau.ENTITY)
        self.assertNotIn("1 KPIs", page)
        KPI.objects.create(code="CA", libelle="Chiffre", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY)
        _, page = self.calcul(Niveau.ENTITY)
        self.assertIn("2 KPIs × 2 Standorte", page)
