"""Appels sortants de la connexion d'entreprise (``sortant.demander``, point unique) : https seulement hors essais ;
jamais la machine elle-même, une adresse locale au lien (service de métadonnées) ou multicast ; adresses privées
permises (fournisseur interne) ; aucune redirection suivie ; réponse JSON de 1 Mo au plus ; contexte TLS vérifié."""
import ssl
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from django.test import SimpleTestCase, override_settings

from . import oidc, sortant


class _Serveur:
    """Petit serveur HTTP local : ``reponses`` = chemin → (statut, en-têtes, corps)."""

    def __init__(self, reponses):
        class Gestion(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                statut, entetes, corps = reponses.get(self.path, (404, {}, b"{}"))
                self.send_response(statut)
                for k, v in entetes.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(corps)

        self.serveur = ThreadingHTTPServer(("127.0.0.1", 0), Gestion)
        threading.Thread(target=self.serveur.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.serveur.server_address[1]}"

    def arreter(self):
        self.serveur.shutdown()
        self.serveur.server_close()


@override_settings(CONNEXION_ENTREPRISE_LOCAL=False)
class AdressesTests(SimpleTestCase):
    def refusee(self, url):
        with self.assertRaises(sortant.ErreurReseau) as e:
            sortant.demander(url)
        self.assertEqual(e.exception.code, "adresse_refusee", url)

    def test_https_seulement(self):
        for url in ("http://login.exemple.example/x", "ftp://login.exemple.example/x", "file:///etc/passwd",
                    "gopher://login.exemple.example/", "https://user:mdp@login.exemple.example/", "https:///x",
                    "https://login.exemple.example:99999/", "https://login exemple.example/"):
            self.refusee(url)

    def test_machine_elle_meme_et_metadonnees(self):
        for url in ("https://127.0.0.1/", "https://127.1.2.3/", "https://[::1]/", "https://localhost/", "https://169.254.169.254/",
                    "https://[fe80::1]/", "https://0.0.0.0/", "https://[::ffff:127.0.0.1]/", "https://224.0.0.1/"):
            self.refusee(url)

    def test_nom_qui_mene_a_une_adresse_interdite(self):
        with mock.patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("169.254.169.254", 443))]):
            self.refusee("https://metadonnees.exemple.example/latest")
        with mock.patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("10.0.0.5", 443)), (2, 1, 6, "", ("127.0.0.1", 443))]):
            self.refusee("https://double.exemple.example/")  # une seule adresse interdite suffit

    def test_adresses_privees_permises(self):
        for ip in ("10.0.0.5", "192.168.1.10", "172.16.0.1", "fd00::1", "203.0.113.5"):
            self.assertTrue(sortant.adresse_ip_permise(ip), ip)
        for ip in ("127.0.0.1", "::1", "169.254.169.254", "fe80::1", "0.0.0.0", "::ffff:127.0.0.1", "ff02::1", "x"):
            self.assertFalse(sortant.adresse_ip_permise(ip), ip)

    def test_adresse_reellement_jointe_controlee(self):
        """Le nom passe le contrôle (adresse publique), mais la connexion arrive sur la machine elle-même (nom qui change
        d'adresse entre le contrôle et la connexion) : refusé après la connexion."""
        serveur = _Serveur({"/": (200, {"Content-Type": "application/json"}, b"{}")})
        self.addCleanup(serveur.arreter)
        with override_settings(CONNEXION_ENTREPRISE_LOCAL=True):
            self.assertEqual(sortant.demander(serveur.base + "/"), (200, {}))  # témoin : joignable en essai
        # contrôles d'avant la connexion trompés (adresse et nom jugés bons) : la connexion elle-même est refusée
        with mock.patch.object(sortant, "_verifier_nom"), \
                mock.patch.object(sortant, "verifier_url", side_effect=urllib.parse.urlsplit):
            with self.assertRaises(sortant.ErreurReseau) as e:
                sortant.demander(serveur.base + "/")
        self.assertEqual((e.exception.code, e.exception.detail), ("adresse_refusee", "peer"))

    def test_contexte_tls_verifie(self):
        ctx = sortant.contexte_tls()
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)


class ReponsesTests(SimpleTestCase):
    """En essai (http sur la machine elle-même permis) : redirection, taille, JSON."""

    def setUp(self):
        self.serveur = _Serveur({
            "/redirige": (302, {"Location": "http://169.254.169.254/latest/meta-data/"}, b""),
            "/gros": (200, {"Content-Type": "application/json"}, b'{"a": "' + b"x" * (sortant.TAILLE_MAX + 10) + b'"}'),
            "/texte": (200, {"Content-Type": "text/html"}, b"<html>secret interne</html>"),
            "/ok": (200, {"Content-Type": "application/json"}, b'{"issuer": "x"}'),
            "/erreur": (500, {}, b"<html>trace</html>"),
        })
        self.addCleanup(self.serveur.arreter)

    def code(self, chemin):
        with self.assertRaises(sortant.ErreurReseau) as e:
            sortant.demander(self.serveur.base + chemin)
        return e.exception.code

    def test_redirection_jamais_suivie(self):
        self.assertEqual(self.code("/redirige"), "redirection")

    def test_reponse_trop_grosse(self):
        self.assertEqual(self.code("/gros"), "trop_gros")

    def test_reponse_qui_n_est_pas_du_json(self):
        self.assertEqual(self.code("/texte"), "pas_json")
        self.assertEqual(self.code("/erreur"), "statut")

    def test_json(self):
        self.assertEqual(sortant.demander(self.serveur.base + "/ok"), (200, {"issuer": "x"}))

    def test_decouverte_n_affiche_jamais_la_reponse(self):
        """Le bouton « Vérifier » ne donne qu'une cause courte : jamais le contenu de la réponse (pas de fuite d'un service
        interne par l'écran)."""
        faits, cause = oidc.essayer(self.serveur.base + "/texte")
        self.assertEqual(faits, [])
        self.assertNotIn("secret interne", cause)
