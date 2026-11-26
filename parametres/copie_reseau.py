"""Copie externe des sauvegardes : adresses que l'outil peut joindre, et erreurs en clair (``copie_s3``, ``copie_sftp``).

L'hôte d'une destination est saisi par un gestionnaire des espaces (``espaces.comptes.est_gestionnaire``).
Même prudence que la connexion d'entreprise (``connexion_entreprise/sortant.py``, dont la
règle des adresses est reprise) : jamais la machine elle-même (127.0.0.0/8, ::1, sauf essais et développement :
``COPIE_EXTERNE_LOCAL``), ni une adresse locale au lien (169.254.0.0/16 : service de métadonnées des hébergeurs,
fe80::/10), multicast, réservée, non précisée ou un autre service de métadonnées connu (``sortant.METADONNEES``).
Les adresses privées restent permises : un NAS ou un MinIO interne est
un cas normal. Le nom est résolu une fois et toutes ses adresses sont contrôlées ; la connexion part vers une adresse
contrôlée (SFTP) ou l'adresse réellement jointe est contrôlée après la connexion (HTTPS) : un nom qui change d'adresse
entre les deux ne passe pas. Aucun appel n'a lieu sans destination réglée par l'administrateur.
"""
import ipaddress
import socket

from django.conf import settings

from connexion_entreprise.sortant import adresse_ip_permise as _permise_oidc


class ErreurCopie(Exception):
    """Échec d'une opération sur la destination. ``code`` : cause (libellé ``admin.copie.cause.<code>``) ; ``resume`` :
    nom de l'erreur et statut (« HTTPError 403 AccessDenied »), pour l'IT, jamais le texte renvoyé par le service."""

    def __init__(self, code, resume=""):
        super().__init__(f"{code}: {resume}" if resume else code)
        self.code, self.resume = code, (resume or "")[:200]


def local_permis():
    return bool(getattr(settings, "COPIE_EXTERNE_LOCAL", False))


def ip_permise(ip):
    """Vrai si la copie peut joindre cette adresse IP (texte) : règle de la connexion d'entreprise, avec la machine
    elle-même seulement en essai (``COPIE_EXTERNE_LOCAL``)."""
    return _permise_oidc(ip, local=local_permis())


def ip_privee(ip):
    """Adresse d'un réseau interne (10/8, 172.16/12, 192.168/16, fc00::/7…) ou, en essai, la machine elle-même."""
    try:
        a = ipaddress.ip_address(ip.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(a, ipaddress.IPv6Address) and a.ipv4_mapped is not None:
        a = a.ipv4_mapped
    if a.is_loopback:
        return local_permis()
    return a.is_private and not a.is_link_local


def resoudre(hote, port):
    """Adresses IP de ``hote`` (toutes contrôlées) ; ``ErreurCopie`` « introuvable » ou « adresse_refusee »."""
    try:
        infos = socket.getaddrinfo(hote, port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, OSError) as e:
        raise ErreurCopie("introuvable", type(e).__name__) from e
    adresses = list(dict.fromkeys(i[4][0] for i in infos))
    if not adresses or not all(ip_permise(a) for a in adresses):
        raise ErreurCopie("adresse_refusee", "ip")
    return adresses


def connecter(hote, port, delai):
    """Socket TCP ouverte vers une adresse contrôlée de ``hote`` (la première qui répond)."""
    derniere = None
    for ip in resoudre(hote, port):
        try:
            return socket.create_connection((ip, port), timeout=delai)
        except OSError as e:
            derniere = e
    raise derniere or ErreurCopie("injoignable")


def cause_reseau(e):
    """Code d'une erreur réseau ou TLS (« delai », « certificat »…), ou None."""
    import ssl

    if isinstance(e, ErreurCopie):
        return e.code
    if isinstance(e, ssl.SSLCertVerificationError):
        return "certificat"
    if isinstance(e, ssl.SSLError):
        return "tls"
    if isinstance(e, socket.gaierror):
        return "introuvable"
    if isinstance(e, (TimeoutError, socket.timeout)):
        return "delai"
    if isinstance(e, ConnectionRefusedError):
        return "refusee"
    if isinstance(e, (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)):
        return "coupee"
    if isinstance(e, OSError):
        return "injoignable"
    return None
