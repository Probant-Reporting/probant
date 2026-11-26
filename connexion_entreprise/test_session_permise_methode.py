"""Les sessions suivent la règle du mot de passe (``regles.session_permise``) : une session ouverte par mot de passe pour
un compte qui n'a plus droit au mot de passe (connexion d'entreprise allumée après coup, gestionnaire qui perd ce rôle)
est refusée à la requête suivante : retour à la page de connexion avec un message simple. Avant, elle restait valable
jusqu'à 12 heures, alors que les jetons des assistants étaient refusés aussitôt. Une session sans méthode notée (ouverte
avant la mise à jour) est traitée comme « mot de passe ». Sans effet quand la connexion d'entreprise est éteinte, coupée
par l'IT (COMPANY_SIGN_IN=off) ou laissée à tous (« chacun peut encore se connecter avec son mot de passe ») ; éteinte,
aucune requête de plus en base par page (mesure)."""
from django.conf import settings
from django.db import connections
from django.test import Client, override_settings
from django.test.utils import CaptureQueriesContext

from espaces.aides_tests import MDP
from espaces.models import Compte
from parametres.libelles import libelle

from . import flux, regles
from .aides_tests import BaseEntreprise
from .test_retour_attaques import messages_de

PAGE = "/administration/"
INTERGICIEL = "connexion_entreprise.intergiciels.SessionSelonLaRegleMiddleware"


def par_mot_de_passe(u):
    c = Client()
    r = c.post("/connexion/", {"username": u.email, "password": MDP})
    assert r.status_code == 302, r.content[:300]
    return c


class SessionsTests(BaseEntreprise):
    def test_methode_notee_a_l_ouverture(self):
        c = par_mot_de_passe(self.contrib)
        self.assertEqual(c.session[flux.CLE_METHODE], "mot_de_passe")
        self.regler()
        c, _ = self.parcours()
        self.assertEqual(c.session[flux.CLE_METHODE], "entreprise")

    def test_allumee_apres_coup_session_par_mot_de_passe_refusee(self):
        c = par_mot_de_passe(self.admin)  # administrateur qui n'est pas gestionnaire
        self.assertEqual(c.get(PAGE).status_code, 200)
        self.regler()
        r = c.get(PAGE)
        self.assertEqual((r.status_code, r["Location"]), (302, "/connexion/"))
        self.assertNotIn("_auth_user_id", c.session)
        self.assertEqual(messages_de(c), [libelle("cadre.connexion.entreprise.session_fermee")])

    def test_session_sans_methode_traitee_comme_mot_de_passe(self):
        c = Client()
        c.force_login(self.contrib)  # session d'avant la mise à jour : aucune méthode notée
        self.regler()
        self.assertEqual(c.get("/pour-moi/")["Location"], "/connexion/")

    def test_session_d_entreprise_garde(self):
        self.regler()
        c, _ = self.parcours()
        self.assertEqual(c.get("/pour-moi/").status_code, 200)

    def test_gestionnaire_qui_perd_le_role(self):
        self.regler()
        c = par_mot_de_passe(self.gestionnaire)  # compte de secours
        self.assertEqual(c.get(PAGE).status_code, 200)
        Compte.objects.filter(pk=self.gestionnaire.pk).update(gestionnaire=False)
        self.assertEqual(c.get(PAGE)["Location"], "/connexion/")

    def test_compte_bloque(self):
        c = par_mot_de_passe(self.contrib)
        Compte.objects.filter(pk=self.contrib.pk).update(actif=False)
        self.assertEqual(c.get("/pour-moi/")["Location"].split("?")[0], "/connexion/")

    def test_mot_de_passe_pour_tous_et_coupee_par_l_it(self):
        c = par_mot_de_passe(self.contrib)
        self.regler(mot_de_passe_pour_tous=True)
        self.assertEqual(c.get("/pour-moi/").status_code, 200)
        self.regler()
        with override_settings(CONNEXION_ENTREPRISE_PERMISE=False):
            self.assertEqual(c.get("/pour-moi/").status_code, 200)
        self.assertEqual(c.get("/pour-moi/")["Location"], "/connexion/")

    def test_requete_de_script_401(self):
        c = par_mot_de_passe(self.contrib)
        self.regler()
        r = c.get("/pour-moi/", HTTP_X_REQUESTED_WITH="fetch")
        self.assertEqual(r.status_code, 401)
        self.assertNotIn("_auth_user_id", c.session)

    def test_eteinte_aucune_requete_de_plus(self):
        self.assertIn(INTERGICIEL, settings.MIDDLEWARE)
        c = par_mot_de_passe(self.admin)
        c.get(PAGE)  # état mis en cache
        sans = [m for m in settings.MIDDLEWARE if m != INTERGICIEL]

        def compter():
            with CaptureQueriesContext(connections["default"]) as d, CaptureQueriesContext(connections["commun"]) as m:
                self.assertEqual(c.get(PAGE).status_code, 200)
            return len(d) + len(m)

        avec = compter()
        with override_settings(MIDDLEWARE=sans):
            sans_n = compter()
        self.assertEqual(avec, sans_n)
        self.assertFalse(regles.active())
