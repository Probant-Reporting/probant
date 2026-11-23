"""Pannes de stockage pendant une requête : disque plein, dossier ou base en lecture seule, erreur d'entrée-sortie.

Toute écriture de l'outil passe par une transaction (rien n'est enregistré à moitié) ; la personne voit une page claire
(503 : rien n'a été enregistré, prévenir l'administrateur) au lieu de « Erreur du serveur », et l'IT trouve la cause en
une ligne dans le journal du serveur. /sante/ signale aussi un disque presque plein (parametres/vues_hebergement.py).
"""
import errno
import logging

from django.db import DatabaseError
from django.shortcuts import render

journal = logging.getLogger("reporting.stockage")

ERRNOS = {errno.ENOSPC, errno.EDQUOT, errno.EROFS, errno.EIO}
TEXTES_SQLITE = ("database or disk is full", "disk i/o error", "readonly database", "unable to open database file")


def panne_de_stockage(exc):
    """Vrai si ``exc`` (ou sa cause) vient du stockage : disque plein, lecture seule, entrée-sortie."""
    vus = set()
    while exc is not None and id(exc) not in vus:
        vus.add(id(exc))
        if isinstance(exc, OSError) and exc.errno in ERRNOS:
            return True
        if isinstance(exc, DatabaseError) and any(t in str(exc).lower() for t in TEXTES_SQLITE):
            return True
        exc = exc.__cause__ or exc.__context__
    return False


class PanneStockageMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if not panne_de_stockage(exception):
            return None
        journal.error("Storage failure (disk full, read-only or I/O error) on %s %s: %s; nothing was saved",
                      request.method, request.path, exception)
        try:
            return render(request, "503_stockage.html", status=503)
        except Exception:  # gabarit impossible à lire ou langue introuvable : texte brut
            from django.http import HttpResponse

            return HttpResponse("503 - storage failure (disk full or read-only): nothing was saved. "
                                "Please tell the tool's administrator.", status=503, content_type="text/plain")
