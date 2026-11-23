"""``comptes.doit_devenir_gestionnaire`` : un compte désactivé au registre commun (``Compte.actif`` faux, connexion
refusée dans tous les espaces) ne devient jamais gestionnaire des espaces, même si sa copie de l'espace principal est
active et administrateur. Avant : seule la copie (``is_active``) était lue."""
from referentiel.models import Utilisateur

from . import comptes as EC
from .aides_tests import creer
from .essais import EspacesTestCase
from .models import Compte


def gestionnaire(u):
    return Compte.objects.get(pk=u.pk).gestionnaire


class CompteActifTests(EspacesTestCase):
    def test_compte_desactive_nomme_administrateur(self):
        u = creer("premier@exemple.example")
        Compte.objects.filter(pk=u.pk).update(actif=False)
        u = Utilisateur.objects.get(pk=u.pk)
        self.assertFalse(EC.doit_devenir_gestionnaire(u, "default"))
        u.role, u.is_superuser, u.is_staff = "admin", True, True
        u.save(update_fields=["role", "is_superuser", "is_staff"])
        self.assertFalse(gestionnaire(u))

    def test_compte_desactive_copie_admin_rattachee_dans_le_principal(self):
        """Compte né dans un espace secondaire et désactivé au registre, puis copie administrateur de l'espace principal."""
        ne_ailleurs = creer("personne@exemple.example", "contributeur", "essai")
        Compte.objects.filter(pk=ne_ailleurs.pk).update(actif=False)
        copie = creer("personne@exemple.example", "admin")
        self.assertEqual(copie.pk, ne_ailleurs.pk)
        self.assertFalse(gestionnaire(copie))

    def test_compte_actif_toujours_nomme(self):
        u = creer("premier@exemple.example")
        u = Utilisateur.objects.get(pk=u.pk)
        u.role, u.is_superuser, u.is_staff = "admin", True, True
        self.assertTrue(EC.doit_devenir_gestionnaire(u, "default"))
        u.save(update_fields=["role", "is_superuser", "is_staff"])
        self.assertTrue(gestionnaire(u))
