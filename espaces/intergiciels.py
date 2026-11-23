"""Intergiciels des espaces.

- ``EspaceMiddleware`` : l'adresse désigne l'espace (``/espace/<code>/…`` ; la racine pour l'espace principal). Le
  préfixe est retiré de ``request.path_info``, les liens le reprennent (``script_prefix``) et la requête entière se
  déroule dans ``activer(code)``.
"""
import re

from django.http import Http404
from django.utils.functional import SimpleLazyObject

from parametres.libelles import libelle

from . import contexte as E
from .requetes import est_script, reponse_erreur

MOTIF = re.compile(r"^/espace/([^/]+)(/.*)?$")


class EspaceMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        m = MOTIF.match(request.path_info)
        code = E.PRINCIPAL
        if m:
            from .models import Espace

            code = m.group(1)
            espace = Espace.objects.filter(code=code).first() if E.CODE.match(code) and code != E.PRINCIPAL else None
            if espace is None or espace.etat != Espace.Etat.ACTIF:
                raise Http404(libelle("espaces.erreur.inconnu"))
            if E.indisponible(code):
                from django.http import HttpResponse

                return HttpResponse(libelle("espaces.erreur.indisponible", nom=espace.nom), status=503,
                                    content_type="text/plain; charset=utf-8")
            reste = m.group(2) or "/"
            request.path_info = reste
            request.META["PATH_INFO"] = reste
        with E.activer(code):
            request.espace = SimpleLazyObject(E.espace_courant)
            return self.get_response(request)


class AccesEspaceMiddleware:
    """Après l'authentification : note la personne qui agit (règle contre l'élévation de droits entre espaces) et, pour
    une personne connectée sans accès à cet espace, affiche la page « Vous n'avez pas accès » (JSON 403 pour le script)
    plutôt que la page de connexion."""

    LIBRES = ("/static/", "/media/", "/sante/", "/identite/logo/", "/connexion/", "/deconnexion/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        u = getattr(request, "user", None)
        connecte = u is not None and u.is_authenticated
        if not connecte and not request.path_info.startswith(self.LIBRES):
            reponse = self._pas_d_acces(request)
            if reponse is not None:
                return reponse
        with E.acteur(u.pk if connecte else E.ANONYME):
            return self.get_response(request)

    def _pas_d_acces(self, request):
        from django.contrib.auth import SESSION_KEY

        from .models import Compte

        session = getattr(request, "session", None)
        uid = session.get(SESSION_KEY) if session is not None else None
        if not uid:
            return None
        try:
            uid = int(uid)
        except (TypeError, ValueError):
            return None
        if not Compte.objects.filter(pk=uid, actif=True).exists():
            return None
        ici = E.espace_courant()
        if est_script(request) or "application/json" in request.headers.get("Accept", ""):
            return reponse_erreur(libelle("espaces.pas_acces.titre", nom=ici.nom), status=403)
        from .vues import pas_d_acces

        with E.acteur(E.ANONYME):
            return pas_d_acces(request, uid)
