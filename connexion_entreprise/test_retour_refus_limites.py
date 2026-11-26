"""Retour du fournisseur (``flux.retour``) : ce qu'une requête anonyme peut écrire, et qui un refus peut bloquer.

- Connexion d'entreprise éteinte (défaut de toute installation) : un retour n'écrit rien (ni historique, ni session, ni
  compteur, ni journal du serveur) ; réponse sobre : la page de connexion.
- Allumée, ``state`` inconnu, rejoué ou absent : aucune session écrite ; une seule ligne d'historique par adresse et par
  période (comme la connexion par mot de passe, ``connexion.premier_refus``) ; le compteur par adresse avance (requêtes
  sans demande valide : la limite de 30 en 15 minutes reste), et une adresse bloquée est refusée avant tout.
- Refus après une authentification réussie chez le fournisseur (compte inconnu, désactivé, en double, adresse non
  vérifiée, lien) : compté pour CETTE personne (« sub » du fournisseur), jamais pour l'adresse réseau. Derrière le proxy
  d'une entreprise, toute la société a la même adresse : un refus ordinaire ne peut plus enfermer dehors tout le monde."""
from unittest import mock

from django.contrib.sessions.models import Session
from django.test import Client

from espaces import contexte as E
from parametres.libelles import libelle
from referentiel import connexion as CX
from referentiel.models import HistoriqueConnexion

from . import flux
from .aides_tests import RETOUR, BaseEntreprise
from .models import ReglageEntreprise
from .test_retour_attaques import messages_de


def sessions():
    with E.toutes_les_bases():
        return Session.objects.count()


class EteinteTests(BaseEntreprise):
    def test_quarante_retours_anonymes_n_ecrivent_rien(self):
        self.assertFalse(ReglageEntreprise.objects.exists())
        avant = (HistoriqueConnexion.objects.count(), sessions())
        with mock.patch.object(flux.journal, "info") as info, mock.patch.object(flux.journal, "warning") as warning:
            for i in range(40):
                c = Client()
                r = c.get(RETOUR, {"state": f"faux-{i}", "code": "x"} if i % 2 else {})
                self.assertEqual((r.status_code, r["Location"]), (302, "/connexion/"))
                self.assertNotIn("sessionid", r.cookies)
        self.assertEqual((HistoriqueConnexion.objects.count(), sessions()), avant)
        self.assertEqual((info.call_count, warning.call_count), (0, 0))
        self.assertEqual(CX.compteur().get(flux._cle_adresse(Client().get("/").wsgi_request), 0), 0)

    def test_reglage_present_mais_eteint(self):
        self.regler(actif=False)
        for _ in range(5):
            Client().get(RETOUR, {"state": "faux"})
        self.assertEqual(HistoriqueConnexion.objects.count(), 0)


class AllumeeSansDemandeTests(BaseEntreprise):
    def setUp(self):
        super().setUp()
        self.regler()

    def test_state_inconnu_une_ligne_par_periode_aucune_session(self):
        avant = sessions()
        for i in range(10):
            c = Client()
            r = c.get(RETOUR, {"state": f"faux-{i}", "code": "x"})
            self.assertEqual(r["Location"], "/connexion/")
            self.assertNotIn("sessionid", r.cookies)
        self.assertEqual(sessions(), avant)
        h = list(HistoriqueConnexion.objects.values_list("resultat", "methode", "motif"))
        self.assertEqual(h, [("echec", "entreprise", "expiree")])

    def test_adresse_bloquee_refusee_avant_tout(self):
        for i in range(flux.REFUS_MAX):
            Client().get(RETOUR, {"state": f"faux-{i}"})
        c, r = self.aller()
        self.assertEqual(r["Location"], "/connexion/")
        self.assertEqual(messages_de(c), [libelle("cadre.connexion.entreprise.refus.trop")])
        self.assertEqual(self.faux.appels, [])  # aucun appel au fournisseur
        n = HistoriqueConnexion.objects.count()
        Client().get(RETOUR, {"state": "encore"})
        self.assertEqual(HistoriqueConnexion.objects.count(), n)


class RefusApresAuthentificationTests(BaseEntreprise):
    def setUp(self):
        super().setUp()
        self.regler()

    def test_compte_inconnu_ne_bloque_pas_l_adresse(self):
        """Toute une entreprise derrière une adresse : 40 refus ordinaires (comptes inconnus) ne bloquent pas les autres."""
        self.faux.claims = {"email": "personne@exemple.example", "sub": "inconnu-1"}
        for _ in range(40):
            self.parcours()
        self.faux.claims = {}
        c, r = self.parcours()
        self.assertEqual(int(self.connecte(c)), self.contrib.pk)

    def test_refus_comptes_par_personne(self):
        """La même personne refusée encore et encore : au-delà de la limite, refusée tout de suite (message « trop »),
        une seule ligne d'historique de plus pour la période ; une autre personne n'est pas touchée."""
        self.faux.claims = {"email": "personne@exemple.example", "sub": "inconnu-2"}
        for _ in range(flux.REFUS_MAX_PERSONNE):
            self.parcours()
        n = HistoriqueConnexion.objects.count()
        self.assertEqual(n, flux.REFUS_MAX_PERSONNE)
        for _ in range(5):
            c, r = self.parcours()
        self.assertEqual(messages_de(c), [libelle("cadre.connexion.entreprise.refus.trop")])
        self.assertEqual(HistoriqueConnexion.objects.count(), n + 1)
        self.assertEqual(HistoriqueConnexion.objects.order_by("-pk").first().resultat, "bloquee")
        self.faux.claims = {}
        c, r = self.parcours()
        self.assertEqual(int(self.connecte(c)), self.contrib.pk)
