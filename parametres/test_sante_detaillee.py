"""/sante/ : le détail (version, base, stockage, dernière sauvegarde) n'est donné qu'à un admin connecté ou à un appel
local sans aucun en-tête de proxy (X-Forwarded-For, X-Real-IP, Forwarded) ; un proxy local qui n'en pose qu'un ne le
donne plus à Internet. Le contrôle de santé de Docker (127.0.0.1, sans en-tête) garde le détail."""
from django.test import TestCase
from django.urls import reverse

from referentiel.models import Utilisateur


class SanteDetailleeTests(TestCase):
    def get(self, **meta):
        return self.client.get(reverse("parametres:sante"), **meta)

    def test_appel_local_sans_proxy(self):
        rep = self.get(REMOTE_ADDR="127.0.0.1")
        self.assertEqual(rep.status_code, 200)
        self.assertIn("version", rep.json())
        self.assertIn("version", self.get(REMOTE_ADDR="::1").json())

    def test_en_tetes_de_proxy(self):
        for meta in ({"HTTP_X_FORWARDED_FOR": "203.0.113.9"}, {"HTTP_X_REAL_IP": "203.0.113.9"},
                     {"HTTP_FORWARDED": "for=203.0.113.9"}):
            rep = self.get(REMOTE_ADDR="127.0.0.1", **meta)
            self.assertEqual(rep.status_code, 200)
            self.assertEqual(rep.json()["etat"], "ok", meta)  # l'état reste lisible pour la supervision
            self.assertNotIn("version", rep.json(), meta)

    def test_appel_distant(self):
        self.assertNotIn("version", self.get(REMOTE_ADDR="203.0.113.9").json())

    def test_admin_connecte(self):
        admin = Utilisateur.objects.create_user("admin", email="admin@exemple.test", password="x", role=Utilisateur.Role.ADMIN)
        self.client.force_login(admin)
        self.assertIn("version", self.get(REMOTE_ADDR="203.0.113.9", HTTP_X_REAL_IP="203.0.113.9").json())
