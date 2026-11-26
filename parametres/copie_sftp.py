"""Copie externe des sauvegardes vers un serveur SFTP, par la bibliothèque ``paramiko`` (SSH et SFTP, elle-même appuyée
sur ``cryptography``) : aucune cryptographie écrite ici. Absente de la version tout-en-un (Python pur) : ``disponible``.

- Clé du serveur ÉPINGLÉE : au premier essai, l'outil lit la clé que le serveur présente et s'arrête là, sans envoyer ni
  mot de passe ni signature (``CleAConfirmer``) ; l'écran montre son empreinte SHA-256 (forme d'OpenSSH,
  « SHA256:… ») et l'administrateur la confirme après l'avoir comparée à celle que donne l'IT. Ensuite, toute autre clé
  est refusée avant l'authentification (``ErreurCopie("empreinte")``) : jamais d'acceptation silencieuse d'une clé
  inconnue. Aucun fichier ``known_hosts`` ni ``~/.ssh`` n'est lu ; aucun agent SSH n'est utilisé.
- Authentification : mot de passe OU clé privée (Ed25519, ECDSA, RSA ; sans phrase secrète : une clé dédiée à la copie).
- Dépôt : dans un fichier caché « .nom.part », renommé à la fin (un fichier au nom final est toujours complet), puis
  taille relue. Le protocole SFTP ne donne pas l'empreinte d'un fichier distant : la taille seule est vérifiée.
- Réseau : connexion vers une adresse contrôlée (``copie_reseau.connecter``) ; délais bornés.
"""
import base64
import errno
import hashlib
import io
import logging
import posixpath
import socket
import stat as ST

from .copie_reseau import ErreurCopie, cause_reseau, connecter

logging.getLogger("paramiko").setLevel(logging.CRITICAL)  # ses lignes de connexion : la copie journalise sa propre cause

TYPES_RSA = ("rsa-sha2-512", "rsa-sha2-256", "ssh-rsa")


def disponible():
    try:
        import paramiko  # noqa: F401
    except ImportError:
        return False
    return True


class CleAConfirmer(ErreurCopie):
    """Aucune clé épinglée : la clé présentée par le serveur (``cle``, « type base64 ») attend la confirmation de
    l'administrateur. Rien d'autre n'a été envoyé au serveur."""

    def __init__(self, cle):
        super().__init__("empreinte_a_confirmer", "")
        self.cle = cle


class CleDifferente(ErreurCopie):
    """La clé présentée n'est pas la clé épinglée : refus avant toute authentification."""

    def __init__(self, cle):
        super().__init__("empreinte", "host key differs from the pinned key")
        self.cle = cle


def empreinte(cle):
    """Empreinte SHA-256 d'une clé « type base64 », comme OpenSSH l'affiche (« SHA256:… », base64 sans « = »)."""
    try:
        blob = base64.b64decode(cle.split()[1], validate=True)
    except (IndexError, ValueError):
        return ""
    return "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode("ascii").rstrip("=")


def type_cle(cle):
    return (cle or "").split(" ", 1)[0]


def lire_cle_privee(texte):
    """Objet clé de ``paramiko`` d'une clé privée collée (format OpenSSH ou PEM) ; ``ErreurCopie`` « cle_protegee »
    (phrase secrète) ou « cle_privee » (illisible)."""
    import paramiko

    texte = (texte or "").strip() + "\n"
    for genre in (paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.RSAKey):
        try:
            return genre.from_private_key(io.StringIO(texte))
        except paramiko.PasswordRequiredException:
            raise ErreurCopie("cle_protegee") from None
        except (paramiko.SSHException, ValueError, TypeError, IndexError):
            continue
    raise ErreurCopie("cle_privee")


def _erreur_sftp(e, operation):
    if isinstance(e, ErreurCopie):
        return e
    import paramiko

    if isinstance(e, paramiko.AuthenticationException):
        return ErreurCopie("identifiants", type(e).__name__)
    if isinstance(e, (FileNotFoundError,)) or getattr(e, "errno", None) == errno.ENOENT:
        return ErreurCopie("dossier", type(e).__name__)
    if isinstance(e, PermissionError) or getattr(e, "errno", None) == errno.EACCES:
        return ErreurCopie(f"droits_{operation}", type(e).__name__)
    if isinstance(e, (socket.timeout, TimeoutError)):
        return ErreurCopie("delai", type(e).__name__)
    if isinstance(e, paramiko.SSHException):
        return ErreurCopie("ssh", type(e).__name__)
    if isinstance(e, EOFError):
        return ErreurCopie("coupee", type(e).__name__)
    code = cause_reseau(e)
    return ErreurCopie(code or "service", type(e).__name__)


