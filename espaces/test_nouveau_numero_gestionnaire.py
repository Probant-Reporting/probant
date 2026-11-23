"""Gestionnaire des espaces nommé à la création d'un compte : même règle que la reprise d'une installation existante
(``comptes.amorcer``) : seul un administrateur actif de l'espace principal le devient, et seulement quand l'installation
n'a aucun gestionnaire actif. Avant : le premier compte du registre le devenait quel que soit son rôle (un
contributeur créé en premier gérait tous les espaces)."""
from .aides_tests import creer
from .essais import EspacesTestCase
from .models import Compte


def gestionnaire(u):
    return Compte.objects.get(pk=u.pk).gestionnaire


class PremierCompteTests(EspacesTestCase):
    def test_premier_compte_contributeur_pas_gestionnaire(self):
        contributeur = creer("premier@exemple.example")
        self.assertFalse(gestionnaire(contributeur))

    def test_premier_administrateur_devient_gestionnaire(self):
        creer("premier@exemple.example")
        creer("lecteur@exemple.example", "lecteur")
        admin = creer("admin@exemple.example", "admin")
        self.assertTrue(gestionnaire(admin))
        autre = creer("admin2@exemple.example", "admin")  # un gestionnaire existe déjà
        self.assertFalse(gestionnaire(autre))

    def test_administrateur_d_un_autre_espace_pas_gestionnaire(self):
        """L'administrateur d'un espace secondaire ne prend pas la main sur toute l'installation."""
        admin_essai = creer("admin.essai@exemple.example", "admin", "essai")
        self.assertFalse(gestionnaire(admin_essai))

    def test_administrateur_desactive_pas_gestionnaire(self):
        u = creer("inactif@exemple.example", "admin", is_active=False)
        self.assertFalse(gestionnaire(u))

    def test_compte_devenu_administrateur_sans_gestionnaire(self):
        """Premier compte créé contributeur, puis nommé administrateur (Comptes, ``grant_admin``) : l'installation ne
        reste pas sans gestionnaire possible."""
        u = creer("premier@exemple.example")
        u.role, u.is_superuser, u.is_staff = "admin", True, True
        u.save(update_fields=["role", "is_superuser", "is_staff"])
        self.assertTrue(gestionnaire(u))

    def test_compte_devenu_administrateur_avec_gestionnaire(self):
        creer("admin@exemple.example", "admin")
        u = creer("contrib@exemple.example")
        u.role = "admin"
        u.save(update_fields=["role"])
        self.assertFalse(gestionnaire(u))

    def test_copie_admin_rattachee_dans_le_principal(self):
        """Compte né dans un espace secondaire, puis administrateur de l'espace principal, sans gestionnaire."""
        creer("personne@exemple.example", "contributeur", "essai")
        copie = creer("personne@exemple.example", "admin")
        self.assertTrue(gestionnaire(copie))

    def test_gestionnaire_bloque_ne_compte_pas(self):
        ancien = creer("ancien@exemple.example", "admin")
        Compte.objects.filter(pk=ancien.pk).update(actif=False)
        nouveau = creer("nouveau@exemple.example", "admin")
        self.assertTrue(gestionnaire(nouveau))
