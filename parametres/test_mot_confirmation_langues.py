"""Mots à taper dans chaque langue complète de l'interface : le mot de confirmation d'une restauration affiché est celui
qui est accepté (majuscules ou minuscules), et un autre mot est refusé ; le « oui » écrit dans un fichier (colonne N/A)
est relu comme un oui."""
from django.test import TransactionTestCase
from django.urls import reverse

from collecte import fichiers as X
from referentiel.models import Utilisateur

from . import libelles as LB
from . import sauvegardes as SV
from .aides_tests.hebergement import MDP, DossiersTemporaires


class MotDeConfirmationParLangue(DossiersTemporaires, TransactionTestCase):
    def test_le_mot_affiche_est_le_mot_accepte(self):
        admin = Utilisateur.objects.create_user("admin", email="admin@exemple.test", password=MDP, role=Utilisateur.Role.ADMIN)
        for langue in LB.langues_disponibles():
            with self.subTest(langue=langue):
                Utilisateur.objects.filter(pk=admin.pk).update(langue=langue)
                self.client.force_login(Utilisateur.objects.get(pk=admin.pk))
                a = SV.creer("manuelle")
                url = reverse("parametres:sauvegarde_restaurer", args=[a.nom])
                mot = LB.libelle("admin.restauration.mot", langue)
                rep = self.client.get(url)
                self.assertContains(rep, f"<strong>{mot}</strong>")
                self.assertEqual(rep.context["mot"], mot)
                rep = self.client.post(url, {"compris": "on", "confirmation": "RESTAURER-A-TORT"})
                self.assertEqual(rep.status_code, 200)
                self.assertContains(rep, mot)
                rep = self.client.post(url, {"compris": "on", "confirmation": mot.lower()})
                self.assertEqual(rep.status_code, 302, f"« {mot.lower()} » refusé en {langue}")


class MotOuiParLangue(TransactionTestCase):
    def test_le_oui_ecrit_dans_un_fichier_est_lu_comme_un_oui(self):
        for langue in LB.langues_disponibles():
            with self.subTest(langue=langue):
                self.assertTrue(X.oui(X.t(langue, "suivi.export.terme.oui")))
                self.assertFalse(X.oui(X.t(langue, "suivi.export.terme.non")))
