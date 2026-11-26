"""OpenID Connect, flux « authorization code » avec PKCE (RFC 7636), pour un fournisseur quelconque (aucun code propre à
l'un d'eux) : découverte (``/.well-known/openid-configuration``), clés publiques (JWKS, rotation suivie), échange du
code, vérification du jeton d'identité par PyJWT.

Vérifié sur chaque jeton d'identité : signature (algorithmes asymétriques seulement : jamais « none », jamais HS256 ni
aucune clé partagée), clé connue du fournisseur (``kid`` ; clé inconnue : les clés sont relues une fois, au plus toutes
les ``RELECTURE_CLES`` secondes), ``iss`` égal à l'émetteur découvert, ``aud`` qui contient l'identifiant du client
(``azp`` égal à lui quand il y a plusieurs destinataires), ``exp`` et ``iat`` (60 s de marge pour les horloges),
``nonce`` égal à celui de la demande. Les appels passent tous par ``sortant.demander``."""
import base64
import hashlib
import logging
import secrets
import threading
import time
import urllib.parse

from . import sortant

journal = logging.getLogger("connexion_entreprise")

ALGORITHMES = ("RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512")
MARGE = 60  # secondes de marge sur exp, iat, nbf
DUREE_CACHE = 600  # découverte et clés gardées 10 minutes en mémoire
RELECTURE_CLES = 60  # clé inconnue : les clés ne sont relues qu'une fois par minute au plus
PORTEE = "openid email"

_verrou = threading.Lock()
_decouvertes = {}  # émetteur → (date, document)
_cles = {}  # adresse des clés → (date, [clés])
_relues = {}  # adresse des clés → date de la dernière relecture forcée


class ErreurOIDC(Exception):
    """Échec de la connexion d'entreprise. ``code`` : cause technique (journal du serveur, écran d'essai)."""

    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code, self.detail = code, detail


def oublier_caches():
    with _verrou:
        _decouvertes.clear()
        _cles.clear()
        _relues.clear()


def normaliser_emetteur(texte):
    return (texte or "").strip().rstrip("/")


def adresse_decouverte(emetteur):
    return normaliser_emetteur(emetteur) + "/.well-known/openid-configuration"


def _appel(url, **kw):
    try:
        return sortant.demander(url, **kw)
    except sortant.ErreurReseau as e:
        raise ErreurOIDC(f"reseau_{e.code}", e.detail) from e


def _https(doc, cle):
    url = doc.get(cle)
    if not isinstance(url, str) or not url:
        raise ErreurOIDC("decouverte_incomplete", cle)
    try:
        sortant.verifier_url(url)
    except sortant.ErreurReseau as e:
        raise ErreurOIDC("decouverte_adresse", cle) from e
    return url


def algorithmes_permis(doc):
    annonces = doc.get("id_token_signing_alg_values_supported") or ["RS256"]  # RS256 : valeur par défaut d'OpenID Connect
    if not isinstance(annonces, list):
        annonces = ["RS256"]
    return [a for a in ALGORITHMES if a in annonces]


def valider_decouverte(emetteur, doc):
    """Document de découverte utilisable, ou ErreurOIDC : même émetteur, adresses en https, flux « code », PKCE S256,
    signature asymétrique."""
    if not isinstance(doc.get("issuer"), str) or normaliser_emetteur(doc["issuer"]) != normaliser_emetteur(emetteur):
        raise ErreurOIDC("emetteur_different")
    for cle in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        _https(doc, cle)
    types = doc.get("response_types_supported")
    if isinstance(types, list) and "code" not in types:
        raise ErreurOIDC("sans_flux_code")
    pkce = doc.get("code_challenge_methods_supported")
    if isinstance(pkce, list) and "S256" not in pkce:
        raise ErreurOIDC("sans_pkce")
    if not algorithmes_permis(doc):
        raise ErreurOIDC("algorithmes")
    methodes = doc.get("token_endpoint_auth_methods_supported")
    if isinstance(methodes, list) and not {"client_secret_basic", "client_secret_post"} & set(methodes):
        raise ErreurOIDC("authentification_client")
    return doc


