"""Adresses : préfixe /espace/<code>/ dans les liens, espace inconnu ou archivé, espace principal inchangé, liens des
relances, adresse donnée dans les messages d'accès."""
from django.test import Client

from collecte import relances as R
from referentiel.models import Utilisateur

from . import contexte as E
from .essais import EspacesTestCase
from .models import Espace
from .aides_tests import MDP, creer


class AdressesTests(EspacesTestCase):
    """Le sélecteur « Espace » (deux espaces accessibles) donne le seul lien vers l'autre espace."""
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin = creer("admin@exemple.example", "admin")
        creer("admin@exemple.example", "admin", "essai")

    def setUp(self):
        self.client.force_login(Utilisateur.objects.get(pk=self.admin.pk))

    def test_liens_prefixes_dans_les_pages(self):
        r = self.client.get("/espace/essai/mon-compte/")
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn('href="/espace/essai/tableau-de-bord/"', html)
        self.assertIn('action="/espace/essai/deconnexion/"', html)
        self.assertIn('href="/static/css/outil.css', html)  # statiques absolus, jamais préfixés
        self.assertNotIn('href="/tableau-de-bord/"', html)

    def test_principal_inchange(self):
        html = self.client.get("/mon-compte/").content.decode()
        self.assertIn('href="/tableau-de-bord/"', html)
        self.assertNotIn('href="/espace/essai/tableau-de-bord/"', html)
        self.assertNotIn('action="/espace/', html)

    def test_espace_inconnu_ou_archive(self):
        self.assertEqual(self.client.get("/espace/inconnu/").status_code, 404)
        self.assertEqual(self.client.get("/espace/../").status_code, 404)
        self.assertEqual(self.client.get("/espace/principal/").status_code, 404)
        Espace.objects.filter(code="essai").update(etat="archive")
        self.assertEqual(self.client.get("/espace/essai/mon-compte/").status_code, 404)
        Espace.objects.filter(code="essai").update(etat="creation")
        self.assertEqual(self.client.get("/espace/essai/mon-compte/").status_code, 404)

    def test_redirection_vers_la_connexion_prefixee(self):
        r = Client().get("/espace/essai/saisie/")
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].startswith("/espace/essai/connexion/"), r["Location"])

    def test_lien_des_relances(self):
        with E.activer("essai"):
            self.assertTrue(R.adresse_outil().endswith("/espace/essai/pour-moi/"))
        self.assertEqual(R.adresse_outil().rstrip("/").split("/")[-1], "pour-moi")
        self.assertNotIn("/espace/", R.adresse_outil())

    def test_adresse_du_message_d_acces(self):
        r = self.client.post("/espace/essai/administration/comptes/nouveau/", {
            "action": "enregistrer", "first_name": "Nouvelle", "last_name": "Personne", "email": "nouvelle@exemple.example",
            "role": "contributeur", "is_active": "on", "equipe": "", "mot_de_passe": ""})
        self.assertContains(r, "Adresse : http://testserver/espace/essai/")

    def test_connexion_par_le_lien_d_un_espace(self):
        c = Client()
        r = c.get("/espace/essai/connexion/")
        self.assertEqual(r.status_code, 200)
        r = c.post("/espace/essai/connexion/", {"username": "admin@exemple.example", "password": MDP})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].startswith("/espace/essai/"))
