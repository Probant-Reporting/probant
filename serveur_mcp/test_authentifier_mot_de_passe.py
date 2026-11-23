"""Un changement ou une réinitialisation de mot de passe révoque tous les jetons de la personne (dans tous les espaces où
elle en a), avec une ligne au journal : un jeton créé avec un mot de passe volé ne survit pas à la réinitialisation.
Chemins : Mon compte, réinitialisation par l'administrateur (puis nouveau mot de passe choisi), ``set_password`` (commande
de gestion, démo), copie remise d'accord avec le registre sans enregistrement (espace réactivé). Un simple recalcul du
hachage (même mot de passe) ne révoque rien."""
import json
import logging

from django.test import Client
from django.urls import reverse
from django.utils.html import escape

from collecte.models import Journal
from espaces import contexte as E
from espaces.aides_tests import MDP, creer
from espaces.essais import EspacesTestCase
from espaces.models import Compte
from parametres.libelles import libelle
from referentiel.models import Utilisateur

from . import jetons as JT
from .aides_tests import BaseMCP
from .models import JetonMCP, ReglageMCP

NOUVEAU = "Nouveau-mot-de-passe-2026"


class MotDePasseTests(BaseMCP):
    def setUp(self):
        super().setUp()
        self.personne = self.validateur  # pas le gestionnaire des espaces (premier compte) : l'administrateur peut réinitialiser
        self.personne.set_password(MDP)
        self.personne.save()
        self.clair, self.j = JT.creer(self.personne, "Portable", 30)
        JT.authentifier(self.clair)

    def assertRevoque(self, par=None):
        with self.assertRaises(JT.JetonRefuse):
            JT.authentifier(self.clair)
        self.j.refresh_from_db()
        self.assertIsNotNone(self.j.revoque_le)
        trace = Journal.objects.filter(action="jeton_mcp", champ="mcp_jeton_revoque_mdp", objet_id=str(self.j.pk)).get()
        self.assertEqual(trace.utilisateur_id, (par or self.personne).pk)
        self.assertFalse(JT.actifs(self.personne).exists())

    def test_changement_dans_mon_compte(self):
        c = Client()
        c.force_login(self.personne)
        page = c.get(reverse("collecte:mon_compte")).content.decode()
        self.assertAffiche(libelle("mcp.jetons.mdp_aide"), page)  # dit à l'écran, à côté du formulaire
        rep = c.post(reverse("collecte:mon_compte"), {"old_password": MDP, "new_password1": NOUVEAU, "new_password2": NOUVEAU},
                     follow=True)
        self.assertAffiche(libelle("mcp.jetons.revoques_mdp"), rep.content.decode())
        self.assertRevoque()

    def assertAffiche(self, texte, page):
        debut = texte.split(". ")[0]  # les messages mettent leur première phrase en gras
        self.assertTrue(debut in page or escape(debut) in page, texte)

    def test_reinitialisation_par_l_administrateur(self):
        c = Client()
        c.force_login(self.admin)
        c.post(reverse("collecte:admin_compte", args=[self.personne.pk]), {"action": "reinitialiser"})
        self.assertRevoque(par=self.admin)
        # la personne remplace le mot de passe provisoire : le jeton ne revient pas
        u = Utilisateur.objects.get(pk=self.personne.pk)
        u.set_password(NOUVEAU)
        u.doit_changer_mdp = False
        u.save()
        with self.assertRaises(JT.JetonRefuse):
            JT.authentifier(self.clair)

    def test_set_password_commande_de_gestion(self):
        u = Utilisateur.objects.get(pk=self.personne.pk)
        u.set_password(NOUVEAU)
        u.save()  # comme « manage.py changepassword » ou la commande de démo
        self.assertRevoque()

    def test_copie_remise_d_accord_sans_enregistrement(self):
        """Mot de passe changé au registre commun sans que la copie de cet espace soit enregistrée (espace archivé ou
        indisponible au moment du changement, puis réactivé) : aucun signal ici, le jeton est refusé quand même
        (empreinte du mot de passe gardée avec le jeton, comparée au mot de passe du registre)."""
        autre = Utilisateur.objects.get(pk=self.personne.pk)
        autre.set_password(NOUVEAU)
        Compte.objects.filter(pk=self.personne.pk).update(password=autre.password)
        with self.assertRaises(JT.JetonRefuse):
            JT.authentifier(self.clair)
        rep = self.requete(self.clair, "tools/list")
        self.assertEqual(rep.status_code, 401)

    def test_meme_mot_de_passe_rien_de_revoque(self):
        """Hachage recalculé (même mot de passe, par exemple après une mise à jour de Django) : jetons gardés."""
        u = Utilisateur.objects.get(pk=self.personne.pk)
        u.set_password(MDP)
        u.save()
        u, j = JT.authentifier(self.clair)
        self.assertIsNone(j.revoque_le)
        self.assertEqual(self.requete(self.clair, "tools/list").status_code, 200)

    def test_hachage_mis_a_jour_a_la_connexion_rien_de_revoque(self):
        """Django recalcule un hachage dépassé quand la personne se connecte (sans le mot de passe en clair au moment de
        l'enregistrement) : ce n'est pas un changement de mot de passe."""
        from django.contrib.auth.hashers import make_password
        from django.test import override_settings

        ancien = make_password(MDP, hasher="md5")
        Utilisateur.objects.filter(pk=self.personne.pk).update(password=ancien)
        Compte.objects.filter(pk=self.personne.pk).update(password=ancien)
        clair, _ = JT.creer(self.personne, "Avant la mise à jour", 7)
        hachages = ["django.contrib.auth.hashers.PBKDF2PasswordHasher", "django.contrib.auth.hashers.MD5PasswordHasher"]
        with override_settings(PASSWORD_HASHERS=hachages):
            u = Utilisateur.objects.get(pk=self.personne.pk)
            self.assertTrue(u.check_password(MDP))
            self.assertTrue(Utilisateur.objects.get(pk=self.personne.pk).password.startswith("pbkdf2_"))  # recalculé
            JT.authentifier(clair)

    def test_autre_changement_du_compte_rien_de_revoque(self):
        u = Utilisateur.objects.get(pk=self.personne.pk)
        u.first_name = "Autre"
        u.save()
        JT.authentifier(self.clair)


