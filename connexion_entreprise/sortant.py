"""Seul point de la connexion d'entreprise qui appelle l'extérieur (le fournisseur d'identité).

Les appels n'ont lieu que sur un geste d'une personne : clic sur le bouton de connexion, retour du fournisseur, bouton
« Essayer » ou enregistrement du réglage. Jamais au démarrage, jamais la nuit.

- ``contexte_tls`` : le seul endroit qui crée le contexte TLS des appels sortants (certificats vérifiés, nom d'hôte
  vérifié). Une autorité de certification interne s'ajoutera ici.
- ``demander`` : un appel (GET, ou POST d'un formulaire), réponse JSON seulement, 1 Mo au plus, délai court
  (``CONNEXION_ENTREPRISE_DELAI`` par opération, deux fois ce délai au total), aucune redirection suivie.
- Adresses (SSRF : l'adresse du fournisseur est saisie par un gestionnaire des espaces) : https seulement ; jamais une
  adresse de la machine elle-même (127.0.0.0/8, ::1), locale au lien (169.254.0.0/16 : service de métadonnées des
  hébergeurs, fe80::/10), multicast, réservée, non précisée, ou un autre service de métadonnées connu (``METADONNEES`` :
  AWS et Google en IPv6, Alibaba, Oracle, Azure). Les adresses privées restent permises (fournisseur
  interne de l'entreprise). Contrôle du nom avant l'appel (toutes ses adresses), puis de l'adresse réellement jointe
  après la connexion (un nom qui change d'adresse entre les deux ne passe pas). Derrière un proxy (variables
  HTTPS_PROXY…), le proxy joint le fournisseur : seul le contrôle du nom reste (adresse IP écrite telle quelle, ou nom
  que la machine sait résoudre). Essais et développement
  (``CONNEXION_ENTREPRISE_LOCAL``) : http et la machine elle-même permis (faux fournisseur des tests).
"""
import http.client
import ipaddress
import json
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

TAILLE_MAX = 1024 * 1024


class ErreurReseau(Exception):
    """Appel impossible ou réponse refusée. ``code`` : adresse_refusee, injoignable, delai, redirection, statut,
    trop_gros, pas_json, tls."""

    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code, self.detail = code, detail


def contexte_tls():
    """Contexte TLS de tous les appels sortants de la connexion d'entreprise (point unique)."""
    return ssl.create_default_context()


def local_permis():
    return bool(getattr(settings, "CONNEXION_ENTREPRISE_LOCAL", False))


# services de métadonnées des hébergeurs qui ne sont pas locaux au lien (169.254.169.254, AWS, Azure, Google, OpenStack…,
# l'est déjà) : ils donnent les identifiants de la machine
METADONNEES = frozenset(ipaddress.ip_address(a) for a in (
    "fd00:ec2::254",  # AWS, IPv6 (Nitro)
    "fd20:ce::254",  # Google Compute Engine, IPv6
    "100.100.100.200",  # Alibaba Cloud
    "192.0.0.192",  # Oracle Cloud (Classic)
    "168.63.129.16",  # Azure « WireServer » (configuration de la machine, certificats des extensions)
))


