"""Faux fournisseur OpenID Connect pour les tests : un vrai serveur HTTP (fil à part, 127.0.0.1, port libre), de vraies
signatures (RSA 2048, PyJWT), PKCE et authentification du client vérifiés comme chez un vrai fournisseur.

``mode`` change le jeton d'identité rendu, pour les cas d'attaque : ``nonce_faux``, ``aud_faux``, ``iss_faux``,
``expire``, ``futur``, ``cle_inconnue`` (signé par une clé absente des clés publiées), ``signature_fausse`` (autre clé
avec le ``kid`` de la vraie), ``alg_none`` (jeton non signé), ``hs256`` (signé avec le secret du client comme clé
partagée), ``sans_jeton``. ``tourner()`` : nouvelle clé de signature publiée (rotation)."""
import base64
import hashlib
import json
import secrets
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

CLIENT_ID = "probant-essai"
SECRET = "secret-du-client-essai-2026-pour-les-tests"


def _cle(kid):
    privee = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    publique = json.loads(RSAAlgorithm.to_jwk(privee.public_key()))
    publique.update(kid=kid, use="sig", alg="RS256")
    return privee, publique


class FauxFournisseur:
    def __init__(self, chemin="/realms/essai"):
        self.chemin = chemin
        self.mode = ""
        self.claims = {}  # revendications ajoutées ou remplacées dans le jeton (email, email_verified, sub…)
        self.decouverte = {}  # champs ajoutés ou remplacés dans le document de découverte
        self.cles = [_cle("cle-1")]
        self.codes = {}  # code → demande (nonce, défi, adresse de retour, client)
        self.appels = []  # (méthode, chemin) reçus
        self.echanges = []  # en-têtes et formulaires reçus au point « token »
        faux = self

        class Gestion(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _json(self, statut, objet):
                corps = json.dumps(objet).encode()
                self.send_response(statut)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(corps)))
                self.end_headers()
                self.wfile.write(corps)

            def do_GET(self):
                faux.appels.append(("GET", self.path))
                u = urllib.parse.urlsplit(self.path)
                if u.path == faux.chemin + "/.well-known/openid-configuration":
                    return self._json(200, faux.document())
                if u.path == faux.chemin + "/jwks":
                    return self._json(200, {"keys": [p for _, p in faux.cles]})
                if u.path == faux.chemin + "/authorize":
                    q = dict(urllib.parse.parse_qsl(u.query))
                    cible = q["redirect_uri"] + "?" + urllib.parse.urlencode(
                        {"error": "access_denied", "state": q.get("state", "")} if faux.mode == "refus" else
                        {"code": faux.emettre_code(q), "state": q.get("state", "")})
                    self.send_response(302)
                    self.send_header("Location", cible)
                    self.end_headers()
                    return None
                return self._json(404, {"error": "not_found"})

            def do_POST(self):
                faux.appels.append(("POST", self.path))
                taille = int(self.headers.get("Content-Length") or 0)
                formulaire = dict(urllib.parse.parse_qsl(self.rfile.read(taille).decode()))
                faux.echanges.append({"authorization": self.headers.get("Authorization", ""), **formulaire})
                if urllib.parse.urlsplit(self.path).path != faux.chemin + "/token":
                    return self._json(404, {"error": "not_found"})
                statut, reponse = faux.jeton(formulaire, self.headers.get("Authorization", ""))
                return self._json(statut, reponse)

        self.serveur = ThreadingHTTPServer(("127.0.0.1", 0), Gestion)
        self.fil = threading.Thread(target=self.serveur.serve_forever, daemon=True)
        self.fil.start()

    @property
    def emetteur(self):
        return f"http://127.0.0.1:{self.serveur.server_address[1]}{self.chemin}"

    def arreter(self):
        self.serveur.shutdown()
        self.serveur.server_close()

    def document(self):
        e = self.emetteur
        doc = {"issuer": e, "authorization_endpoint": e + "/authorize", "token_endpoint": e + "/token",
               "jwks_uri": e + "/jwks", "response_types_supported": ["code"], "subject_types_supported": ["public"],
               "id_token_signing_alg_values_supported": ["RS256"], "code_challenge_methods_supported": ["S256"],
               "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"]}
        doc.update(self.decouverte)
        return doc

    def tourner(self):
        """Rotation : une nouvelle clé publiée en tête, qui signe désormais les jetons."""
        self.cles.insert(0, _cle(f"cle-{len(self.cles) + 1}"))

    def emettre_code(self, q):
        code = secrets.token_urlsafe(24)
        self.codes[code] = {"nonce": q.get("nonce"), "defi": q.get("code_challenge"), "methode": q.get("code_challenge_method"),
                            "retour": q.get("redirect_uri"), "client_id": q.get("client_id"), "scope": q.get("scope")}
        return code

    def jeton(self, f, autorisation):
        demande = self.codes.pop(f.get("code", ""), None)  # un code ne sert qu'une fois
        if demande is None or f.get("grant_type") != "authorization_code" or f.get("redirect_uri") != demande["retour"]:
            return 400, {"error": "invalid_grant"}
        verif = base64.urlsafe_b64encode(hashlib.sha256((f.get("code_verifier") or "").encode()).digest()).rstrip(b"=").decode()
        if demande["methode"] != "S256" or verif != demande["defi"]:
            return 400, {"error": "invalid_grant", "error_description": "PKCE"}
        attendu = "Basic " + base64.b64encode(f"{CLIENT_ID}:{SECRET}".encode()).decode()
        if autorisation != attendu and not (f.get("client_id") == CLIENT_ID and f.get("client_secret") == SECRET):
            return 401, {"error": "invalid_client"}
        if self.mode == "sans_jeton":
            return 200, {"access_token": "a", "token_type": "Bearer"}
        return 200, {"access_token": "a", "token_type": "Bearer", "id_token": self.fabriquer(demande["nonce"])}

    def fabriquer(self, nonce):
        maintenant = int(time.time())
        claims = {"iss": self.emetteur, "aud": CLIENT_ID, "sub": "sujet-001", "iat": maintenant, "exp": maintenant + 300,
                  "nonce": nonce, "email": "contrib@exemple.example", "email_verified": True}
        claims.update(self.claims)
        claims = {k: v for k, v in claims.items() if v is not None}
        privee, publique = self.cles[0]
        kid = publique["kid"]
        if self.mode == "nonce_faux":
            claims["nonce"] = "autre-nonce"
        elif self.mode == "aud_faux":
            claims["aud"] = "autre-client"
        elif self.mode == "iss_faux":
            claims["iss"] = "https://autre.example/realms/essai"
        elif self.mode == "expire":
            claims["iat"], claims["exp"] = maintenant - 3600, maintenant - 600
        elif self.mode == "futur":
            claims["iat"] = maintenant + 3600
        elif self.mode == "cle_inconnue":
            privee, kid = _cle("inconnue")[0], "inconnue"
        elif self.mode == "signature_fausse":
            privee = _cle("x")[0]
        elif self.mode == "alg_none":
            return jwt.encode(claims, None, algorithm="none", headers={"kid": kid})
        elif self.mode == "hs256":
            return jwt.encode(claims, SECRET, algorithm="HS256", headers={"kid": kid})
        return jwt.encode(claims, privee, algorithm="RS256", headers={"kid": kid})
