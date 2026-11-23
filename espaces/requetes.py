"""Aides sur la requête et la réponse HTTP communes à toutes les applications. Ici (et non dans ``collecte``) parce que
``espaces`` n'importe jamais ``collecte`` (test ``parametres/test_structure_imports.py``) et que tout le monde importe
``espaces``."""
from django.http import JsonResponse


def est_script(request):
    """Vrai pour une requête envoyée par le script des pages (``fetch``, en-tête « X-Requested-With: fetch ») : la
    réponse attendue est un fragment ou du JSON, pas une page complète. Les en-têtes se lisent sans souci de la casse."""
    return request.headers.get("X-Requested-With") == "fetch"


def reponse_erreur(message, status=400, **plus):
    """Réponse JSON d'erreur, le seul format de l'outil : ``{"ok": false, "erreur": message, "message": message}``, plus les
    champs propres à l'écran (``plus``). Les deux clés : le script des pages lit ``erreur`` puis ``message``
    (``motifErreur``), certains écrans lisent ``message`` (éditeur de référentiel, attribution des SPOC, listes de KPI)."""
    message = str(message)
    return JsonResponse({"ok": False, "erreur": message, "message": message, **plus}, status=status,
                        json_dumps_params={"ensure_ascii": False})
