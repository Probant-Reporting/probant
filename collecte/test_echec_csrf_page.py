"""Jeton CSRF périmé : une page de l'outil (et non la page technique de Django), un motif en JSON pour le script."""
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from referentiel.models import Utilisateur


class EchecCsrfTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        Utilisateur.objects.create_user(username="admin", password="x", role=Utilisateur.Role.ADMIN)

    def poster_connexion(self, **entetes):
        return self.client.post(reverse("login"), {"username": "admin", "password": "x"}, **entetes)

    def test_page_de_l_outil_sans_detail_technique(self):
        for debug in (False, True):
            with self.subTest(debug=debug), override_settings(DEBUG=debug):
                rep = self.poster_connexion(HTTP_REFERER="http://testserver" + reverse("login"))
                self.assertEqual(rep.status_code, 403)
                html = rep.content.decode()
                self.assertIn("<main>", html)
                self.assertIn("Cette page est restée ouverte trop longtemps", html)
                self.assertNotIn("CSRF", html)
                self.assertNotIn("Reason given", html)
                self.assertIn('<a href="' + reverse("login") + '"', html)  # revenir à la page précédente, rechargée

    def test_retour_seulement_vers_l_outil(self):
        rep = self.poster_connexion(HTTP_REFERER="https://autre.example/piege")
        html = rep.content.decode()
        self.assertNotIn("autre.example", html)
        self.assertIn('<a href="/"', html)

    def test_sans_referent(self):
        self.assertEqual(self.poster_connexion().status_code, 403)

    def test_requete_du_script_en_json(self):
        rep = self.poster_connexion(HTTP_X_REQUESTED_WITH="fetch")
        self.assertEqual(rep.status_code, 403)
        self.assertEqual(rep["Content-Type"], "application/json")
        d = rep.json()
        self.assertFalse(d["ok"])
        self.assertIn("restée ouverte trop longtemps", d["erreur"])
        self.assertNotIn("CSRF", d["erreur"])

    def test_connecte(self):
        c = Client(enforce_csrf_checks=True)
        c.force_login(Utilisateur.objects.get(username="admin"))
        rep = c.post(reverse("collecte:mon_compte"), {"action": "apparence", "apparence": "sombre"})
        self.assertEqual(rep.status_code, 403)
        self.assertIn("restée ouverte trop longtemps", rep.content.decode())
