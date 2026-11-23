"""Fournisseurs de la prise IA (docs/ai_socket.md) : une interface, plusieurs fournisseurs possibles.

- ``Fournisseur`` : ``code``, ``nom``, ``hote`` (ce que l'IT ouvre), ``modeles``, ``modele_par_defaut`` et une seule
  méthode, ``demander(requete) -> ReponseIA`` ; toute erreur est une ``ErreurIA`` à code fermé (affiché en clair).
- ``FournisseurClaude`` : API Messages d'Anthropic, un appel HTTPS par la bibliothèque standard (aucune dépendance).
- ``FournisseurFactice`` : réponses fabriquées sur place, sans réseau ; seulement dans les tests et, sur un poste de
  développement, avec AI_FAKE_PROVIDER=1 (``settings.IA_FOURNISSEUR_FACTICE``).

Aucun appel réel pendant les tests : ``_ouvrir`` refuse tout réseau quand ``settings.IA_RESEAU_INTERDIT``.
"""
import http.client
import json
import logging
import re
import socket
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from django.conf import settings

journal = logging.getLogger("reporting.ia")

CODES_ERREUR = ("cle_refusee", "credit", "quota", "surcharge", "reseau", "delai", "refus", "trop_long", "modele", "requete",
                "reponse_invalide")


class ErreurIA(Exception):
    """Échec d'un appel : ``code`` parmi CODES_ERREUR (libellé ``admin.ia.erreur.<code>``) ; jamais le contenu envoyé."""

    def __init__(self, code, detail=""):
        super().__init__(code)
        self.code = code if code in CODES_ERREUR else "requete"
        self.detail = detail


@dataclass
class Requete:
    cle: str
    modele: str
    systeme: str  # consignes fixes
    donnees: str  # bloc de données (<data>…</data>)
    schema: dict  # schéma JSON de la réponse attendue
    max_jetons: int = 2000
    effort: str = "medium"
    delai: int = 60
    usage: str = ""


@dataclass
class ReponseIA:
    donnees: dict
    modele: str = ""
    jetons_entree: int = 0
    jetons_sortie: int = 0


class Fournisseur:
    code = ""
    nom = ""
    hote = ""
    modeles = []  # [(identifiant, nom, note)]
    modele_par_defaut = ""

    def demander(self, requete):  # pragma: no cover - interface
        raise NotImplementedError

    def connait(self, modele):
        return any(m == modele for m, _, _ in self.modeles)


# ---------------------------------------------------------------- Claude (Anthropic)
def _maintenant():
    return time.monotonic()


def _borner(rep, restant):
    """Attente d'une lecture bornée au temps qui reste (socket de la réponse, quand il est accessible)."""
    sock = getattr(getattr(getattr(rep, "fp", None), "raw", None), "_sock", None)
    if sock is not None:
        try:
            sock.settimeout(max(restant, 0.01))
        except OSError:
            pass


def _ouvrir(req, delai):
    """Seul point de l'outil qui ouvre une connexion vers un fournisseur."""
    if settings.IA_RESEAU_INTERDIT:
        raise RuntimeError("Network access to an AI provider is forbidden while the tests run.")
    return urllib.request.urlopen(req, timeout=delai, context=ssl.create_default_context())  # noqa: S310 - adresse fixe en https


