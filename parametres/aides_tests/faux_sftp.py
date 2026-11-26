"""Faux serveur SFTP pour les tests de la copie externe (``parametres/copie_sftp.py``), sans réseau : écrit avec les
classes serveur de la bibliothèque elle-même (``paramiko.ServerInterface``, ``SFTPServerInterface``), fichiers dans un
dossier temporaire. Clé du serveur (``cle_hote``) remplaçable pour simuler un serveur qui change de clé ; mot de passe ou
clé publique du client ; ``refus`` : opérations refusées (« remove », « write ») ; ``couper_apres`` : connexion coupée
après N octets écrits (une fois)."""
import os
import socket
import threading

import paramiko
from paramiko import SFTPAttributes, SFTPHandle, SFTPServer, SFTPServerInterface


class _Interface(paramiko.ServerInterface):
    def __init__(self, faux):
        self.faux = faux

    def get_allowed_auths(self, username):
        return "password,publickey"

    def check_auth_password(self, username, password):
        self.faux.authentifications.append(("password", username))
        ok = username == self.faux.identifiant and password == self.faux.mot_de_passe
        return paramiko.AUTH_SUCCESSFUL if ok else paramiko.AUTH_FAILED

    def check_auth_publickey(self, username, key):
        self.faux.authentifications.append(("publickey", username))
        ok = username == self.faux.identifiant and self.faux.cle_client is not None \
            and key.get_base64() == self.faux.cle_client.get_base64()
        return paramiko.AUTH_SUCCESSFUL if ok else paramiko.AUTH_FAILED

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED if kind == "session" else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED


class _Poignee(SFTPHandle):
    def write(self, offset, data):
        faux = self.faux
        if faux.couper_apres is not None:
            faux.ecrits += len(data)
            if faux.ecrits > faux.couper_apres:
                faux.couper_apres = None
                faux.ecrits = 0
                faux.couper()
                return paramiko.SFTP_FAILURE
        return super().write(offset, data)

    def stat(self):
        try:
            return SFTPAttributes.from_stat(os.fstat(self.readfile.fileno() if self.readfile else self.writefile.fileno()))
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)


def _systeme(faux):
    class Systeme(SFTPServerInterface):
        def __init__(self, server, *args, **kwargs):
            super().__init__(server, *args, **kwargs)

        def _reel(self, chemin):
            reel = os.path.realpath(os.path.join(faux.racine, chemin.lstrip("/")))
            if reel != faux.racine and not reel.startswith(faux.racine + os.sep):
                raise PermissionError(13, "outside")
            return reel

        def canonicalize(self, path):
            return "/" + os.path.relpath(self._reel(path), faux.racine).replace(os.sep, "/").lstrip(".")

        def list_folder(self, path):
            try:
                reel = self._reel(path)
                sortie = []
                for nom in os.listdir(reel):
                    a = SFTPAttributes.from_stat(os.stat(os.path.join(reel, nom)))
                    a.filename = nom
                    sortie.append(a)
                return sortie
            except OSError as e:
                return SFTPServer.convert_errno(e.errno)

        def stat(self, path):
            try:
                return SFTPAttributes.from_stat(os.stat(self._reel(path)))
            except OSError as e:
                return SFTPServer.convert_errno(e.errno)

        lstat = stat

        def open(self, path, flags, attr):
            ecriture = flags & (os.O_WRONLY | os.O_RDWR)
            if ecriture and "write" in faux.refus:
                return paramiko.SFTP_PERMISSION_DENIED
            try:
                fd = os.open(self._reel(path), flags | getattr(os, "O_BINARY", 0), 0o600)
                f = os.fdopen(fd, ("r+b" if flags & os.O_RDWR else "wb") if ecriture else "rb")
            except OSError as e:
                return SFTPServer.convert_errno(e.errno)
            h = _Poignee(flags)
            h.faux = faux
            h.filename = path
            if ecriture:
                h.writefile = f
            else:
                h.readfile = f
            return h

        def remove(self, path):
            if "remove" in faux.refus:
                return paramiko.SFTP_PERMISSION_DENIED
            try:
                os.remove(self._reel(path))
            except OSError as e:
                return SFTPServer.convert_errno(e.errno)
            return paramiko.SFTP_OK

        def rename(self, oldpath, newpath):
            try:
                if os.path.exists(self._reel(newpath)):
                    return paramiko.SFTP_FAILURE
                os.rename(self._reel(oldpath), self._reel(newpath))
            except OSError as e:
                return SFTPServer.convert_errno(e.errno)
            return paramiko.SFTP_OK

        def posix_rename(self, oldpath, newpath):
            try:
                os.replace(self._reel(oldpath), self._reel(newpath))
            except OSError as e:
                return SFTPServer.convert_errno(e.errno)
            return paramiko.SFTP_OK

        def mkdir(self, path, attr):
            if "mkdir" in faux.refus:
                return paramiko.SFTP_PERMISSION_DENIED
            try:
                os.mkdir(self._reel(path), 0o700)
            except OSError as e:
                return SFTPServer.convert_errno(e.errno)
            return paramiko.SFTP_OK

    return Systeme


class FauxSFTP:
    def __init__(self, racine, identifiant="copie", mot_de_passe="Mdp-SFTP-tres-secret-42", cle_hote=None, cle_client=None):
        self.racine = os.path.realpath(str(racine))
        self.identifiant, self.mot_de_passe, self.cle_client = identifiant, mot_de_passe, cle_client
        self.cle_hote = cle_hote or nouvelle_cle()
        self.refus, self.couper_apres, self.ecrits = set(), None, 0
        self.authentifications, self.transports = [], []
        self.ecoute = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.ecoute.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.ecoute.bind(("127.0.0.1", 0))
        self.ecoute.listen(8)
        self.port = self.ecoute.getsockname()[1]
        self.fini = False
        threading.Thread(target=self._accepter, daemon=True).start()

    def _accepter(self):
        while not self.fini:
            try:
                sock, _ = self.ecoute.accept()
            except OSError:
                return
            t = paramiko.Transport(sock)
            t.add_server_key(self.cle_hote)
            t.set_subsystem_handler("sftp", SFTPServer, _systeme(self))
            self.transports.append(t)
            try:
                t.start_server(server=_Interface(self))
            except (paramiko.SSHException, EOFError, OSError):
                continue

    def couper(self):
        for t in self.transports:
            try:
                t.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    @property
    def cle_publique(self):
        return f"{self.cle_hote.get_name()} {self.cle_hote.get_base64()}"

    def fermer(self):
        self.fini = True
        try:
            self.ecoute.close()
        except OSError:
            pass
        for t in self.transports:
            t.close()


def nouvelle_cle():
    """Clé d'hôte de test (Ed25519, créée par cryptography)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    import io

    cle = ed25519.Ed25519PrivateKey.generate()
    texte = cle.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
                              serialization.NoEncryption()).decode("ascii")
    return paramiko.Ed25519Key.from_private_key(io.StringIO(texte))


def cle_client_texte():
    """(texte de la clé privée au format OpenSSH, objet clé de paramiko) : une clé de client de test."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    import io

    cle = ed25519.Ed25519PrivateKey.generate()
    texte = cle.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
                              serialization.NoEncryption()).decode("ascii")
    return texte, paramiko.Ed25519Key.from_private_key(io.StringIO(texte))
