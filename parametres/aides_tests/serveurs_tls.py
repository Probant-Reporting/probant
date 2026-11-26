"""Aides des tests des appels sortants en TLS (autorités de certification ajoutées par l'IT), sans réseau :

- ``Autorite`` : autorité de test créée dans le test (``cryptography``, dépendance des tests), qui signe des certificats
  de serveur pour ``localhost`` et ``127.0.0.1`` ;
- ``ServeurHttps`` : faux serveur HTTPS local (répond « ok » à tout GET) ;
- ``ServeurSmtp`` : faux serveur SMTP local, en STARTTLS (port 587) ou en SSL d'emblée (port 465), qui garde les
  e-mails reçus ;
- ``lancer_python(code, env)`` : un processus Python neuf (les réglages de l'outil y sont lus au démarrage, comme sur un
  serveur), avec un environnement sans autorité héritée de la machine de test (``SSL_CERT_FILE``…, proxys)."""
import datetime
import ipaddress
import os
import socketserver
import ssl
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

RACINE = Path(__file__).resolve().parent.parent.parent
# variables de la machine de test qui donneraient d'autres autorités ou un proxy aux appels : retirées
VARIABLES_RETIREES = ("SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "EXTRA_CA_CERTS",
                      "PROBANT_CA_BUNDLE", "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY",
                      "all_proxy", "SMTP_HOST", "DATABASE_URL")


def _nom(texte):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, texte)])


def _pem(cle):
    return cle.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


class Autorite:
    """Autorité de test (racine auto-signée) ; ``jours`` : durée de validité (négative : déjà expirée)."""

    def __init__(self, nom="Probant Test Internal CA", jours=365, autorite=True):
        self.nom = nom
        self.cle = ec.generate_private_key(ec.SECP256R1())
        maintenant = datetime.datetime.now(datetime.timezone.utc)
        debut = maintenant - datetime.timedelta(days=max(1, -jours + 1))
        b = (x509.CertificateBuilder().subject_name(_nom(nom)).issuer_name(_nom(nom)).public_key(self.cle.public_key())
             .serial_number(x509.random_serial_number()).not_valid_before(debut)
             .not_valid_after(maintenant + datetime.timedelta(days=jours))
             .add_extension(x509.BasicConstraints(ca=autorite, path_length=None), critical=True)
             .add_extension(x509.SubjectKeyIdentifier.from_public_key(self.cle.public_key()), critical=False))
        if autorite:
            b = b.add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False, key_encipherment=False,
                                              data_encipherment=False, key_agreement=False, key_cert_sign=True,
                                              crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
        self.certificat = b.sign(self.cle, hashes.SHA256())

    @property
    def pem(self):
        return self.certificat.public_bytes(serialization.Encoding.PEM)

    @property
    def expire(self):
        return self.certificat.not_valid_after_utc

    def ecrire(self, dossier, nom="autorite.pem"):
        chemin = Path(dossier) / nom
        chemin.write_bytes(self.pem)
        return chemin

    def certificat_serveur(self, dossier, noms=("localhost",), adresses=("127.0.0.1",), jours=30):
        """(certificat.pem, cle.pem) d'un serveur, signés par cette autorité."""
        cle = ec.generate_private_key(ec.SECP256R1())
        maintenant = datetime.datetime.now(datetime.timezone.utc)
        san = [x509.DNSName(n) for n in noms] + [x509.IPAddress(ipaddress.ip_address(a)) for a in adresses]
        cert = (x509.CertificateBuilder().subject_name(_nom(noms[0])).issuer_name(self.certificat.subject)
                .public_key(cle.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(maintenant - datetime.timedelta(days=max(1, -jours + 1)))
                .not_valid_after(maintenant + datetime.timedelta(days=jours))
                .add_extension(x509.SubjectAlternativeName(san), critical=False)
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                .add_extension(x509.SubjectKeyIdentifier.from_public_key(cle.public_key()), critical=False)
                .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(self.cle.public_key()), critical=False)
                .sign(self.cle, hashes.SHA256()))
        c, k = Path(dossier) / f"serveur-{noms[0]}.pem", Path(dossier) / f"serveur-{noms[0]}.key"
        c.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        k.write_bytes(_pem(cle))
        return c, k

    def contexte_serveur(self, dossier):
        c, k = self.certificat_serveur(dossier)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(c, k)
        return ctx