class FournisseurClaude(Fournisseur):
    code = "claude"
    nom = "Claude"
    hote = "api.anthropic.com"
    url = "https://api.anthropic.com/v1/messages"
    version_api = "2026-10-21"
    beta_repli = "server-side-fallback-2026-07-01"
    # le plus capable d'abord (modèle par défaut), puis du plus cher au moins cher ; prix par million de jetons, en USD,
    # entrée / sortie, relevés (docs/ai_socket.md)
    modeles = [
        ("claude-fable-5-2", "Claude Fable 5.2", "admin.ia.modele.fable"),
        ("claude-opus-5-5", "Claude Opus 5.5", "admin.ia.modele.opus"),
        ("claude-sonnet-5-5", "Claude Sonnet 5.5", "admin.ia.modele.sonnet"),
        ("claude-haiku-5-5", "Claude Haiku 5.5", "admin.ia.modele.haiku"),
    ]
    modele_par_defaut = "claude-fable-5-2"
    sans_repli = {"claude-haiku-5-5"}  # pas de repli côté serveur après un refus

    def corps(self, r, repli=True):
        corps = {
            "model": r.modele, "max_tokens": r.max_jetons, "system": r.systeme,
            "messages": [{"role": "user", "content": r.donnees}],
            "output_config": {"effort": r.effort, "format": {"type": "json_schema", "schema": r.schema}},
        }
        if repli and r.modele not in self.sans_repli:
            corps["fallbacks"] = "default"
        return corps

    def entetes(self, r, repli=True):
        e = {"x-api-key": r.cle, "anthropic-version": self.version_api, "content-type": "application/json",
             "user-agent": "probant"}
        if repli and r.modele not in self.sans_repli:
            e["anthropic-beta"] = self.beta_repli
        return e

    def demander(self, r):
        """Un appel, limité à ``r.delai`` secondes en tout : la nouvelle tentative sans l'en-tête bêta n'a que le temps
        qui reste, et la réponse est lue par morceaux jusqu'à cette limite (le délai de ``urlopen`` vaut pour chaque
        attente du réseau, pas pour tout l'appel)."""
        fin = _maintenant() + r.delai
        try:
            return self._demander(r, True, r.delai, fin)
        except _BetaRefusee:
            restant = fin - _maintenant()
            if restant <= 0:
                raise ErreurIA("delai") from None
            return self._demander(r, False, restant, fin)  # compte sans le repli côté serveur : une seule nouvelle tentative

    def _demander(self, r, repli, delai, fin):
        req = urllib.request.Request(self.url, data=json.dumps(self.corps(r, repli)).encode("utf-8"),
                                     headers=self.entetes(r, repli), method="POST")
        try:
            with _ouvrir(req, delai) as rep:
                morceaux = []
                while True:
                    restant = fin - _maintenant()
                    if restant <= 0:
                        raise ErreurIA("delai")
                    _borner(rep, restant)
                    morceau = rep.read(65536)
                    if not morceau:
                        break
                    morceaux.append(morceau)
                brut = b"".join(morceaux)
        except urllib.error.HTTPError as e:
            raise self._erreur_http(e, repli) from None
        except http.client.HTTPException as e:  # réponse coupée (IncompleteRead), ligne d'état illisible (BadStatusLine)…
            journal.warning("AI call failed: provider=claude unreadable HTTP answer (%s)", type(e).__name__)
            raise ErreurIA("reponse_invalide") from None
        except (TimeoutError, socket.timeout):
            raise ErreurIA("delai") from None
        except urllib.error.URLError as e:
            if isinstance(e.reason, (TimeoutError, socket.timeout)):
                raise ErreurIA("delai") from None
            journal.warning("AI call failed: provider=claude network error (%s)", type(e.reason).__name__)
            raise ErreurIA("reseau") from None
        except OSError as e:
            journal.warning("AI call failed: provider=claude network error (%s)", type(e).__name__)
            raise ErreurIA("reseau") from None
        return self.lire(brut)

    def _erreur_http(self, e, repli):
        try:
            message = (json.loads(e.read() or b"{}").get("error") or {}).get("message", "")
        except (ValueError, OSError, AttributeError):
            message = ""
        message = str(message)[:300]
        journal.warning("AI call failed: provider=claude status=%s request-id=%s", e.code, e.headers.get("request-id", "") if e.headers else "")
        if e.code == 400 and repli and "anthropic-beta" in message:
            return _BetaRefusee()
        if e.code in (401, 403):
            return ErreurIA("cle_refusee")
        if e.code == 402 or (e.code == 400 and re.search(r"credit|billing", message, re.I)):
            return ErreurIA("credit")
        if e.code == 404:
            return ErreurIA("modele")
        if e.code == 413:
            return ErreurIA("trop_long")
        if e.code == 429:
            return ErreurIA("quota")
        if e.code >= 500:
            return ErreurIA("surcharge")
        return ErreurIA("requete", message)

    @staticmethod
    def lire(brut):
        """Réponse de l'API → ReponseIA ; un refus, une réponse coupée ou un JSON inattendu sont des erreurs."""
        try:
            d = json.loads(brut)
        except ValueError:
            raise ErreurIA("reponse_invalide") from None
        if not isinstance(d, dict):
            raise ErreurIA("reponse_invalide")
        arret = d.get("stop_reason")
        if arret == "refusal":
            raise ErreurIA("refus")
        if arret == "max_tokens":
            raise ErreurIA("trop_long")
        contenu = d.get("content") or []
        if not isinstance(contenu, list):
            raise ErreurIA("reponse_invalide")
        textes = [b.get("text", "") for b in contenu if isinstance(b, dict) and b.get("type") == "text"]
        try:
            donnees = json.loads(textes[0]) if textes else None
        except (ValueError, TypeError):  # texte absent, illisible ou qui n'est pas une chaîne
            donnees = None
        if not isinstance(donnees, dict):
            raise ErreurIA("reponse_invalide")
        u = d.get("usage") or {}
        try:  # décompte des jetons : des entiers, sinon la réponse n'est pas celle de l'API
            entree, sortie = (int(u.get(c) or 0) for c in ("input_tokens", "output_tokens"))
        except (AttributeError, TypeError, ValueError):
            raise ErreurIA("reponse_invalide") from None
        return ReponseIA(donnees, str(d.get("model", ""))[:60], entree, sortie)


