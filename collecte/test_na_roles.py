"""Rôles qui peuvent répondre « N/A » (Paramètres › Seuils de suivi) : l'administrateur toujours,
les autres selon le réglage ; un N/A déjà posé par un autre reste modifiable (commentaire) ; le panneau cache
l'interrupteur aux rôles non autorisés."""
from django.core.exceptions import ValidationError
from django.urls import reverse

from parametres.models import Instance

from .models import Reponse
from .aides_tests.saisie import Base


class RolesNATests(Base):
    def regler(self, roles):
        i = Instance.courante()
        i.na_roles = roles
        i.save()

    def test_par_defaut_tous_les_roles_qui_saisissent(self):
        self.enregistrer("", na=True, com="Pas de salariés")
        self.assertTrue(Reponse.objects.get(periode=self.c.periode, kpi=self.eff, organisation=self.e1).non_applicable)

    def test_contributeur_refuse_quand_son_role_n_est_pas_coche(self):
        self.regler("admin,validateur")
        with self.assertRaises(ValidationError):
            self.enregistrer("", na=True, com="Pas de salariés")
        self.enregistrer("12")  # une valeur reste possible

    def test_admin_toujours_autorise(self):
        self.regler("")
        self.enregistrer("", na=True, com="Pas de salariés", user=self.admin)
        self.assertTrue(Reponse.objects.get(periode=self.c.periode, kpi=self.eff, organisation=self.e1).non_applicable)

    def test_na_deja_pose_reste_modifiable(self):
        self.enregistrer("", na=True, com="Pas de salariés", user=self.admin)
        self.regler("admin")
        self.enregistrer("", na=True, com="Pas de salariés en 2026")  # le contributeur complète le commentaire
        self.assertEqual(Reponse.objects.get(periode=self.c.periode, kpi=self.eff, organisation=self.e1).commentaire, "Pas de salariés en 2026")

    def test_panneau_sans_interrupteur_pour_un_role_non_autorise(self):
        url = reverse("collecte:cellule", args=[self.c.pk, self.eff.code, self.e1.pk])
        self.client.force_login(self.contrib)
        self.assertContains(self.client.get(url), 'name="non_applicable"')
        self.regler("admin,validateur")
        self.assertNotContains(self.client.get(url), 'name="non_applicable"')
