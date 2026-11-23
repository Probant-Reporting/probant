"""Fake e-mail server (SMTP) to try the reminders and the test e-mail without really sending anything.

No e-mail leaves the machine: each message received is shown in the terminal and added to a JSON file (list of
messages: date, sender, recipients, subject, text). No dependency: standard library only.

In a first terminal:
    python3 qa/fake_smtp.py                     # listens on 127.0.0.1:1025
    python3 qa/fake_smtp.py --port 1026 --file /tmp/emails.json

In a second terminal, the tool connected to this fake server:
    SMTP_HOST=127.0.0.1 SMTP_PORT=1025 SMTP_SECURITY=none python3 manage.py runserver

Stop: Ctrl+C. The file is rewritten in full at each message (it can be read at any time).
"""
import argparse
import datetime
import email
import email.policy
import json
import os
import socketserver
import sys
import tempfile
import threading

VERROU = threading.Lock()


def _texte(message):
    """Texte lisible d'un e-mail : la partie text/plain, sinon la première partie texte."""
    corps = message.get_body(preferencelist=("plain", "html"))
    return corps.get_content().replace("\r\n", "\n") if corps is not None else ""


class Session(socketserver.StreamRequestHandler):
    """Une connexion SMTP : EHLO/HELO, AUTH (tout est accepté), MAIL FROM, RCPT TO, DATA, RSET, NOOP, QUIT."""

    def repondre(self, ligne):
        self.wfile.write((ligne + "\r\n").encode("utf-8"))
        self.wfile.flush()

    def handle(self):
        self.repondre("220 faux-smtp prêt (rien n'est envoyé pour de vrai)")
        expediteur, destinataires = "", []
        while True:
            brut = self.rfile.readline(65536)
            if not brut:
                return
            ligne = brut.decode("utf-8", "replace").rstrip("\r\n")
            commande = ligne[:4].upper()
            if commande == "EHLO":
                self.wfile.write(b"250-faux-smtp\r\n250-AUTH PLAIN LOGIN\r\n250-8BITMIME\r\n250 SMTPUTF8\r\n")
                self.wfile.flush()
            elif commande == "HELO":
                self.repondre("250 faux-smtp")
            elif commande == "AUTH":
                mots = ligne.split()
                if len(mots) >= 2 and mots[1].upper() == "LOGIN":
                    for _ in range(2 if len(mots) == 2 else 1):  # identifiant puis mot de passe, non vérifiés
                        self.repondre("334 ")
                        self.rfile.readline(65536)
                elif len(mots) == 2:  # AUTH PLAIN sans la donnée sur la même ligne
                    self.repondre("334 ")
                    self.rfile.readline(65536)
                self.repondre("235 authentification acceptée (fausse)")
            elif ligne[:10].upper() == "MAIL FROM:":
                expediteur, destinataires = ligne[10:].strip().split()[0].strip("<>") if ligne[10:].strip() else "", []
                self.repondre("250 OK")
            elif ligne[:8].upper() == "RCPT TO:":
                destinataires.append(ligne[8:].strip().split()[0].strip("<>"))
                self.repondre("250 OK")
            elif commande == "DATA":
                self.repondre("354 fin par une ligne contenant un seul point")
                lignes = []
                while True:
                    l = self.rfile.readline(1 << 20)
                    if not l or l in (b".\r\n", b".\n"):
                        break
                    lignes.append(l[1:] if l.startswith(b"..") else l)
                self.server.recevoir(expediteur, destinataires, b"".join(lignes))
                self.repondre("250 OK message reçu")
                expediteur, destinataires = "", []
            elif commande == "RSET":
                expediteur, destinataires = "", []
                self.repondre("250 OK")
            elif commande == "NOOP":
                self.repondre("250 OK")
            elif commande == "QUIT":
                self.repondre("221 au revoir")
                return
            else:  # STARTTLS compris : le faux serveur ne chiffre pas (SMTP_SECURITE=aucune)
                self.repondre("502 commande non prise en charge")


class FauxSMTP(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, adresse, fichier, silencieux=False):
        super().__init__(adresse, Session)
        self.fichier, self.silencieux = fichier, silencieux
        with VERROU, open(fichier, "w", encoding="utf-8") as f:  # chaque lancement repart d'une liste vide
            json.dump([], f)

    def recevoir(self, expediteur, destinataires, donnees):
        m = email.message_from_bytes(donnees, policy=email.policy.default)
        recu = {"date": datetime.datetime.now().astimezone().isoformat(timespec="seconds"), "expediteur": expediteur,
                "destinataires": destinataires, "a": str(m.get("To", "")), "sujet": str(m.get("Subject", "")), "texte": _texte(m)}
        with VERROU:
            try:
                with open(self.fichier, encoding="utf-8") as f:
                    tous = json.load(f)
            except (OSError, ValueError):
                tous = []
            tous.append(recu)
            provisoire = self.fichier + ".tmp"
            with open(provisoire, "w", encoding="utf-8") as f:
                json.dump(tous, f, ensure_ascii=False, indent=1)
            os.replace(provisoire, self.fichier)
        if not self.silencieux:
            print(f"[{recu['date']}] e-mail no. {len(tous)} to {', '.join(destinataires)}: {recu['sujet']}", flush=True)


def main():
    a = argparse.ArgumentParser(description="Fake e-mail server: nothing is sent, everything is recorded in a JSON file.")
    # noms anglais ; les anciens noms français restent acceptés
    a.add_argument("--host", "--hote", dest="hote", default="127.0.0.1")
    a.add_argument("--port", type=int, default=1025)
    a.add_argument("--file", "--fichier", dest="fichier", default=os.path.join(tempfile.gettempdir(), "faux_smtp_emails.json"),
                   help="JSON file of the e-mails received (emptied at startup)")
    a.add_argument("--quiet", "--silencieux", dest="silencieux", action="store_true", help="show nothing for each e-mail")
    o = a.parse_args()
    serveur = FauxSMTP((o.hote, o.port), o.fichier, o.silencieux)
    print(f"Fake e-mail server on {o.hote}:{o.port}. E-mails received recorded in {o.fichier}.\n"
          f"Start the tool with: SMTP_HOST={o.hote} SMTP_PORT={o.port} SMTP_SECURITY=none python3 manage.py runserver\n"
          "Stop: Ctrl+C.", flush=True)
    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        serveur.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
