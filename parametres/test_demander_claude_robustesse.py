"""Fournisseur Claude (``FournisseurClaude.demander``) : une réponse HTTP coupée ou mal formée (``http.client``) et un
décompte de jetons qui n'est pas un nombre deviennent une ``ErreurIA`` au message clair, jamais une erreur 500."""
import http.client
import json
from unittest import mock

from parametres import ia_fournisseurs as F

from .test_fournisseur_claude import Reponse, SansBruit, erreur_http, requete, succes


class ReponseCoupeeTests(SansBruit):
    def code(self, exc=None, reponse=None):
        def ouvrir(req, delai):
            if exc is not None:
                raise exc
            return reponse
        with mock.patch.object(F, "_ouvrir", ouvrir), self.assertRaises(F.ErreurIA) as e:
            F.FournisseurClaude().demander(requete())
        return e.exception.code

    def test_erreurs_de_http_client(self):
        for exc in (http.client.IncompleteRead(b"{", 100), http.client.BadStatusLine("xx"),
                    http.client.RemoteDisconnected("fermé")):
            with self.subTest(exc=type(exc).__name__):
                self.assertIn(self.code(exc), ("reponse_invalide", "reseau"))
        self.assertEqual(self.code(http.client.IncompleteRead(b"{", 100)), "reponse_invalide")

    def test_lecture_coupee_pendant_read(self):
        class Coupee(Reponse):
            def read(self, *a):
                raise http.client.IncompleteRead(b"{", 100)
        self.assertEqual(self.code(reponse=Coupee(b"")), "reponse_invalide")

    def test_usage_ou_contenu_inattendus(self):
        texte = json.dumps({"explanation": "x"})
        for corps in ({"usage": {"input_tokens": "beaucoup"}, "content": [{"type": "text", "text": texte}]},
                      {"usage": {"input_tokens": {"a": 1}}, "content": [{"type": "text", "text": texte}]},
                      {"usage": "rien", "content": [{"type": "text", "text": texte}]},
                      {"content": 5}, {"content": [{"type": "text", "text": 5}]}):
            with self.subTest(corps=corps):
                self.assertEqual(self.code(reponse=Reponse(json.dumps(corps).encode())), "reponse_invalide")


class DelaiTotalTests(SansBruit):
    """La limite de temps (``Requete.delai``) vaut pour tout l'appel : la nouvelle tentative sans l'en-tête bêta n'a que
    le temps qui reste, et une lecture lente ne la dépasse pas."""

    def horloge(self):
        self.t = 1000.0
        reglage = mock.patch.object(F, "_maintenant", lambda: self.t)
        reglage.start()
        self.addCleanup(reglage.stop)

    def test_nouvelle_tentative_avec_le_temps_qui_reste(self):
        self.horloge()
        delais = []

        def ouvrir(req, delai):
            delais.append(delai)
            if len(delais) == 1:
                self.t += 25  # le refus de l'en-tête bêta arrive après 25 s sur 30
                raise erreur_http(400, "Unexpected value for the `anthropic-beta` header.")
            return succes()
        with mock.patch.object(F, "_ouvrir", ouvrir):
            F.FournisseurClaude().demander(requete())
        self.assertEqual(delais[0], 30)
        self.assertLessEqual(delais[1], 5)

    def test_plus_de_temps_pour_la_nouvelle_tentative(self):
        self.horloge()
        delais = []

        def ouvrir(req, delai):
            delais.append(delai)
            self.t += 31
            raise erreur_http(400, "Unexpected value for the `anthropic-beta` header.")
        with mock.patch.object(F, "_ouvrir", ouvrir), self.assertRaises(F.ErreurIA) as e:
            F.FournisseurClaude().demander(requete())
        self.assertEqual((e.exception.code, len(delais)), ("delai", 1))

    def test_lecture_lente_arretee_a_la_limite(self):
        self.horloge()
        test = self

        class Lente(Reponse):
            def read(self, n=-1):
                test.t += 10  # 10 s par morceau : la limite de 30 s passe avant la fin
                return super().read(8)
        with mock.patch.object(F, "_ouvrir", lambda req, delai: Lente(succes().getvalue())), \
                self.assertRaises(F.ErreurIA) as e:
            F.FournisseurClaude().demander(requete())
        self.assertEqual(e.exception.code, "delai")