def adresse_ip_permise(ip, local=None):
    """Vrai si l'outil peut joindre cette adresse IP (texte). ``local`` : la machine elle-même est-elle permise (par
    défaut : ``CONNEXION_ENTREPRISE_LOCAL`` ; la copie externe des sauvegardes donne son propre réglage)."""
    try:
        a = ipaddress.ip_address(ip.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(a, ipaddress.IPv6Address) and a.ipv4_mapped is not None:
        a = a.ipv4_mapped
    if a.is_loopback:
        return local_permis() if local is None else bool(local)
    return not (a.is_link_local or a.is_multicast or a.is_unspecified or a.is_reserved or a in METADONNEES)


def verifier_url(url):
    """Adresse découpée (``urllib.parse``) si elle peut être appelée, sinon ``ErreurReseau("adresse_refusee")`` : schéma
    https (http seulement sur la machine elle-même, en essai), hôte présent, ni identifiant ni mot de passe."""
    try:
        u = urllib.parse.urlsplit(url or "")
        if u.port is not None and not 0 < u.port < 65536:  # port hors bornes : ValueError dès la lecture
            raise ValueError("port")
    except ValueError as e:
        raise ErreurReseau("adresse_refusee", "malformed") from e
    hote = (u.hostname or "").lower()
    if not hote or u.username or u.password or any(c in (url or "") for c in "\r\n\t "):
        raise ErreurReseau("adresse_refusee", "host")
    if u.scheme == "https":
        pass
    elif u.scheme == "http" and local_permis() and _est_local(hote):
        pass
    else:
        raise ErreurReseau("adresse_refusee", "scheme")
    return u


def _est_local(hote):
    if hote == "localhost":
        return True
    try:
        return ipaddress.ip_address(hote).is_loopback
    except ValueError:
        return False


def _par_un_proxy(u):
    proxies = urllib.request.getproxies()
    return u.scheme in proxies and not urllib.request.proxy_bypass(u.hostname or "")


def _verifier_nom(u):
    """Toutes les adresses du nom doivent être permises, même derrière un proxy (une adresse IP écrite telle quelle se
    « résout » toujours en elle-même) ; seul un nom que la machine ne sait pas résoudre part au proxy, qui le résout."""
    hote = u.hostname or ""
    try:
        infos = socket.getaddrinfo(hote, u.port or (443 if u.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, OSError) as e:
        if _par_un_proxy(u):
            return
        raise ErreurReseau("injoignable", "dns") from e
    if not infos or not all(adresse_ip_permise(i[4][0]) for i in infos):
        raise ErreurReseau("adresse_refusee", "ip")


def _controler_pair(conn):
    """Après la connexion : l'adresse réellement jointe (pas pour un tunnel par un proxy : c'est celle du proxy)."""
    if getattr(conn, "_tunnel_host", None):
        return
    try:
        ip = conn.sock.getpeername()[0]
    except (OSError, AttributeError, IndexError):
        return
    if not adresse_ip_permise(ip):
        conn.close()
        raise ErreurReseau("adresse_refusee", "peer")


class _ConnexionHTTPS(http.client.HTTPSConnection):
    def connect(self):
        super().connect()
        _controler_pair(self)


class _ConnexionHTTP(http.client.HTTPConnection):
    def connect(self):
        super().connect()
        _controler_pair(self)


class _HTTPS(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_ConnexionHTTPS, req, context=self._context)


class _HTTP(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_ConnexionHTTP, req)


class _SansRedirection(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # la réponse 3xx remonte en HTTPError : refusée


def _ouvreur():
    return urllib.request.build_opener(_HTTPS(context=contexte_tls()), _HTTP(), _SansRedirection())


def demander(url, formulaire=None, entetes=None, delai=None):
    """(statut, objet JSON) d'un appel GET (ou POST de ``formulaire``, dict encodé). Statut hors 2xx : renvoyé avec le
    JSON de la réponse s'il y en a un (erreur OAuth), sinon ``ErreurReseau("statut")``."""
    u = verifier_url(url)
    _verifier_nom(u)
    delai = float(delai or getattr(settings, "CONNEXION_ENTREPRISE_DELAI", 5))
    corps = urllib.parse.urlencode(formulaire).encode("ascii") if formulaire is not None else None
    req = urllib.request.Request(url, data=corps, method="POST" if corps is not None else "GET")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "Probant")
    if corps is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    for k, v in (entetes or {}).items():
        req.add_header(k, v)
    fin = time.monotonic() + 2 * delai
    try:
        try:
            rep = _ouvreur().open(req, timeout=delai)
            statut = rep.status
        except urllib.error.HTTPError as e:
            if 300 <= e.code < 400:
                e.close()
                raise ErreurReseau("redirection", str(e.code)) from None
            rep, statut = e, e.code
        with rep:
            morceaux, taille = [], 0
            while True:
                if time.monotonic() > fin:
                    raise ErreurReseau("delai")
                bloc = rep.read(65536)
                if not bloc:
                    break
                taille += len(bloc)
                if taille > TAILLE_MAX:
                    raise ErreurReseau("trop_gros")
                morceaux.append(bloc)
    except ErreurReseau:
        raise
    except (TimeoutError, socket.timeout) as e:
        raise ErreurReseau("delai") from e
    except ssl.SSLError as e:
        raise ErreurReseau("tls", type(e).__name__) from e
    except urllib.error.URLError as e:
        if isinstance(e.reason, ErreurReseau):
            raise e.reason from None
        if isinstance(e.reason, (TimeoutError, socket.timeout)):
            raise ErreurReseau("delai") from e
        if isinstance(e.reason, ssl.SSLError):
            raise ErreurReseau("tls", type(e.reason).__name__) from e
        raise ErreurReseau("injoignable", type(e.reason).__name__) from e
    except (OSError, http.client.HTTPException) as e:
        raise ErreurReseau("injoignable", type(e).__name__) from e
    try:
        objet = json.loads(b"".join(morceaux).decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        objet = None
    if not isinstance(objet, dict):
        if 200 <= statut < 300:
            raise ErreurReseau("pas_json")
        raise ErreurReseau("statut", str(statut))
    return statut, objet
