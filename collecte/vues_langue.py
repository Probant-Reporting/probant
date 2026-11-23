"""Choix de la langue de l'interface dans la barre du haut (FR / EN / ES), aussi pour un visiteur (page de connexion).

Le choix est gardé dans la session ; pour une personne connectée, il devient aussi la langue de son compte
(``Utilisateur.langue``, comme dans Mon compte) : les contenus traduits (noms des KPI…) suivent, avec le repli habituel.
Seule la préférence de la personne change : aucun contenu saisi n'est touché (permis aussi au lecteur et à l'auditeur).
"""
from django.http import HttpResponseNotAllowed
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme

from espaces.comptes import recopier_langue
from parametres import langues as L

from .models import Journal


def changer_langue(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    code = request.POST.get("langue", "")
    suivant = request.POST.get("suivant") or "/"
    if not url_has_allowed_host_and_scheme(suivant, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        suivant = "/"
    if code in L.langues_interface():
        request.session[L.CLE_SESSION] = code
        u = request.user
        if u.is_authenticated and u.langue != code:
            Journal.ecrire(u, "reglage_compte", u, "langue", u.langue or "(installation)", code)
            u.langue = code
            u.save(update_fields=["langue"])
            recopier_langue(u)
    return redirect(suivant)