def decouvrir(emetteur, frais=False):
    """Document de découverte de l'émetteur (gardé ``DUREE_CACHE`` secondes)."""
    emetteur = normaliser_emetteur(emetteur)
    if not emetteur:
        raise ErreurOIDC("sans_emetteur")
    with _verrou:
        garde = _decouvertes.get(emetteur)
    if garde and not frais and time.monotonic() - garde[0] < DUREE_CACHE:
        return garde[1]
    statut, doc = _appel(adresse_decouverte(emetteur))
    if statut != 200:
        raise ErreurOIDC("decouverte_statut", str(statut))
    valider_decouverte(emetteur, doc)
    with _verrou:
        _decouvertes[emetteur] = (time.monotonic(), doc)
    return doc


def lire_cles(doc, frais=False):
    """Clés publiques de signature du fournisseur (liste de JWK)."""
    url = _https(doc, "jwks_uri")
    with _verrou:
        garde = _cles.get(url)
    if garde and not frais and time.monotonic() - garde[0] < DUREE_CACHE:
        return garde[1]
    statut, jwks = _appel(url)
    cles = jwks.get("keys") if statut == 200 else None
    if not isinstance(cles, list):
        raise ErreurOIDC("cles_illisibles", str(statut))
    cles = [k for k in cles if isinstance(k, dict) and k.get("use", "sig") == "sig" and k.get("kty") in ("RSA", "EC")]
    with _verrou:
        _cles[url] = (time.monotonic(), cles)
    return cles


def _choisir(cles, kid, alg):
    candidates = [k for k in cles if (kid is None or k.get("kid") == kid) and k.get("alg", alg) == alg]
    if kid is None and len(candidates) != 1:
        return None  # sans « kid », une seule clé possible, sinon refus
    return candidates[0] if candidates else None


def cle_du_jeton(doc, kid, alg):
    """Clé publique (objet ``cryptography``) qui doit avoir signé le jeton ; clé inconnue : relecture des clés (rotation
    chez le fournisseur), au plus une fois par ``RELECTURE_CLES`` secondes."""
    import jwt

    jwk = _choisir(lire_cles(doc), kid, alg)
    if jwk is None:
        url = doc["jwks_uri"]
        with _verrou:
            permise = time.monotonic() - _relues.get(url, -RELECTURE_CLES) >= RELECTURE_CLES
            if permise:
                _relues[url] = time.monotonic()
        if permise:
            jwk = _choisir(lire_cles(doc, frais=True), kid, alg)
    if jwk is None:
        raise ErreurOIDC("cle_inconnue")
    try:
        return jwt.PyJWK(jwk, algorithm=alg).key
    except (jwt.PyJWKError, jwt.InvalidKeyError, ValueError, TypeError) as e:
        raise ErreurOIDC("cle_inutilisable", type(e).__name__) from e


