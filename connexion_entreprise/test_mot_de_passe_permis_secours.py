"""Mot de passe et connexion d'entreprise : rien ne change tant qu'elle est éteinte (installation mise à jour) ; allumée,
le mot de passe ne sert plus qu'aux gestionnaires des espaces (comptes de secours), même fournisseur en panne ; l'IT
peut la couper (COMPANY_SIGN_IN=off) ; le réglage « mot de passe pour tous » rend le mot de passe à chacun. La même
règle vaut pour la page de connexion de l'outil et pour celle du mode expert (/admin/)."""
from django.test import Client, override_settings

from espaces.aides_tests import MDP
from parametres.libelles import libelle
from referentiel.models import HistoriqueConnexion

from . import regles
from .aides_tests import BaseEntreprise
from .models import ReglageEntreprise


def connexion(identifiant, page="/connexion/"):
    c = Client()
    return c, c.post(page, {"username": identifiant, "password": MDP})


class MotDePasseTests(BaseEntreprise):
    def test_eteinte_par_defaut_rien_ne_change(self):
        """Installation existante après la mise à jour : aucun réglage, aucun bouton, mot de passe permis à tous."""
        self.assertFalse(ReglageEntreprise.objects.exists())
        self.assertFalse(regles.active())
        page = Client().get("/connexion/")
        self.assertNotContains(page, "/connexion/entreprise/")
        self.assertIsNone(page.context["connexion_entreprise"])
        for u in (self.contrib, self.admin, self.gestionnaire):
            c, r = connexion(u.email)
            self.assertEqual(r.status_code, 302, u.email)
            self.assertEqual(int(c.session["_auth_user_id"]), u.pk)
        self.assertEqual(set(HistoriqueConnexion.objects.values_list("methode", flat=True)), {"mot_de_passe"})
        # le bouton du début ne mène nulle part tant qu'elle est éteinte
        r = Client().get("/connexion/entreprise/")
        self.assertEqual(r["Location"], "/connexion/")
        self.assertFalse(self.faux.appels)

    def test_allumee_mot_de_passe_refuse_sauf_secours(self):
        self.regler()
        page = Client().get("/connexion/")
        self.assertContains(page, 'href="/connexion/entreprise/"')
        self.assertContains(page, libelle("cadre.connexion.entreprise.bouton_defaut"))
        for u in (self.contrib, self.admin):  # un administrateur d'espace qui n'est pas gestionnaire non plus
            c, r = connexion(u.email)
            self.assertEqual(r.status_code, 200, u.email)
            self.assertNotIn("_auth_user_id", c.session)
            self.assertContains(r, libelle("cadre.connexion.entreprise.incorrect").split(". ")[0])  # encart : 1re phrase en titre
        h = HistoriqueConnexion.objects.order_by("-pk").first()
        self.assertEqual((h.resultat, h.methode, h.motif, h.utilisateur_id), ("echec", "mot_de_passe", "mot_de_passe", self.admin.pk))
        # mauvais mot de passe : exactement le même message (rien ne dit que le mot de passe était bon,
        # test_formulaire_connexion_meme_reponse)
        c = Client()
        r = c.post("/connexion/", {"username": self.contrib.email, "password": "faux"})
        self.assertContains(r, libelle("cadre.connexion.entreprise.incorrect").split(". ")[0])
        # compte de secours : le gestionnaire des espaces
        c, r = connexion(self.gestionnaire.email)
        self.assertEqual(int(c.session["_auth_user_id"]), self.gestionnaire.pk)

    def test_mode_expert_meme_regle(self):
        self.regler()
        c, r = connexion(self.admin.email, "/admin/login/")
        self.assertNotIn("_auth_user_id", c.session)
        c, r = connexion(self.gestionnaire.email, "/admin/login/")
        self.assertEqual(int(c.session["_auth_user_id"]), self.gestionnaire.pk)

    def test_fournisseur_en_panne_le_secours_entre(self):
        """On ne peut pas s'enfermer dehors : fournisseur arrêté, le gestionnaire entre avec son mot de passe et éteint
        la connexion d'entreprise ; les autres retrouvent alors leur mot de passe."""
        self.regler(emetteur="http://127.0.0.1:9/realms/essai")
        with self.assertLogs("connexion_entreprise", "WARNING"):
            self.assertEqual(Client().get("/connexion/entreprise/")["Location"], "/connexion/")
        c, r = connexion(self.gestionnaire.email)
        self.assertEqual(int(c.session["_auth_user_id"]), self.gestionnaire.pk)
        with self.assertLogs("connexion_entreprise", "WARNING") as journal:  # éteinte : écrit au journal du serveur
            r = c.post("/administration/parametres/connexion-entreprise/", {"action": "enregistrer", "emetteur": self.faux.emetteur,
                                                                            "client_id": "probant-essai"})
        self.assertIn("turned off", journal.output[0])
        self.assertEqual(r.status_code, 302)
        self.assertFalse(regles.active())
        c, r = connexion(self.contrib.email)
        self.assertEqual(int(c.session["_auth_user_id"]), self.contrib.pk)

    def test_gestionnaire_bloque_n_est_plus_secours(self):
        from espaces.models import Compte

        self.regler()
        Compte.objects.filter(pk=self.gestionnaire.pk).update(actif=False)
        c, r = connexion(self.gestionnaire.email)
        self.assertNotIn("_auth_user_id", c.session)

    def test_mot_de_passe_pour_tous(self):
        self.regler(mot_de_passe_pour_tous=True)
        c, r = connexion(self.contrib.email)
        self.assertEqual(int(c.session["_auth_user_id"]), self.contrib.pk)
        self.assertContains(Client().get("/connexion/"), 'href="/connexion/entreprise/"')

    @override_settings(CONNEXION_ENTREPRISE_PERMISE=False)
    def test_coupee_par_l_it(self):
        self.regler()
        self.assertFalse(regles.active())
        self.assertNotContains(Client().get("/connexion/"), "/connexion/entreprise/")
        c, r = connexion(self.contrib.email)
        self.assertEqual(int(c.session["_auth_user_id"]), self.contrib.pk)
        self.assertEqual(Client().get("/connexion/entreprise/")["Location"], "/connexion/")
        self.assertFalse(self.faux.appels)

    def test_bibliotheques_absentes(self):
        """Version tout-en-un (Python pur, sans PyJWT ni cryptography) : éteinte, le mot de passe pour tous."""
        from unittest import mock

        self.regler()
        with mock.patch.object(regles, "bibliotheques", return_value=False):
            self.assertFalse(regles.active())
            self.assertNotContains(Client().get("/connexion/"), "/connexion/entreprise/")
            c, r = connexion(self.contrib.email)
            self.assertEqual(int(c.session["_auth_user_id"]), self.contrib.pk)

    def test_mot_de_passe_provisoire_pas_demande_par_le_compte_d_entreprise(self):
        from referentiel.models import Utilisateur

        self.regler()
        Utilisateur.objects.filter(pk=self.contrib.pk).update(doit_changer_mdp=True)
        c, r = self.parcours()
        self.assertEqual(c.get("/saisie/").status_code, 200)  # pas renvoyé vers « Mon compte »
        # compte de secours : son mot de passe provisoire reste à remplacer, même entré par l'entreprise
        Utilisateur.objects.filter(pk=self.gestionnaire.pk).update(doit_changer_mdp=True)
        self.faux.claims = {"email": self.gestionnaire.email, "sub": "sujet-gestion"}
        c, r = self.parcours()
        self.assertEqual(c.get("/saisie/")["Location"], "/mon-compte/")
