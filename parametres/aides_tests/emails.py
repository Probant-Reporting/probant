"""Aides des tests du serveur d'envoi réglé dans l'outil (``parametres/envoi_emails.py``) : réglages enregistrés, faux
serveurs qui répondent mal (identifiant refusé, réponse d'un autre service, silence), réglages de l'IT."""
import socket
import socketserver
import threading

from django.test import override_settings

from parametres import envoi_emails as EE

MDP = "Mdp-SMTP-tres-secret-7f3a"  # jamais dans une page, le journal, l'historique, une archive d'espace
HOTE, EXPEDITEUR, IDENTIFIANT = "smtp.outil.example", "envoi@outil.example", "compte-envoi@outil.example"

# Sans SMTP_HOST dans l'environnement (les réglages de l'outil servent) ; avec : le fichier de réglages gagne.
SANS_ENV = override_settings(EMAIL_HOST="", EMAIL_HOST_USER="", EMAIL_HOST_PASSWORD="")
AVEC_ENV = override_settings(EMAIL_HOST="smtp.it.example", EMAIL_PORT=2525, EMAIL_USE_TLS=True, EMAIL_USE_SSL=False,
                             EMAIL_HOST_USER="compte-it@it.example", EMAIL_HOST_PASSWORD="mdp-de-l-it",
                             DEFAULT_FROM_EMAIL="it@it.example")
SMTP_REEL = override_settings(EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend")


def regler(hote=HOTE, port=587, securite="starttls", identifiant=IDENTIFIANT, expediteur=EXPEDITEUR, mot_de_passe=MDP, par=None):
    """Réglages de l'outil enregistrés comme par la page (registre commun)."""
    return EE.enregistrer(par, hote, port, securite, identifiant, expediteur, mot_de_passe)


class _Gestionnaire(socketserver.StreamRequestHandler):
    def handle(self):
        s = self.server
        if s.genre == "muet":  # accepte la connexion et ne répond jamais
            s.fin.wait(5)
            return
        if s.genre == "http":  # un autre service (réponse qu'un bouton détourné pourrait recopier)
            self.wfile.write(b"HTTP/1.0 200 OK\r\nX-Interne: reponse-interne-42\r\n\r\n")
            return
        self.wfile.write(b"220 faux serveur\r\n")
        while True:
            ligne = self.rfile.readline(4096)
            if not ligne:
                return
            commande = ligne[:4].upper()
            if commande == b"EHLO":
                self.wfile.write(b"250-faux\r\n250 AUTH PLAIN LOGIN\r\n")
            elif commande == b"AUTH":
                self.wfile.write(b"535 5.7.8 banniere-secrete-du-serveur\r\n")
            elif commande == b"QUIT":
                self.wfile.write(b"221 bye\r\n")
                return
            else:
                self.wfile.write(b"250 ok\r\n")


class FauxServeur(socketserver.ThreadingTCPServer):
    """``genre`` : « refus_identifiant » (AUTH refusé en 535), « http » (pas un serveur d'e-mails), « muet »."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, genre):
        self.genre, self.fin = genre, threading.Event()
        super().__init__(("127.0.0.1", 0), _Gestionnaire)
        threading.Thread(target=self.serve_forever, daemon=True).start()

    @property
    def port(self):
        return self.server_address[1]

    def arreter(self):
        self.fin.set()
        self.shutdown()
        self.server_close()


def port_ferme():
    """Un port local sur lequel rien n'écoute (connexion refusée)."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