class ClientSFTP:
    """Un dossier d'un serveur SFTP (``base`` : « identifiant-de-l-installation/ » sous ``dossier``). Mêmes opérations que
    ``copie_s3.ClientS3`` : ``taille``, ``deposer``, ``lire``, ``supprimer``, ``lister``."""

    def __init__(self, hote, port, identifiant, mot_de_passe, cle_privee, dossier, cle_epinglee, base="", delai=60):
        self.hote, self.port, self.identifiant = hote, int(port or 22), identifiant
        self.mot_de_passe, self.cle_privee = mot_de_passe or "", cle_privee or ""
        self.dossier = (dossier or "").rstrip("/") or "."
        self.cle_epinglee, self.base, self.delai = (cle_epinglee or "").strip(), base, delai
        self.cle_vue = ""
        self._transport = self._sftp = None

    def __enter__(self):
        try:
            self.ouvrir()
        except BaseException:
            self.fermer()
            raise
        return self

    def __exit__(self, *exc):
        self.fermer()

    def fermer(self):
        for objet in (self._sftp, self._transport):
            if objet is not None:
                try:
                    objet.close()
                except Exception:  # noqa: BLE001
                    pass
        self._sftp = self._transport = None

    def ouvrir(self):
        import paramiko

        pkey = lire_cle_privee(self.cle_privee) if self.cle_privee else None
        try:
            sock = connecter(self.hote, self.port, self.delai)
        except ErreurCopie:
            raise
        except OSError as e:
            raise ErreurCopie(cause_reseau(e) or "injoignable", type(e).__name__) from e
        try:
            t = paramiko.Transport(sock)
            t.banner_timeout = t.handshake_timeout = t.auth_timeout = self.delai
            self._transport = t
            options = t.get_security_options()
            epingle = type_cle(self.cle_epinglee)
            if epingle:  # le serveur présente d'abord une clé du type épinglé (il peut en avoir plusieurs)
                voulus = TYPES_RSA if epingle == "ssh-rsa" else (epingle,)
                options.key_types = tuple([k for k in voulus if k in options.key_types]
                                          + [k for k in options.key_types if k not in voulus])
            t.start_client(timeout=self.delai)
            cle = t.get_remote_server_key()
            self.cle_vue = f"{cle.get_name()} {cle.get_base64()}"
            if not self.cle_epinglee:
                raise CleAConfirmer(self.cle_vue)
            if self.cle_vue.split()[1] != self.cle_epinglee.split()[1]:
                raise CleDifferente(self.cle_vue)
            if pkey is not None:
                t.auth_publickey(self.identifiant, pkey)
            else:
                t.auth_password(self.identifiant, self.mot_de_passe)
            self._sftp = paramiko.SFTPClient.from_transport(t)
            self._sftp.get_channel().settimeout(self.delai)
        except (ErreurCopie, KeyboardInterrupt):
            raise
        except Exception as e:  # noqa: BLE001 - toute erreur de la négociation devient une cause en clair
            raise _erreur_sftp(e, "ecrire") from e

    def _chemin(self, rel=""):
        return posixpath.join(self.dossier, self.base, rel) if rel else posixpath.join(self.dossier, self.base).rstrip("/")

    def _creer_dossiers(self, chemin):
        morceaux, courant = [], chemin
        while courant not in ("", ".", "/"):
            try:
                if ST.S_ISDIR(self._sftp.stat(courant).st_mode):
                    break
            except FileNotFoundError:
                pass
            except OSError as e:
                if getattr(e, "errno", None) != errno.ENOENT:
                    raise
            morceaux.append(courant)
            courant = posixpath.dirname(courant)
        for d in reversed(morceaux):
            try:
                self._sftp.mkdir(d, 0o700)
            except OSError:
                if not ST.S_ISDIR(self._sftp.stat(d).st_mode):
                    raise

    def _appel(self, operation, fonction, *args):
        try:
            return fonction(*args)
        except ErreurCopie:
            raise
        except Exception as e:  # noqa: BLE001
            raise _erreur_sftp(e, operation) from e

    def taille(self, rel):
        def lire():
            try:
                return self._sftp.stat(self._chemin(rel)).st_size, None
            except FileNotFoundError:
                return None
            except OSError as e:
                if getattr(e, "errno", None) == errno.ENOENT:
                    return None
                raise
        return self._appel("lire", lire)

    def deposer(self, rel, chemin_local, taille, sha256):
        final = self._chemin(rel)
        dossier, nom = posixpath.split(final)
        partiel = posixpath.join(dossier, f".{nom}.part")

        def envoyer():
            self._creer_dossiers(dossier)
            with open(chemin_local, "rb") as f:
                self._sftp.putfo(f, partiel, file_size=taille, confirm=True)
            try:
                self._sftp.posix_rename(partiel, final)
            except OSError:  # serveur sans l'extension : remplacer en deux temps
                try:
                    self._sftp.remove(final)
                except OSError:
                    pass
                self._sftp.rename(partiel, final)
            if self._sftp.stat(final).st_size != taille:
                raise ErreurCopie("integrite", "size differs after upload")
        try:
            self._appel("ecrire", envoyer)
        except BaseException:
            try:
                self._sftp.remove(partiel)
            except Exception:  # noqa: BLE001
                pass
            raise

    def lire(self, rel, maxi=1024 * 1024):
        def lire():
            with self._sftp.open(self._chemin(rel), "rb") as f:
                return f.read(maxi)
        return self._appel("lire", lire)

    def supprimer(self, rel):
        def supprimer():
            try:
                self._sftp.remove(self._chemin(rel))
            except FileNotFoundError:
                pass
        self._appel("supprimer", supprimer)

    def lister(self):
        """[(chemin relatif à ``base``, taille)] : fichiers de ``base`` et de ses sous-dossiers (deux niveaux au plus :
        « spaces/<code>/ », « shared/ »)."""
        sortie = []

        def parcourir(rel, profondeur):
            try:
                entrees = self._sftp.listdir_attr(self._chemin(rel) if rel else self._chemin())
            except FileNotFoundError:
                return
            except OSError as e:
                if getattr(e, "errno", None) == errno.ENOENT:
                    return
                raise
            for a in entrees:
                chemin = f"{rel}{a.filename}"
                if ST.S_ISDIR(a.st_mode or 0):
                    if profondeur < 2:
                        parcourir(chemin + "/", profondeur + 1)
                elif ST.S_ISREG(a.st_mode or 0):
                    sortie.append((chemin, a.st_size or 0))
        self._appel("lister", parcourir, "", 0)
        return sortie