def verifier_jeton(id_token, doc, client_id, nonce):
    """Revendications (« claims ») du jeton d'identité, une fois tout vérifié ; ErreurOIDC sinon."""
    import jwt

    if not isinstance(id_token, str) or len(id_token) > 20000:
        raise ErreurOIDC("jeton_illisible")
    try:
        entete = jwt.get_unverified_header(id_token)
    except jwt.PyJWTError as e:
        raise ErreurOIDC("jeton_illisible", type(e).__name__) from e
    alg = entete.get("alg")
    if alg not in algorithmes_permis(doc):
        raise ErreurOIDC("algorithme_refuse", str(alg)[:20])
    kid = entete.get("kid")
    if kid is not None and not isinstance(kid, str):
        raise ErreurOIDC("jeton_illisible", "kid")
    cle = cle_du_jeton(doc, kid, alg)
    try:
        claims = jwt.decode(id_token, cle, algorithms=[alg], audience=client_id, issuer=doc["issuer"], leeway=MARGE,
                            options={"require": ["exp", "iat", "iss", "aud", "sub"]})
    except jwt.ExpiredSignatureError as e:
        raise ErreurOIDC("jeton_expire") from e
    except jwt.InvalidAudienceError as e:
        raise ErreurOIDC("destinataire_refuse") from e
    except jwt.InvalidIssuerError as e:
        raise ErreurOIDC("emetteur_refuse") from e
    except jwt.InvalidSignatureError as e:
        raise ErreurOIDC("signature_refusee") from e
    except jwt.PyJWTError as e:
        raise ErreurOIDC("jeton_refuse", type(e).__name__) from e
    aud = claims.get("aud")
    if isinstance(aud, list) and len(aud) > 1 and claims.get("azp") != client_id:
        raise ErreurOIDC("destinataire_refuse", "azp")
    if "azp" in claims and claims["azp"] != client_id:
        raise ErreurOIDC("destinataire_refuse", "azp")
    if not isinstance(claims.get("nonce"), str) or not secrets.compare_digest(claims["nonce"], nonce):
        raise ErreurOIDC("nonce_refuse")
    if not isinstance(claims.get("sub"), str) or not claims["sub"] or len(claims["sub"]) > 255:
        raise ErreurOIDC("jeton_refuse", "sub")
    return claims


def pkce():
    """(vérificateur, défi S256)."""
    verificateur = secrets.token_urlsafe(64)
    defi = base64.urlsafe_b64encode(hashlib.sha256(verificateur.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    return verificateur, defi


def lien_autorisation(doc, client_id, adresse_retour, etat, nonce, defi):
    base = doc["authorization_endpoint"]
    parametres = urllib.parse.urlencode({
        "response_type": "code", "client_id": client_id, "redirect_uri": adresse_retour, "scope": PORTEE,
        "state": etat, "nonce": nonce, "code_challenge": defi, "code_challenge_method": "S256"})
    return base + ("&" if urllib.parse.urlsplit(base).query else "?") + parametres


def echanger_code(doc, client_id, secret, code, adresse_retour, verificateur):
    """Jeton d'identité contre le code reçu (le secret du client part dans l'en-tête Authorization si le fournisseur le
    permet ou ne dit rien, sinon dans le formulaire)."""
    url = _https(doc, "token_endpoint")
    methodes = doc.get("token_endpoint_auth_methods_supported")
    if not isinstance(methodes, list):
        methodes = ["client_secret_basic"]  # valeur par défaut d'OpenID Connect
    formulaire = {"grant_type": "authorization_code", "code": code, "redirect_uri": adresse_retour,
                  "code_verifier": verificateur}
    entetes = {}
    if "client_secret_basic" in methodes:
        paire = f"{urllib.parse.quote(client_id, safe='')}:{urllib.parse.quote(secret, safe='')}"
        entetes["Authorization"] = "Basic " + base64.b64encode(paire.encode("utf-8")).decode("ascii")
    elif "client_secret_post" in methodes:
        formulaire.update(client_id=client_id, client_secret=secret)
    else:
        raise ErreurOIDC("authentification_client")
    statut, reponse = _appel(url, formulaire=formulaire, entetes=entetes)
    if statut != 200:
        erreur = reponse.get("error") if isinstance(reponse.get("error"), str) else ""
        raise ErreurOIDC("echange_refuse", f"{statut} {erreur[:40]}".strip())
    jeton = reponse.get("id_token")
    if not isinstance(jeton, str) or not jeton:
        raise ErreurOIDC("sans_jeton")
    return jeton


def essayer(emetteur):
    """Bouton « Essayer » : [(code, réussi)] des contrôles faits, puis la cause du premier échec (ou "")."""
    faits = []
    try:
        doc = decouvrir(emetteur, frais=True)
        faits.append(("decouverte", True))
        if not lire_cles(doc, frais=True):
            raise ErreurOIDC("sans_cle")
        faits.append(("cles", True))
    except ErreurOIDC as e:
        return faits, e.code
    return faits, ""
