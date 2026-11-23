"""Garde des requêtes : entrées forgées refusées tôt, avec une réponse claire au lieu d'une erreur 500
ou d'un disque rempli.

- ``GardeRequetesMiddleware`` : envoi trop gros (413, avant d'être reçu en entier) : sans connexion, plus de 1 Mo ;
  connecté, plus que la plus grande des tailles d'import et de preuve (plus une marge), sauf le dépôt d'une sauvegarde
  par un administrateur (MAX_BACKUP_UPLOAD_MB) ; octet NUL dans l'adresse, un formulaire ou un corps JSON (400 :
  PostgreSQL le refuse dans un texte, SQLite l'accepte).
- ``nombre_envoye`` : compteur de lignes d'un formulaire (« nb »), borné par ce qui a vraiment été envoyé.
- ``reponse_inerte`` : fichier déposé servi sans pouvoir agir dans la page (logo, preuve).
"""
from django.conf import settings
from django.core.exceptions import SuspiciousOperation
from django.http import HttpResponse
from django.urls import Resolver404, resolve

ENVOI_ANONYME_MAX = 1024 * 1024  # octets d'un envoi sans connexion (connexion, création du premier compte : quelques champs)
MARGE_ENVOI = 1024 * 1024  # en-têtes du formulaire et autres champs autour du fichier


def envoi_max():
    """Taille d'un envoi d'une personne connectée : le plus gros fichier accepté (import ou preuve), plus une marge."""
    return max(settings.IMPORT_TAILLE_MAX, settings.PREUVE_TAILLE_MAX) + MARGE_ENVOI


def _depot_sauvegarde(request):
    try:
        m = resolve(request.path_info)
    except Resolver404:
        return False
    return m.view_name == "parametres:sauvegarde_deposer"


def trop_gros(limite):
    from parametres.libelles import libelle

    texte = libelle("messages.envoi.trop_gros", mo=f"{limite / 1024 / 1024:.0f}")
    return HttpResponse(texte, status=413, content_type="text/plain; charset=utf-8")


class GardeRequetesMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if "\x00" in request.path or "%00" in request.META.get("QUERY_STRING", ""):
            raise SuspiciousOperation("octet NUL dans l'adresse")
        if request.method in ("POST", "PUT", "PATCH"):
            try:
                taille = int(request.META.get("CONTENT_LENGTH") or 0)
            except ValueError:
                taille = 0
            if taille > ENVOI_ANONYME_MAX and not request.user.is_authenticated:
                return HttpResponse(status=413)
            if taille > envoi_max():  # refusé avant d'être reçu : la preuve de 5 Mo n'était contrôlée qu'après
                if not (getattr(request.user, "est_admin", False) and _depot_sauvegarde(request)):
                    return trop_gros(envoi_max() - MARGE_ENVOI)
                if taille > settings.SAUVEGARDE_DEPOT_MAX:
                    return trop_gros(settings.SAUVEGARDE_DEPOT_MAX)
            if (request.content_type or "").startswith("application/json"):
                if b"\\u0000" in request.body or b"\x00" in request.body:
                    raise SuspiciousOperation("octet NUL dans le corps JSON")
            elif any("\x00" in cle or any("\x00" in v for v in valeurs) for cle, valeurs in request.POST.lists()):
                raise SuspiciousOperation("octet NUL dans le formulaire")
        return self.get_response(request)


def nombre_envoye(P, cle):
    """Nombre de lignes annoncé par un formulaire (champ caché « nb »…), borné par le nombre de champs reçus : un nombre
    forgé (« 99999999999 », « abc ») ne fait ni tourner le serveur à vide ni planter la page."""
    try:
        n = int(P.get(cle) or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, min(n, len(P)))


def reponse_inerte(reponse):
    """Fichier déposé (logo, preuve) : aucun script, aucun chargement, même si le fichier est un contenu actif déguisé.
    PDF : sans la directive ``sandbox``, que certains navigateurs refusent pour un PDF (affichage vide ou téléchargement
    forcé) ; le type est forcé d'après le fichier rangé et ``nosniff`` empêche de le lire comme une page, donc rien ne
    s'exécute dans l'outil. Images et autres fichiers : protection complète."""
    pdf = reponse.get("Content-Type", "").split(";")[0].strip().lower() == "application/pdf"
    reponse["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'" + ("" if pdf else "; sandbox")
    reponse["X-Content-Type-Options"] = "nosniff"
    return reponse
