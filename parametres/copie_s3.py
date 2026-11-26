"""Copie externe des sauvegardes vers un stockage objet compatible S3 (MinIO, et les services compatibles S3 courants),
avec la bibliothèque standard de Python seulement (``http.client``, ``hmac``, ``hashlib``) : aucune dépendance.

Signature des requêtes : « Signature Version 4 » (SigV4), protocole public du stockage S3. Rien n'est inventé : HMAC-SHA256
et SHA-256 de la bibliothèque standard, appliqués dans l'ordre que le protocole décrit (requête canonique, texte à signer,
clé dérivée de la date, de la région et du service). Les exemples publiés avec le protocole sont rejoués par les tests
(``parametres/test_copie_s3_signature.py``). La clé secrète ne quitte jamais le serveur : seule la signature part.

- Contenu signé : l'empreinte SHA-256 de chaque envoi est dans la signature (``x-amz-content-sha256``) ; le service
  refuse un contenu qui ne lui correspond pas. C'est la vérification d'intégrité au dépôt ; après le dépôt, la taille et
  l'empreinte de l'archive entière (métadonnée ``x-amz-meta-sha256``) sont relues.
- Grosse archive : envoi en plusieurs morceaux (``MORCEAU``, 16 Mo ; « multipart upload ») ; un seul morceau en mémoire à
  la fois, chacun réessayé ; un envoi abandonné est annulé (rien ne reste à moitié chez le service).
- Style d'adresse : « path » (``https://service/compartiment/clé``, MinIO et la plupart des services compatibles) ou
  « virtual » (``https://compartiment.service/clé``) ; « auto » : virtual pour une adresse en ``.amazonaws.com``, path sinon.
- Réseau : contexte TLS par défaut (``ssl.create_default_context`` : les autorités ajoutées par l'IT, ``SSL_CERT_FILE``,
  valent ici) ; adresses contrôlées (``copie_reseau``) ; http seulement vers une adresse privée (NAS, MinIO interne) ;
  aucune redirection suivie ; réponses lues 1 Mo au plus ; délais et nouveaux essais bornés. Derrière un proxy
  (``HTTPS_PROXY``), un service public est joint par le proxy ; une adresse privée, directement.
- Erreurs : une cause en clair (``ErreurCopie.code``), jamais le texte renvoyé par le service.
"""
import datetime
import hashlib
import hmac
import http.client
import re
import ssl
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from .copie_reseau import ErreurCopie, cause_reseau, ip_permise, ip_privee, resoudre

ALGORITHME = "AWS4-HMAC-SHA256"
SERVICE = "s3"
REGION_DEFAUT = "us-east-1"
VIDE = hashlib.sha256(b"").hexdigest()
MORCEAU = 16 * 1024 * 1024  # au-delà : envoi en plusieurs morceaux (5 Mo au moins chacun, sauf le dernier)
REPONSE_MAX = 1024 * 1024
NON_RESERVES = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~")
COMPARTIMENT = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
CODE_ERREUR = re.compile(r"^[A-Za-z0-9.]{1,40}$")
NOUVEL_ESSAI = (500, 502, 503, 504, 408, 429)
META_SHA = "x-amz-meta-sha256"


# ---------------------------------------------------------------- signature (Signature Version 4)
def encoder(texte, garder_slash=False):
    """Encodage du protocole : lettres, chiffres et « -_.~ » tels quels, tout le reste en %XX (majuscules), octet par
    octet en UTF-8 ; « / » gardé dans le chemin d'un objet."""
    sortie = []
    for octet in str(texte).encode("utf-8"):
        c = chr(octet)
        sortie.append(c if c in NON_RESERVES or (garder_slash and c == "/") else f"%{octet:02X}")
    return "".join(sortie)


def _hmac(cle, texte):
    return hmac.new(cle, texte.encode("utf-8"), hashlib.sha256).digest()


