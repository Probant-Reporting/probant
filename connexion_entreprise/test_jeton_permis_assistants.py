"""Jetons des assistants (serveur MCP) et connexion d'entreprise (décision du produit) : connexion d'entreprise allumée,
une personne qui ne peut plus se connecter par mot de passe n'a aucun accès par un assistant : ses jetons sont refusés
avec un message clair (403, ``company_sign_in``), même juste après une connexion par son compte d'entreprise, et elle
ne peut pas en créer (Mon compte le dit). Gestionnaires des espaces, et tout le monde si le mot de passe reste permis à
tous : comme avant. Connexion d'entreprise éteinte : rien ne change (les jetons d'avant servent de nouveau). Plus de
délai de 7 jours."""
import datetime

from django.core.exceptions import PermissionDenied
from django.test import Client
from django.utils import timezone

from espaces.models import Compte
from referentiel.models import Utilisateur
from serveur_mcp import jetons as JT
from serveur_mcp.aides_tests import BaseMCP

from . import regles
from .flux import CLE_METHODE
from .models import LienEntreprise, ReglageEntreprise
from .secret import chiffrer


class JetonsEntrepriseTests(BaseMCP):
    def setUp(self):
        super().setUp()
        Compte.objects.update(gestionnaire=False)
        Compte.objects.filter(pk=self.admin.pk).update(gestionnaire=True)

    def allumer(self):
        ReglageEntreprise.objects.update_or_create(pk=1, defaults={
            "actif": True, "emetteur": "https://login.exemple.example/realms/x", "client_id": "c",
            "secret_chiffre": chiffrer("secret-du-client-2026")})
        self.assertTrue(regles.active())

    def lien(self, u, jours):
        LienEntreprise.objects.update_or_create(compte_id=u.pk, defaults={
            "emetteur": "https://login.exemple.example/realms/x", "sujet": f"s-{u.pk}",
            "derniere_le": timezone.now() - datetime.timedelta(days=jours)})

    def liste(self, role):
        return self.requete(self.jetons[role], "tools/list").status_code

    def test_eteinte_rien_ne_change(self):
        self.assertEqual(self.liste("contributeur"), 200)

    def test_sans_mot_de_passe_aucun_acces_meme_connectee_a_l_instant(self):
        self.allumer()
        self.lien(self.contrib, 0)  # connectée par son compte d'entreprise à l'instant : ne change plus rien
        rep = self.requete(self.jetons["contributeur"], "tools/list")
        self.assertEqual(rep.status_code, 403)
        err = rep.json()["error"]
        self.assertEqual(err["data"]["reason"], "company_sign_in")
        self.assertIn("connexion d'entreprise est allumée", err["message"])
        self.assertNotIn("WWW-Authenticate", rep)  # pas une invitation à refaire un jeton

    def test_jeton_deja_mort_garde_le_message_commun(self):
        """Un jeton révoqué ne dit rien de la connexion d'entreprise : refus commun (401)."""
        self.allumer()
        JT.revoquer(self.contrib, JT.actifs(self.contrib).get().pk)
        rep = self.requete(self.jetons["contributeur"], "tools/list")
        self.assertEqual((rep.status_code, rep.json()["error"]["data"]["reason"]), (401, "invalid_token"))

    def test_eteinte_de_nouveau_les_jetons_servent(self):
        self.allumer()
        self.assertEqual(self.liste("contributeur"), 403)
        ReglageEntreprise.objects.filter(pk=1).update(actif=False)
        self.assertEqual(self.liste("contributeur"), 200)

    def test_compte_de_secours_regle_d_avant(self):
        self.allumer()
        self.assertEqual(self.liste("admin"), 200)  # gestionnaire des espaces : mot de passe permis
        self.assertTrue(JT.creer(self.admin, "Secours", 30)[0])

    def test_mot_de_passe_pour_tous_regle_d_avant(self):
        self.allumer()
        ReglageEntreprise.objects.filter(pk=1).update(mot_de_passe_pour_tous=True)
        self.assertEqual(self.liste("contributeur"), 200)
        self.assertTrue(JT.creer(self.contrib, "Encore", 30)[0])

    def test_creation_refusee_sans_mot_de_passe(self):
        self.allumer()
        self.lien(self.contrib, 0)
        with self.assertRaisesMessage(PermissionDenied, "vous ne pouvez donc pas créer de jeton d'assistant"):
            JT.creer(self.contrib, "Nouveau", 30)
        self.assertEqual(JT.actifs(self.contrib).count(), 1)  # seulement celui d'avant

    def test_mon_compte_le_dit_et_n_offre_pas_la_creation(self):
        self.allumer()
        c = Client()
        c.force_login(self.contrib)
        s = c.session  # session ouverte par le compte d'entreprise (une session par mot de passe serait fermée :
        s[CLE_METHODE] = "entreprise"  # test_session_permise_methode)
        s.save()
        rep = c.get("/mon-compte/")
        self.assertContains(rep, "vous ne pouvez donc pas utiliser d")
        self.assertContains(rep, "Vos jetons ci-dessous ne servent plus.")
        self.assertNotContains(rep, 'value="jeton_creer"')
        self.assertContains(rep, 'value="jeton_revoquer"')  # elle peut encore les révoquer
        rep = c.post("/mon-compte/", {"action": "jeton_creer", "nom": "Contourner", "jours": "30"})
        self.assertEqual(JT.actifs(self.contrib).count(), 1)
        c.force_login(self.admin)
        self.assertContains(c.get("/mon-compte/"), 'value="jeton_creer"')  # gestionnaire des espaces : comme avant

    def test_mot_de_passe_provisoire(self):
        """Éteinte : le mot de passe provisoire bloque le jeton comme avant. Allumée, sans mot de passe permis : refus de la
        connexion d'entreprise, avec son message."""
        Utilisateur.objects.filter(pk=self.contrib.pk).update(doit_changer_mdp=True)
        self.assertEqual(self.liste("contributeur"), 401)
        self.allumer()
        self.lien(self.contrib, 0)
        self.assertEqual(self.liste("contributeur"), 403)

    def test_compte_bloque_toujours_refuse(self):
        self.allumer()
        self.lien(self.contrib, 0)
        Compte.objects.filter(pk=self.contrib.pk).update(actif=False)
        self.assertEqual(self.liste("contributeur"), 401)

    def test_plus_de_delai_de_sept_jours(self):
        self.assertFalse(hasattr(regles, "PREUVE_JETONS_JOURS"))
        self.assertFalse(hasattr(regles, "preuve_recente"))
