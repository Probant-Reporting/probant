"""Le lien de retour d'une fiche Compte, Organisation ou Campagne ouverte en page complète mène à la liste d'où l'on vient,
pas à la vue d'ensemble de l'Administration."""
from django.test import TestCase
from django.urls import reverse

from referentiel.models import Niveau, Organisation, Utilisateur

from .models import Campagne


class FicheRetourListeTests(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        self.client.force_login(self.admin)

    def _retour(self, url):
        rep = self.client.get(url)
        self.assertEqual(rep.status_code, 200)
        return rep.content.decode()

    def test_fiche_compte_revient_aux_comptes(self):
        html = self._retour(reverse("collecte:admin_compte", args=[self.admin.pk]))
        self.assertIn(f'<a href="{reverse("collecte:admin_comptes")}">←', html)
        self.assertNotIn(f'<a href="{reverse("collecte:admin_accueil")}">←', html)

    def test_fiche_organisation_revient_aux_organisations(self):
        o = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        html = self._retour(reverse("collecte:admin_organisation", args=[o.pk]))
        self.assertIn(f'<a href="{reverse("collecte:admin_organisations")}">←', html)

    def test_fiche_campagne_revient_aux_campagnes(self):
        c = Campagne.objects.create(exercice=2026, statut=Campagne.Statut.OUVERTE)
        html = self._retour(reverse("collecte:admin_campagne", args=[c.pk]))
        self.assertIn(f'<a href="{reverse("collecte:admin_campagnes")}">←', html)