def cle_signature(secret, jour, region, service=SERVICE):
    """Clé de signature dérivée : HMAC-SHA256 en chaîne de « AWS4 » + secret, du jour (AAAAMMJJ), de la région, du
    service et de « aws4_request »."""
    k = _hmac(("AWS4" + secret).encode("utf-8"), jour)
    k = _hmac(k, region)
    k = _hmac(k, service)
    return _hmac(k, "aws4_request")


def requete_canonique(methode, chemin, params, entetes, empreinte):
    """(requête canonique, en-têtes signés). ``chemin`` : déjà encodé ; ``params`` : [(clé, valeur)] ; ``entetes`` :
    {nom: valeur} (noms en minuscules dans la signature, valeurs sans espaces en trop)."""
    requete = "&".join(f"{k}={v}" for k, v in sorted((encoder(k), encoder("" if v is None else v)) for k, v in params))
    propres = {k.lower().strip(): " ".join(str(v).split()) for k, v in entetes.items()}
    signes = sorted(propres)
    lignes = "".join(f"{k}:{propres[k]}\n" for k in signes)
    return "\n".join([methode, chemin or "/", requete, lignes, ";".join(signes), empreinte]), ";".join(signes)


def autorisation(methode, chemin, params, entetes, empreinte, identifiant, secret, region, quand, service=SERVICE):
    """Valeur de l'en-tête ``Authorization`` ; ``entetes`` doit déjà contenir ``host`` et ``x-amz-date`` (et, pour S3,
    ``x-amz-content-sha256``)."""
    canonique, signes = requete_canonique(methode, chemin, params, entetes, empreinte)
    jour = quand.strftime("%Y%m%d")
    portee = f"{jour}/{region}/{service}/aws4_request"
    a_signer = "\n".join([ALGORITHME, quand.strftime("%Y%m%dT%H%M%SZ"), portee,
                          hashlib.sha256(canonique.encode("utf-8")).hexdigest()])
    signature = hmac.new(cle_signature(secret, jour, region, service), a_signer.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{ALGORITHME} Credential={identifiant}/{portee}, SignedHeaders={signes}, Signature={signature}"


# ---------------------------------------------------------------- adresse du service
def verifier_adresse(texte):
    """(schéma, hôte, port, chemin) d'une adresse de service valide, sinon ``ValueError`` : http ou https, un hôte, ni
    identifiant, ni requête, ni fragment."""
    u = urllib.parse.urlsplit((texte or "").strip())
    if u.port is not None and not 0 < u.port < 65536:
        raise ValueError("port")
    hote = (u.hostname or "").lower()
    if u.scheme not in ("http", "https") or not hote or u.username or u.password or u.query or u.fragment \
            or any(c in (texte or "") for c in "\r\n\t "):
        raise ValueError("adresse")
    return u.scheme, hote, u.port or (443 if u.scheme == "https" else 80), u.path.rstrip("/")


def style_virtuel(style, hote, compartiment):
    if style == "virtual":
        return True
    if style == "path":
        return False
    return hote.endswith(".amazonaws.com") and "." not in compartiment


class _ConnexionControlee(http.client.HTTPSConnection):
    """Connexion directe : l'adresse réellement jointe est contrôlée (un nom qui change d'adresse ne passe pas)."""

    def connect(self):
        super().connect()
        _controler_pair(self)


class _ConnexionControleeHTTP(http.client.HTTPConnection):
    def connect(self):
        super().connect()
        _controler_pair(self)
        if not ip_privee(self.sock.getpeername()[0]):
            self.close()
            raise ErreurCopie("http_public", "peer")


def _controler_pair(conn):
    try:
        ip = conn.sock.getpeername()[0]
    except (OSError, AttributeError, IndexError):
        return
    if not ip_permise(ip):
        conn.close()
        raise ErreurCopie("adresse_refusee", "peer")


# ---------------------------------------------------------------- client
class ClientS3:
    """Un compartiment, sous un préfixe (``base`` : « préfixe/identifiant-de-l-installation/ »). Opérations par chemin
    relatif à ``base`` : ``taille``, ``deposer``, ``lire``, ``supprimer``, ``lister``. Contexte : ``with ClientS3(…) as c``."""

    def __init__(self, adresse, region, compartiment, style, identifiant, secret, base="", delai=60, essais=3, pause=1.0):
        self.schema, self.hote_service, self.port, chemin = verifier_adresse(adresse)
        self.region = (region or "").strip() or REGION_DEFAUT
        self.compartiment, self.identifiant, self.secret = compartiment, identifiant, secret
        self.base, self.delai, self.essais, self.pause = base, delai, max(1, essais), pause
        if style_virtuel(style, self.hote_service, compartiment):
            self.hote, self.racine = f"{compartiment}.{self.hote_service}", chemin
        else:
            self.hote, self.racine = self.hote_service, f"{chemin}/{compartiment}"
        defaut = 443 if self.schema == "https" else 80
        self.entete_hote = self.hote if self.port == defaut else f"{self.hote}:{self.port}"
        self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.fermer()

    def fermer(self):
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None

    # -------------------------------------------------- connexion
    def _proxy(self):
        if self.schema != "https":
            return None
        proxies = urllib.request.getproxies()
        if "https" not in proxies or urllib.request.proxy_bypass(self.hote):
            return None
        u = urllib.parse.urlsplit(proxies["https"])
        return (u.hostname, u.port or 80) if u.hostname else None

    def _ouvrir(self):
        proxy = self._proxy()
        try:
            adresses = resoudre(self.hote, self.port)
        except ErreurCopie as e:
            if e.code == "introuvable" and proxy:  # nom que seul le proxy sait résoudre
                adresses = None
            else:
                raise
        privee = adresses is not None and all(ip_privee(a) for a in adresses)
        if self.schema == "http":
            if not privee:
                raise ErreurCopie("http_public", "ip")
            return _ConnexionControleeHTTP(self.hote, self.port, timeout=self.delai)
        contexte = ssl.create_default_context()  # point unique : autorités du système et de l'IT (SSL_CERT_FILE)
        if proxy and not privee:
            conn = http.client.HTTPSConnection(proxy[0], proxy[1], timeout=self.delai, context=contexte)
            conn.set_tunnel(self.hote, self.port)
            return conn
        return _ConnexionControlee(self.hote, self.port, timeout=self.delai, context=contexte)

    def _chemin(self, rel=None):
        """Chemin encodé : racine du compartiment, ou objet ``base`` + ``rel``."""
        if rel is None:
            return encoder(self.racine, garder_slash=True) if self.racine else "/"
        return encoder(f"{self.racine}/{self.base}{rel}", garder_slash=True)

    def _une_fois(self, methode, chemin, params, corps, entetes_sup, lire_max):
        quand = datetime.datetime.now(datetime.timezone.utc)
        empreinte = hashlib.sha256(corps).hexdigest() if corps else VIDE
        entetes = {"host": self.entete_hote, "x-amz-date": quand.strftime("%Y%m%dT%H%M%SZ"),
                   "x-amz-content-sha256": empreinte, **entetes_sup}
        auth = autorisation(methode, chemin, params, entetes, empreinte, self.identifiant, self.secret, self.region, quand)
        envoyes = {("Host" if k == "host" else k): v for k, v in entetes.items()}
        envoyes["Authorization"] = auth
        envoyes["User-Agent"] = "Probant"
        if corps or methode in ("PUT", "POST"):
            envoyes["Content-Length"] = str(len(corps or b""))
        url = chemin + ("?" + "&".join(f"{encoder(k)}={encoder('' if v is None else v)}" for k, v in params) if params else "")
        if self._conn is None:
            self._conn = self._ouvrir()
        try:
            self._conn.request(methode, url, body=corps or None, headers=envoyes)
            rep = self._conn.getresponse()
            morceaux, taille = [], 0
            while True:
                bloc = rep.read(65536)
                if not bloc:
                    break
                taille += len(bloc)
                if taille > lire_max:
                    self.fermer()
                    raise ErreurCopie("service", "response too large")
                morceaux.append(bloc)
            if rep.getheader("Connection", "").lower() == "close":
                self.fermer()
            return rep.status, {k.lower(): v for k, v in rep.getheaders()}, b"".join(morceaux)
        except BaseException:
            self.fermer()
            raise

    def _envoyer(self, methode, rel=None, params=(), corps=b"", entetes=None, operation="ecrire", attendus=(200,),
                 absents=(), lire_max=REPONSE_MAX):
        """(statut, en-têtes, corps) ; nouveaux essais bornés sur une erreur réseau ou un service momentanément
        indisponible ; sinon ``ErreurCopie`` avec la cause. Statut de ``absents`` (404) : renvoyé tel quel."""
        chemin, params = self._chemin(rel), list(params)
        derniere = None
        for essai in range(self.essais):
            if essai:
                time.sleep(min(self.pause * 2 ** (essai - 1), 30))
            try:
                statut, ent, corps_rep = self._une_fois(methode, chemin, params, corps, dict(entetes or {}), lire_max)
            except ErreurCopie as e:
                if e.code not in ("service",):
                    raise
                derniere = e
                continue
            except (OSError, http.client.HTTPException) as e:
                code = cause_reseau(e) or "injoignable"
                derniere = ErreurCopie(code, type(e).__name__)
                if code in ("certificat", "tls", "introuvable", "adresse_refusee"):
                    raise derniere from e
                continue
            if statut in attendus or statut in absents:
                return statut, ent, corps_rep
            erreur = _erreur(statut, corps_rep, operation)
            if statut in NOUVEL_ESSAI:
                derniere = erreur
                continue
            raise erreur
        raise derniere

    # -------------------------------------------------- opérations
    def taille(self, rel):
        """(taille, sha256 noté ou None) de l'objet, ou None s'il n'existe pas."""
        statut, ent, _ = self._envoyer("HEAD", rel, operation="taille", absents=(404,))
        if statut == 404:
            return None
        return int(ent.get("content-length", "0") or 0), ent.get(META_SHA) or None

    def deposer(self, rel, chemin_local, taille, sha256):
        """Dépose le fichier local sous ``rel`` (en un envoi, ou en morceaux au-delà de ``MORCEAU``), puis relit sa
        taille et son empreinte."""
        meta = {META_SHA: sha256}
        if taille <= MORCEAU:
            with open(chemin_local, "rb") as f:
                corps = f.read()
            self._envoyer("PUT", rel, corps=corps, entetes={**meta, "content-type": "application/zip"})
        else:
            self._en_morceaux(rel, chemin_local, taille, meta)
        relu = self.taille(rel)
        if relu is None or relu[0] != taille or (relu[1] and relu[1] != sha256):
            raise ErreurCopie("integrite", "size or checksum differs after upload")

    def _en_morceaux(self, rel, chemin_local, taille, meta):
        _, _, corps = self._envoyer("POST", rel, params=[("uploads", "")], entetes={**meta, "content-type": "application/zip"})
        identifiant = _texte_xml(corps, "UploadId")
        if not identifiant:
            raise ErreurCopie("service", "no UploadId")
        parts = []
        try:
            with open(chemin_local, "rb") as f:
                numero = 1
                while True:
                    morceau = f.read(MORCEAU)
                    if not morceau:
                        break
                    _, ent, _ = self._envoyer("PUT", rel, params=[("partNumber", str(numero)), ("uploadId", identifiant)],
                                              corps=morceau)
                    parts.append((numero, ent.get("etag", "")))
                    numero += 1
                    del morceau
            liste = "".join(f"<Part><PartNumber>{n}</PartNumber><ETag>{_echapper(e)}</ETag></Part>" for n, e in parts)
            fin = f'<CompleteMultipartUpload xmlns="http://s3.amazonaws.com/doc/2006-03-01/">{liste}</CompleteMultipartUpload>'
            _, _, corps = self._envoyer("POST", rel, params=[("uploadId", identifiant)], corps=fin.encode("utf-8"),
                                        entetes={"content-type": "application/xml"})
            if b"<Error>" in corps:  # le service peut répondre 200 puis une erreur dans le corps
                raise _erreur(200, corps, "ecrire")
        except BaseException:
            try:
                self._envoyer("DELETE", rel, params=[("uploadId", identifiant)], attendus=(200, 204), absents=(404,))
            except Exception:  # noqa: BLE001 - l'envoi a déjà échoué ; le service purge les envois abandonnés
                pass
            raise

    def lire(self, rel, maxi=REPONSE_MAX):
        _, _, corps = self._envoyer("GET", rel, operation="lire", lire_max=maxi)
        return corps

    def supprimer(self, rel):
        self._envoyer("DELETE", rel, operation="supprimer", attendus=(200, 204), absents=(404,))

    def lister(self, pages_max=100):
        """[(chemin relatif à ``base``, taille)] de tous les objets sous ``base``."""
        sortie, jeton = [], None
        for _ in range(pages_max):
            params = [("list-type", "2"), ("prefix", self.base)] + ([("continuation-token", jeton)] if jeton else [])
            _, _, corps = self._envoyer("GET", None, params=params, operation="lister")
            racine = _xml(corps)
            for c in racine.iter():
                if _local(c.tag) == "Contents":
                    cle = _enfant(c, "Key")
                    taille = _enfant(c, "Size")
                    if cle and cle.startswith(self.base):
                        sortie.append((cle[len(self.base):], int(taille or 0)))
            if (_enfant(racine, "IsTruncated") or "").lower() != "true":
                return sortie
            jeton = _enfant(racine, "NextContinuationToken")
            if not jeton:
                return sortie
        return sortie


# ---------------------------------------------------------------- réponses XML (1 Mo au plus, sans DTD)
def _xml(corps):
    if b"<!DOCTYPE" in corps or b"<!ENTITY" in corps:
        raise ErreurCopie("service", "XML with DTD refused")
    try:
        return ET.fromstring(corps)
    except ET.ParseError as e:
        raise ErreurCopie("service", "XML unreadable") from e


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _enfant(noeud, nom):
    for c in noeud:
        if _local(c.tag) == nom:
            return (c.text or "").strip()
    return None


def _texte_xml(corps, nom):
    try:
        racine = _xml(corps)
    except ErreurCopie:
        return None
    for c in racine.iter():
        if _local(c.tag) == nom:
            return (c.text or "").strip()
    return None


def _echapper(texte):
    return texte.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def code_service(corps):
    """Code d'erreur du service (« AccessDenied »), s'il a la forme d'un code ; jamais le message."""
    code = _texte_xml(corps, "Code") if corps else None
    return code if code and CODE_ERREUR.match(code) else ""


def _erreur(statut, corps, operation):
    """``ErreurCopie`` d'une réponse en erreur : statut HTTP et code du service, sans recopier le message."""
    code = code_service(corps)
    resume = f"HTTP {statut} {code}".strip()
    if code in ("InvalidAccessKeyId", "SignatureDoesNotMatch", "InvalidToken", "InvalidSecurity"):
        return ErreurCopie("identifiants", resume)
    if code == "NoSuchBucket":
        return ErreurCopie("compartiment", resume)
    if code in ("PermanentRedirect", "AuthorizationHeaderMalformed", "IllegalLocationConstraintException") or statut in (301, 307):
        return ErreurCopie("region", resume)
    if code == "RequestTimeTooSkewed":
        return ErreurCopie("horloge", resume)
    if code in ("XAmzContentSHA256Mismatch", "BadDigest", "InvalidDigest"):
        return ErreurCopie("integrite", resume)
    if "Quota" in code or "StorageFull" in code or statut == 507:
        return ErreurCopie("place", resume)
    if operation == "taille" and statut in (401, 403):  # réponse sans corps : identifiants ou droits, on ne sait pas
        return ErreurCopie("acces", resume)
    if code == "AccessDenied" or statut == 403:
        return ErreurCopie(f"droits_{operation}", resume)
    if statut == 404 and operation == "lire":
        return ErreurCopie("relecture", resume)
    if statut == 401:
        return ErreurCopie("identifiants", resume)
    return ErreurCopie("service", resume)
