"""Les sessions suivent la règle du mot de passe (``regles.session_permise``) : une session ouverte par mot de passe pour
un compte qui n'y a plus droit (connexion d'entreprise allumée après coup, gestionnaire des espaces qui perd ce rôle)
est fermée à la requête suivante, avec un message simple sur la page de connexion. La méthode est notée dans la session
à l'ouverture (``flux.CLE_METHODE`` : « entreprise » par ``flux.retour``, « mot_de_passe » par
``referentiel.connexion._reussite``) ; une session sans méthode (ouverte avant la mise à jour) compte comme
« mot_de_passe ». Requête du script des pages : la réponse « session expirée » (401) de
``collecte.reponses_script.SessionExpireeMiddleware``. Éteinte : aucune requête en base (état mis en cache)."""
from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect

from espaces import contexte as E
from parametres.libelles import libelle

from . import regles
from .flux import CLE_METHODE


class SessionSelonLaRegleMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        u = getattr(request, "user", None)
        if u is not None and u.is_authenticated and not regles.session_permise(u.pk, request.session.get(CLE_METHODE, "")):
            code = E.code_courant()
            logout(request)
            messages.warning(request, libelle("cadre.connexion.entreprise.session_fermee"))
            return redirect(E.url_espace(code, "login"))
        return self.get_response(request)
