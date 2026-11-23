"""Correctif de sécurité : jamais d'installation sans administrateur actif."""
from django.test import TestCase
from django.urls import reverse

from referentiel.models import Utilisateur


class DernierAdministrateurTests(TestCase):
    """Jamais d'installation sans administrateur actif. Un administrateur a aussi
    is_superuser : l'ancienne règle « pas son propre rôle » ne le visait pas, il pouvait se retirer le rôle."""

    def setUp(self):
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", first_name="A", last_name="A",
                                                role=Utilisateur.Role.ADMIN, is_superuser=True, is_staff=True)
        self.client.force_login(self.admin)

    def poster(self, u, **champs):
        donnees = {"first_name": u.first_name or "X", "last_name": u.last_name or "Y", "email": u.email, "equipe": "",
                   "role": u.role, "is_active": "on", "action": "enregistrer", **champs}
        donnees = {k: v for k, v in donnees.items() if v is not None}
        return self.client.post(reverse("collecte:admin_compte", args=[u.pk]), donnees, HTTP_X_REQUESTED_WITH="fetch")

    def test_ne_peut_pas_se_retirer_le_role(self):
        self.poster(self.admin, role="contributeur")
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.role, Utilisateur.Role.ADMIN)
        self.assertTrue(self.admin.is_superuser)

    def test_ne_peut_pas_se_desactiver(self):
        self.poster(self.admin, is_active=None)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_autre_admin_retirable_tant_qu_il_en_reste_un(self):
        autre = Utilisateur.objects.create(username="b", email="b@exemple.test", first_name="B", last_name="B",
                                           role=Utilisateur.Role.ADMIN, is_superuser=True, is_staff=True)
        self.poster(autre, role="validateur")
        autre.refresh_from_db()
        self.assertEqual((autre.role, autre.is_superuser), (Utilisateur.Role.VALIDATEUR, False))

    def test_dernier_admin_garde_par_un_compte_technique(self):
        """Un compte technique de l'IT (superuser sans rôle administrateur, désactivé) ne compte pas : l'administrateur
        reste le dernier actif, et personne ne peut lui retirer son rôle."""
        from .administration import CompteForm

        it = Utilisateur.objects.create(username="it", email="it@exemple.test", is_superuser=True, is_staff=True,
                                        role=Utilisateur.Role.CONTRIBUTEUR, is_active=False)
        f = CompteForm({"first_name": "A", "last_name": "A", "email": self.admin.email, "equipe": "", "role": "contributeur",
                        "is_active": "on"}, instance=self.admin, moi=it)
        self.assertFalse(f.is_valid())
        self.assertIn("dernier administrateur", " ".join(f.non_field_errors()))

    def test_page_de_son_compte_bloque_les_autres_roles(self):
        rep = self.client.get(reverse("collecte:admin_compte", args=[self.admin.pk]), HTTP_X_REQUESTED_WITH="fetch")
        html = rep.json()["html"] if rep["Content-Type"].startswith("application/json") else rep.content.decode()
        self.assertRegex(html, r'value="contributeur"[^>]*disabled')
        self.assertNotRegex(html, r'value="admin"[^>]*disabled')
        self.assertIn("vous gardez le rôle d'administrateur", html)

    def test_commande_de_secours(self):
        from io import StringIO

        from django.core.management import call_command

        u = Utilisateur.objects.create(username="perdu", email="perdu@exemple.test", role=Utilisateur.Role.CONTRIBUTEUR, is_active=False)
        call_command("grant_admin", "PERDU@exemple.test", stdout=StringIO())
        u.refresh_from_db()
        self.assertEqual((u.role, u.is_active, u.is_superuser), (Utilisateur.Role.ADMIN, True, True))
