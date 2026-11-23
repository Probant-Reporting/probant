"""Lien « Retour » de la page du jeton CSRF périmé (``reponses_script.echec_csrf``) : construit depuis le Referer, il ne
mène jamais vers un autre site, même quand le chemin commence par « // » ou « /\\ » (adresse relative au protocole)."""
from django.test import Client, TestCase
from django.urls import reverse

from referentiel.models import Utilisateur


class RetourEchecCsrfTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        Utilisateur.objects.create_user(username="admin", password="x", role=Utilisateur.Role.ADMIN)

    def retour(self, referent):
        rep = self.client.post(reverse("login"), {"username": "admin", "password": "x"}, HTTP_REFERER=referent)
        self.assertEqual(rep.status_code, 403)
        html = rep.content.decode()
        debut = html.index('<a href="') + len('<a href="')
        return html[debut:html.index('"', debut)]

    def test_chemin_relatif_au_protocole_refuse(self):
        for referent in ("http://testserver//autre.example/piege", "http://testserver/\\autre.example/piege",
                         "http://testserver///autre.example"):
            with self.subTest(referent):
                retour = self.retour(referent)
                self.assertEqual(retour, "/")

    def test_chemin_de_l_outil_garde(self):
        self.assertEqual(self.retour("http://testserver/saisie/?org=3"), "/saisie/?org=3")
