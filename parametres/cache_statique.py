"""Cache long pour les fichiers statiques versionnés par leur adresse.

La feuille de style et le script de la Visualisation sont appelés avec ``?v=<version>-<empreinte du fichier>``
(``contexte.version_css``) : l'adresse change dès que le fichier change. Cette adresse-là peut donc se garder un an dans le
navigateur sans risque de servir une vieille feuille après une mise à jour. WhiteNoise ne sait pas distinguer l'adresse
avec ou sans ``?v=`` (son ``max-age`` de 60 secondes vaut pour tous les fichiers) : ce petit intergiciel, placé juste avant
lui, remplace l'en-tête seulement quand ``v`` est la version courante du fichier. Sans ``v``, ou avec une ancienne
version, l'en-tête de WhiteNoise reste (60 secondes).
"""
from django.conf import settings

from .contexte import version_css

FICHIERS_VERSIONNES = ("css/outil.css", "js/visualisation.js")
UN_AN = 31536000


class CacheStatiqueVersionneMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        reponse = self.get_response(request)
        if request.method in ("GET", "HEAD") and reponse.status_code == 200 and request.path.startswith(settings.STATIC_URL):
            fichier = request.path[len(settings.STATIC_URL):]
            v = request.GET.get("v")
            if v and fichier in FICHIERS_VERSIONNES and v == version_css(fichier):
                reponse["Cache-Control"] = f"public, max-age={UN_AN}, immutable"
        return reponse