class ServeurHttps:
    def __init__(self, contexte):
        class Gestion(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, *args):
                pass

        self.serveur = ThreadingHTTPServer(("127.0.0.1", 0), Gestion)
        self.serveur.socket = contexte.wrap_socket(self.serveur.socket, server_side=True)
        self.serveur.handle_error = lambda *a: None  # poignée de main refusée par le client : attendu
        self.port = self.serveur.server_address[1]
        self.url = f"https://localhost:{self.port}/"
        threading.Thread(target=self.serveur.serve_forever, daemon=True).start()

    def fermer(self):
        self.serveur.shutdown()
        self.serveur.server_close()


class ServeurSmtp:
    """Faux serveur SMTP : ``mode`` « starttls » (texte clair, puis STARTTLS) ou « ssl » (TLS dès la connexion)."""

    def __init__(self, contexte, mode="starttls"):
        self.recus = []
        serveur_smtp = self

        class Gestion(socketserver.StreamRequestHandler):
            def setup(self):
                if mode == "ssl":
                    self.request = contexte.wrap_socket(self.request, server_side=True)
                super().setup()

            def dire(self, texte):
                self.wfile.write(texte.encode("ascii") + b"\r\n")
                self.wfile.flush()

            def handle(self):
                chiffre = mode == "ssl"
                self.dire("220 localhost ESMTP test")
                donnees = None
                while True:
                    ligne = self.rfile.readline()
                    if not ligne:
                        return
                    if donnees is not None:
                        if ligne in (b".\r\n", b".\n"):
                            serveur_smtp.recus.append(b"".join(donnees))
                            donnees = None
                            self.dire("250 OK")
                        else:
                            donnees.append(ligne)
                        continue
                    commande = ligne.decode("ascii", "replace").strip().upper()
                    if commande.startswith(("EHLO", "HELO")):
                        self.dire("250-localhost" if not chiffre else "250 localhost")
                        if not chiffre:
                            self.dire("250 STARTTLS")
                    elif commande == "STARTTLS" and not chiffre:
                        self.dire("220 Ready to start TLS")
                        self.request = contexte.wrap_socket(self.request, server_side=True)
                        self.rfile = self.request.makefile("rb")
                        self.wfile = self.request.makefile("wb")
                        chiffre = True
                    elif commande.startswith(("MAIL", "RCPT", "RSET", "NOOP")):
                        self.dire("250 OK")
                    elif commande == "DATA":
                        self.dire("354 End data with <CR><LF>.<CR><LF>")
                        donnees = []
                    elif commande == "QUIT":
                        self.dire("221 Bye")
                        return
                    else:
                        self.dire("502 Not implemented")

        class Serveur(socketserver.ThreadingTCPServer):
            daemon_threads = True
            allow_reuse_address = True

            def handle_error(self, *args):
                pass  # poignée de main refusée par le client : attendu

        self.serveur = Serveur(("127.0.0.1", 0), Gestion)
        self.port = self.serveur.server_address[1]
        threading.Thread(target=self.serveur.serve_forever, daemon=True).start()

    def fermer(self):
        self.serveur.shutdown()
        self.serveur.server_close()


def environnement(**variables):
    """Environnement d'un processus de l'outil : celui de la machine de test sans autorité ni proxy hérités, avec un
    dossier des données neuf (supprimé par l'appelant) et ``variables``."""
    env = {k: v for k, v in os.environ.items() if k not in VARIABLES_RETIREES}
    env.update({"DJANGO_SETTINGS_MODULE": "config.settings", "PYTHONDONTWRITEBYTECODE": "1", "DJANGO_SECRET_KEY": "essai-autorites",
                "DJANGO_LOG_LEVEL": "WARNING"})
    env.update({k: str(v) for k, v in variables.items()})
    return env


def lancer_python(code, env, timeout=60):
    """Lance ``code`` dans un processus Python neuf, depuis le dossier du projet."""
    return subprocess.run([sys.executable, "-c", code], cwd=RACINE, env=env, capture_output=True, text=True,
                          timeout=timeout)


def dossier_temporaire(test):
    d = Path(tempfile.mkdtemp(prefix="autorites-"))
    test.addCleanup(__import__("shutil").rmtree, d, True)
    return d
