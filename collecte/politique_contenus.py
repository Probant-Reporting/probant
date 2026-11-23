"""Politique de sécurité des contenus (Content-Security-Policy) de toutes les pages de l'outil.

Chaque requête reçoit un jeton (nonce) tiré au hasard ; chaque ``<script>`` et chaque ``<style>`` écrits dans une page le
portent (``nonce="{% jeton_csp %}"``, bibliothèque ``collecte``). Un script ou un style glissé dans une page sans ce jeton
(texte d'une personne mal échappé, contenu forgé) ne s'exécute pas. Aucun gestionnaire en attribut (``onclick=``…) ni
lien ``javascript:`` : les écouteurs sont posés par les scripts (un test le vérifie sur tous les gabarits).

Politique retenue (voir ``politique``) :

- scripts : fichiers de l'outil et scripts intégrés munis du jeton ; ni ``unsafe-inline`` ni ``unsafe-eval`` ;
- styles : feuilles de l'outil et ``<style>`` munis du jeton (``style-src-elem``) ; les attributs ``style=`` restent permis
  (``style-src-attr 'unsafe-inline'``) : ils portent des valeurs calculées (couleurs réglables, retraits de l'arbre,
  largeurs des barres d'avancement). ``style-src`` garde ``'unsafe-inline'`` pour les navigateurs anciens qui ne
  connaissent pas les deux directives précédentes (sans jeton, sinon ils ignoreraient ``'unsafe-inline'``) ;
- images : l'outil, ``data:`` (icône de l'onglet, pictogrammes de la feuille de style) et ``blob:`` (aperçu du logo choisi) ;
- polices, connexions des scripts, formulaires : l'outil seulement ; aucun cadre, aucun objet ; la page ne s'affiche dans
  le cadre d'aucun site (comme ``X-Frame-Options: DENY``).

Mise en production : ``CONTENT_SECURITY_POLICY_MODE=report-only`` (docs/installation.md) envoie la même politique en
« signalement seulement » (``Content-Security-Policy-Report-Only``) : rien n'est bloqué, le navigateur signale dans sa
console ce qui l'aurait été. Aucun point de collecte des rapports.

Les réponses qui ont déjà leur politique (fichiers déposés servis par ``garde_requetes.reponse_inerte`` : logo, preuves)
la gardent, plus stricte. Les réponses qui ne sont pas des pages (JSON, fichiers, serveur MCP) ne reçoivent rien.
"""
import secrets
from contextvars import ContextVar

from django.conf import settings

_jeton = ContextVar("jeton_csp", default="")

ENTETE = "Content-Security-Policy"
ENTETE_SIGNALEMENT = "Content-Security-Policy-Report-Only"
MODES = ("enforce", "report-only")


def jeton_courant():
    """Jeton de la requête en cours ; vide hors requête (gabarit rendu par une commande, un e-mail)."""
    return _jeton.get()


def politique(jeton):
    """En-tête complet pour ce jeton."""
    return "; ".join([
        "default-src 'self'",
        f"script-src 'self' 'nonce-{jeton}'",
        "style-src 'self' 'unsafe-inline'",
        f"style-src-elem 'self' 'nonce-{jeton}'",
        "style-src-attr 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "font-src 'self'",
        "connect-src 'self'",
        "frame-src 'none'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ])


def mode():
    """« enforce » (par défaut) ou « report-only » ; une valeur inconnue garde la politique bloquante."""
    m = str(getattr(settings, "POLITIQUE_CONTENUS_MODE", "enforce")).strip().lower()
    return m if m in MODES else "enforce"


def _est_page(reponse):
    return reponse.get("Content-Type", "").split(";")[0].strip().lower() == "text/html"


class PolitiqueContenusMiddleware:
    """Tire le jeton de la requête (``request.csp_nonce`` et ``jeton_courant()``), puis pose la politique sur chaque page
    HTML qui n'en a pas déjà une. Placé tout en haut de la pile : les pages fabriquées par les autres intergiciels (pas
    d'accès, panne du stockage) et les pages d'erreur (400, 403, 404, 500) la reçoivent aussi."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        jeton = secrets.token_urlsafe(18)
        request.csp_nonce = jeton
        marque = _jeton.set(jeton)
        try:
            reponse = self.get_response(request)
        finally:
            _jeton.reset(marque)
        if not _est_page(reponse) or ENTETE in reponse or ENTETE_SIGNALEMENT in reponse:
            return reponse
        if settings.DEBUG and reponse.status_code in (404, 500):
            return reponse  # page technique de Django (développement seulement) : styles et scripts intégrés sans jeton
        reponse[ENTETE_SIGNALEMENT if mode() == "report-only" else ENTETE] = politique(jeton)
        return reponse