class MotDePasseDeuxEspacesTests(EspacesTestCase):
    def setUp(self):
        journal = logging.getLogger("serveur_mcp")
        self.addCleanup(journal.setLevel, journal.level)
        journal.setLevel(logging.ERROR)
        self.u = creer("deux@exemple.example", "admin")
        creer("deux@exemple.example", "admin", "essai")
        for code in ("principal", "essai"):
            with E.activer(code):
                ReglageMCP.objects.update_or_create(pk=1, defaults={"actif": True})
        with E.activer("principal"):
            self.ici, _ = JT.creer(self.u, "Principal", 7)
        with E.activer("essai"):
            self.la, _ = JT.creer(Utilisateur.objects.get(pk=self.u.pk), "Essai", 7)

    def statut(self, url, jeton):
        corps = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        return Client().post(url, corps, content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {jeton}").status_code

    def test_changement_dans_un_espace_revoque_dans_tous(self):
        self.assertEqual(self.statut("/espace/essai/mcp/", self.la), 200)
        with E.activer("principal"):
            u = Utilisateur.objects.get(pk=self.u.pk)
            u.set_password(NOUVEAU)
            u.save()
        self.assertEqual(self.statut("/mcp/", self.ici), 401)
        self.assertEqual(self.statut("/espace/essai/mcp/", self.la), 401)
        with E.activer("essai"):
            self.assertIsNotNone(JetonMCP.objects.get().revoque_le)
            self.assertTrue(Journal.objects.filter(action="jeton_mcp", champ="mcp_jeton_revoque_mdp").exists())
