"""Connexion par le compte d'entreprise réussie, contre le faux fournisseur (vraies signatures, vrai HTTP) : flux
« code » avec PKCE et ``state``, secret du client envoyé dans l'en-tête, adresse sans majuscules, page demandée
(``next``) gardée, lien avec le « sub », ligne de l'historique avec la méthode, connexion dans l'espace où la personne
a accès ; rien n'est créé (ni compte, ni rôle, ni attribution)."""
import base64
import urllib.parse

from django.test import Client

from espaces import contexte as E
from espaces.aides_tests import creer
from espaces.models import Compte
from referentiel.models import Attribution, HistoriqueConnexion, Utilisateur

from .aides_tests import RETOUR, BaseEntreprise
from .aides_tests.faux_fournisseur import CLIENT_ID, SECRET
from .flux import CLE_METHODE
from .models import LienEntreprise


class ConnexionReussieTests(BaseEntreprise):
    def test_parcours_complet(self):
        self.regler()
        avant = (Compte.objects.count(), Utilisateur.objects.count(), Attribution.objects.count(),
                 Utilisateur.objects.get(pk=self.contrib.pk).role)
        c, r = self.parcours(suivante="/saisie/")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], "/saisie/")
        self.assertEqual(int(self.connecte(c)), self.contrib.pk)
        self.assertEqual(c.session[CLE_METHODE], "entreprise")
        self.assertEqual(c.get("/mon-compte/").status_code, 200)  # session valable sur une page de l'outil
        # demande envoyée au fournisseur : flux « code », PKCE S256, state et nonce, adresse de retour de la racine
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.aller()[1]["Location"]).query))
        self.assertEqual((q["response_type"], q["code_challenge_method"], q["client_id"], q["scope"]),
                         ("code", "S256", CLIENT_ID, "openid email"))
        self.assertEqual(q["redirect_uri"], "http://testserver" + RETOUR)
        self.assertGreaterEqual(len(q["state"]), 40)
        self.assertGreaterEqual(len(q["nonce"]), 40)
        # échange du code : secret dans l'en-tête (client_secret_basic), vérificateur PKCE (vérifié par le faux fournisseur)
        echange = self.faux.echanges[-1]
        self.assertEqual(echange["authorization"], "Basic " + base64.b64encode(f"{CLIENT_ID}:{SECRET}".encode()).decode())
        self.assertNotIn("client_secret", echange)
        self.assertTrue(echange["code_verifier"])
        # historique : méthode « entreprise », dans l'espace de la page, sans jeton
        h = HistoriqueConnexion.objects.get()
        self.assertEqual((h.utilisateur_id, h.resultat, h.methode, h.motif, h.empreinte),
                         (self.contrib.pk, "reussie", "entreprise", "", ""))
        # lien avec le « sub » ; rien d'autre créé ni changé
        lien = LienEntreprise.objects.get()
        self.assertEqual((lien.compte_id, lien.emetteur, lien.sujet), (self.contrib.pk, self.faux.emetteur, "sujet-001"))
        self.assertEqual(avant, (Compte.objects.count(), Utilisateur.objects.count(), Attribution.objects.count(),
                                 Utilisateur.objects.get(pk=self.contrib.pk).role))

    def test_adresse_sans_tenir_compte_des_majuscules(self):
        self.regler()
        self.faux.claims = {"email": "  CONTRIB@Exemple.EXAMPLE "}
        c, _ = self.parcours()
        self.assertEqual(int(self.connecte(c)), self.contrib.pk)

    def test_email_verified_en_texte(self):
        self.regler()
        self.faux.claims = {"email_verified": "true"}
        c, _ = self.parcours()
        self.assertEqual(int(self.connecte(c)), self.contrib.pk)

    def test_secret_dans_le_formulaire_si_le_fournisseur_le_demande(self):
        self.regler()
        self.faux.decouverte = {"token_endpoint_auth_methods_supported": ["client_secret_post"]}
        c, _ = self.parcours()
        self.assertEqual(int(self.connecte(c)), self.contrib.pk)
        self.assertEqual(self.faux.echanges[-1]["client_secret"], SECRET)
        self.assertEqual(self.faux.echanges[-1]["authorization"], "")

    def test_espace_de_la_page(self):
        """Bouton de la page de connexion d'un autre espace : retour par l'adresse de la racine, session ouverte dans cet
        espace, historique noté dans sa base."""
        self.regler()
        u = creer("achats@exemple.example", "contributeur", "essai")
        self.faux.claims = {"email": "achats@exemple.example", "sub": "sujet-achats"}
        c, r = self.parcours(espace="essai", suivante="/espace/essai/saisie/")
        self.assertEqual(r["Location"], "/espace/essai/saisie/")
        self.assertEqual(int(self.connecte(c)), u.pk)
        with E.activer("essai"):
            self.assertEqual(list(HistoriqueConnexion.objects.values_list("utilisateur_id", "methode")), [(u.pk, "entreprise")])
        self.assertFalse(HistoriqueConnexion.objects.exists())

    def test_sans_acces_ici_connexion_dans_son_espace(self):
        self.regler()
        u = creer("achats@exemple.example", "contributeur", "essai")
        self.faux.claims = {"email": "achats@exemple.example", "sub": "sujet-achats"}
        c, r = self.parcours(suivante="/saisie/")
        self.assertEqual(r["Location"], "/espace/essai/")  # la page demandée d'un autre espace n'est pas suivie
        self.assertEqual(int(self.connecte(c)), u.pk)
        self.assertEqual(Compte.objects.get(pk=u.pk).dernier_espace, "essai")

    def test_deuxieme_connexion_meme_lien(self):
        self.regler()
        self.parcours()
        premiere = LienEntreprise.objects.get().derniere_le
        c, _ = self.parcours()
        self.assertEqual(int(self.connecte(c)), self.contrib.pk)
        self.assertEqual(LienEntreprise.objects.count(), 1)
        self.assertGreaterEqual(LienEntreprise.objects.get().derniere_le, premiere)

    def test_deconnexion_locale(self):
        """Se déconnecter ferme la session de l'outil (le fournisseur n'est pas appelé)."""
        self.regler()
        c, _ = self.parcours()
        appels = len(self.faux.appels)
        c.post("/deconnexion/")
        self.assertIsNone(self.connecte(c))
        self.assertNotIn(CLE_METHODE, c.session)
        self.assertEqual(len(self.faux.appels), appels)
        self.assertEqual(Client().get("/").status_code, 302)
