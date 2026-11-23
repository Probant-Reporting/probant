"""Réponses aux envois du script des pages (fetch, en-tête « X-Requested-With: fetch ») : un motif lisible en JSON au lieu
d'une page HTML que le script ne sait pas afficher.

- Session expirée (plus de 12 h, ou déconnexion dans un autre onglet) : 401 avec le motif, au lieu d'une redirection
  vers la page de connexion (le panneau restait muet, bouton grisé).
- Refus (PermissionDenied) : 403 avec le motif du refus (« Saisie fermée aux contributeurs… »), au lieu de « Action non
  autorisée. ».
Sans script (pages complètes), rien ne change.

Un seul format d'erreur pour toutes les réponses JSON de l'outil : ``reponse_erreur`` (écrite dans ``espaces/requetes.py``,
que ``espaces`` utilise aussi sans importer ``collecte`` ; réexportée ici, où la cherchent les vues).
"""
from django.conf import settings
from urllib.parse import urlsplit

from django.shortcuts import render, resolve_url
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.defaults import permission_denied

from espaces.requetes import est_script, reponse_erreur  # noqa: F401  (reponse_erreur : réexportée pour les vues)
from parametres.libelles import libelle


def refus(request, exception=None):
    """Page 403 (``handler403``) : en JSON avec le motif pour le script, la page habituelle sinon."""
    if est_script(request):
        motif = str(exception) if exception is not None else ""
        return reponse_erreur(motif or libelle("messages.reponses.refus"), status=403)
    return permission_denied(request, exception)


def echec_csrf(request, reason=""):
    """Jeton CSRF périmé ou absent (``CSRF_FAILURE_VIEW``) : page de l'outil, ou motif en JSON pour le script. Le motif
    technique de Django (``reason``) n'est jamais affiché, même en mode DEBUG. Le lien de retour mène à la page d'où
    vient l'envoi si elle est de l'outil (l'ouvrir la recharge), à l'accueil sinon."""
    if est_script(request):
        return reponse_erreur(libelle("cadre.erreur.csrf.texte"), status=403)
    origine = request.META.get("HTTP_REFERER", "")
    retour = "/"
    if origine and url_has_allowed_host_and_scheme(origine, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        morceaux = urlsplit(origine)
        retour = morceaux.path + (f"?{morceaux.query}" if morceaux.query else "") or "/"
        # chemin « //autre.site » ou « /\autre.site » : adresse d'un autre site pour le navigateur
        if not url_has_allowed_host_and_scheme(retour, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            retour = "/"
    reponse = render(request, "403_csrf.html", {"retour": retour}, status=403)
    reponse["Cache-Control"] = "no-store"
    return reponse


class SessionExpireeMiddleware:
    """Envoi du script sans session (redirigé vers la connexion par ``login_required``) : 401 et un motif lisible."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        reponse = self.get_response(request)
        if reponse.status_code in (301, 302) and est_script(request) and not request.user.is_authenticated:
            if reponse.get("Location", "").split("?")[0] == resolve_url(settings.LOGIN_URL):
                return reponse_erreur(libelle("messages.reponses.session_expiree"), status=401, session_expiree=True)
        return reponse