class _BetaRefusee(Exception):
    """L'en-tête du repli côté serveur n'est pas accepté par ce compte."""


# ---------------------------------------------------------------- fournisseur factice (tests, écrans)
@dataclass
class _Etat:
    demandes: list = field(default_factory=list)  # requêtes reçues (tests : ce qui serait parti)
    reponse: dict = None  # réponse imposée par un test
    erreur: str = ""  # code d'erreur imposé par un test


def _bloc(texte):
    m = re.search(r"<data>\s*(.*?)\s*</data>", texte, re.S)
    try:
        return json.loads(m.group(1)) if m else {}
    except ValueError:
        return {}


def _mots(t):
    return {m for m in re.findall(r"\w+", (t or "").lower()) if len(m) > 2}


class FournisseurFactice(Fournisseur):
    code = "factice"
    nom = "Fake provider (tests)"
    hote = "none"  # écrit entre parenthèses par la page (« Fake provider (tests) (none) »)
    modeles = [("factice-1", "Fake model", "admin.ia.modele.factice")]
    modele_par_defaut = "factice-1"
    etat = _Etat()

    @classmethod
    def remettre(cls):
        cls.etat = _Etat()

    def demander(self, r):
        self.etat.demandes.append(r)
        if self.etat.erreur:
            raise ErreurIA(self.etat.erreur)
        if self.etat.reponse is not None:
            return ReponseIA(self.etat.reponse, r.modele)
        d = _bloc(r.donnees)
        if r.usage == "expliquer_alerte":
            constat = d.get("finding") or ""
            return ReponseIA({"explanation": f"(fake) The value differs from the usual figures. {constat}".strip(),
                              "checks": ["(fake) Check the unit.", "(fake) Check the scope."]}, r.modele)
        if r.usage == "reprise":
            kpis = d.get("kpis") or []
            sortie = []
            for l in d.get("labels") or []:
                mots = _mots(l.get("label")) | _mots(l.get("beside"))
                meilleur = max(kpis, key=lambda k: len(mots & _mots(k.get("name"))), default=None)
                code = meilleur["code"] if meilleur and mots & _mots(meilleur.get("name")) else ""
                sortie.append({"id": l.get("id"), "code": code, "reason": "(fake) shared words" if code else "(fake) no match"})
            return ReponseIA({"matches": sortie}, r.modele)
        if r.usage == "traduction":
            cible = str(d.get("target_language", ""))[:2].lower()
            return ReponseIA({"translations": [{"id": t.get("id"), "text": f"[{cible}] {t.get('text', '')}"}
                                               for t in d.get("texts") or []]}, r.modele)
        return ReponseIA({}, r.modele)


FOURNISSEURS = {f.code: f for f in (FournisseurClaude, FournisseurFactice)}


def disponibles():
    """{code: classe} des fournisseurs proposés : le factice seulement dans les tests ou avec AI_FAKE_PROVIDER=1."""
    return {c: f for c, f in FOURNISSEURS.items() if c != "factice" or settings.IA_FOURNISSEUR_FACTICE}
