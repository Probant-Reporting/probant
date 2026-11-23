"""Étape 8 de l'assistant sans référentiel installé : l'aperçu n'affiche pas « None » comme date de fin de saisie."""
from django.test import TestCase
from django.urls import reverse

from referentiel.models import Referentiel, Utilisateur

from .models import Instance


class EtapeCampagneSansReferentiel(TestCase):
    def test_apercu_sans_date_ne_montre_pas_none(self):
        u = Utilisateur.objects.create_user("admin", email="a@exemple.test", password="Essai-mise-en-place-2026",
                                            role=Utilisateur.Role.ADMIN, is_superuser=True)
        self.client.force_login(u)
        i = Instance.courante()
        i.mise_en_place_etape = 8
        i.save()
        self.assertFalse(Referentiel.objects.exists())
        rep = self.client.get(reverse("parametres:mise_en_place_etape", args=[8]))
        self.assertEqual(rep.status_code, 200)
        self.assertNotContains(rep, "None")
