"""Compte de la personne connectée : langue (interface et contenus), changement de mot de passe (obligatoire après un
mot de passe provisoire), apparence, et « Récemment supprimés » (ce que la personne a supprimé et peut encore restaurer,
collecte/corbeille.py)."""
import secrets

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import translation
from django.views.decorators.cache import never_cache

from espaces.requetes import est_script
from parametres import langues as L
from parametres.libelles import libelle

from .models import Journal

ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789"  # sans caractères ambigus (l, 1, O, 0…)


def mot_de_passe_provisoire():
    """Ex. « Kp7m-Rx4t-Wq9z » : facile à dicter ou recopier."""
    return "-".join("".join(secrets.choice(ALPHABET) for _ in range(4)) for _ in range(3))


class MotDePasseProvisoireMiddleware:
    """Tant que le mot de passe provisoire n'est pas remplacé, seule la page « Mon compte » est accessible. Sauf pour une
    session ouverte par le compte d'entreprise d'une personne qui ne peut plus se connecter par mot de passe
    (connexion_entreprise/regles.py) : son mot de passe provisoire ne sert à rien, rien ne lui est demandé."""

    def __init__(self, get_response):
        self.get_response = get_response

    @staticmethod
    def _par_compte_d_entreprise(request, u):
        from connexion_entreprise.flux import CLE_METHODE
        from connexion_entreprise.regles import mot_de_passe_permis

        session = getattr(request, "session", None)
        return session is not None and session.get(CLE_METHODE) == "entreprise" and not mot_de_passe_permis(u.pk)

    def __call__(self, request):
        u = getattr(request, "user", None)
        if u is not None and u.is_authenticated and getattr(u, "doit_changer_mdp", False) \
                and not self._par_compte_d_entreprise(request, u):
            libres = (reverse("collecte:mon_compte"), reverse("logout"), reverse("langue"), reverse("collecte:confidentialite"))
            if request.path not in libres and not request.path.startswith(("/static/", "/media/")):
                return redirect("collecte:mon_compte")
        return self.get_response(request)


class FormulaireMotDePasse(PasswordChangeForm):
    """Changement de mot de passe dont l'ancien mot de passe a des essais limités : après
    ``connexion.ESSAIS_MAX`` échecs, il n'est plus vérifié pendant ``connexion.DUREE`` (même le bon), avec un message
    clair ; la session reste ouverte. Un bon ancien mot de passe remet le compteur à zéro."""

    def clean_old_password(self):
        from referentiel import connexion as CX

        if CX.mdp_actuel_bloque(self.user):
            CX.noter_echec_mdp_actuel(self.user)  # insister prolonge l'attente
            raise ValidationError(libelle("cadre.compte.mdp.trop_essais"), code="trop_d_essais")
        try:
            ancien = super().clean_old_password()
        except ValidationError:
            CX.noter_echec_mdp_actuel(self.user)
            raise
        CX.oublier_mdp_actuel(self.user)
        return ancien


def formulaire_mot_de_passe(user, data=None):
    """Changement de mot de passe avec les libellés et l'autocomplete de l'outil, en GET comme après une erreur (POST)."""
    form = FormulaireMotDePasse(user, data)
    form.fields["old_password"].label = libelle("cadre.compte.mdp.actuel_provisoire" if user.doit_changer_mdp else "cadre.compte.mdp.actuel")
    form.fields["old_password"].widget.attrs["autocomplete"] = "current-password"
    # Django met le focus sur ce champ à chaque affichage, ce qui fait défiler la page sous Langue et Apparence :
    # le focus n'y va que pour reprendre une saisie refusée (``form.is_valid()`` a alors déjà rempli les erreurs)
    form.fields["old_password"].widget.attrs.pop("autofocus", None)
    form.fields["new_password1"].label = libelle("cadre.compte.mdp.nouveau")
    form.fields["new_password2"].label = libelle("cadre.compte.mdp.confirmation")
    # messages de l'outil, pas ceux de Django 
    form.error_messages = {**form.error_messages, "password_incorrect": libelle("cadre.compte.mdp.erreur_actuel"),
                           "password_mismatch": libelle("cadre.compte.mdp.erreur_confirmation")}
    for nom in ("new_password1", "new_password2"):
        form.fields[nom].widget.attrs["autocomplete"] = "new-password"
    return form


def langues_proposees():
    """[(code, nom)] des langues de Mon compte : celles de l'interface (nom dans leur langue), puis les autres langues
    actives des contenus (l'interface s'y affiche alors dans la langue de l'installation)."""
    sortie = [(c, libelle("cadre.langue.nom", c)) for c in L.langues_interface()]
    vus = {c for c, _ in sortie}
    return sortie + [(lg.code, lg.libelle) for lg in L.actives() if lg.code not in vus]


@never_cache  # la page peut montrer un jeton d'assistant en clair : gardée par aucun cache (no-store)
@login_required
def mon_compte(request):
    # messages de Django (mot de passe trop court, trop courant…) dans la langue de l'interface
    with translation.override(L.interface()):
        return _mon_compte(request)


def _mon_compte(request):
    form = formulaire_mot_de_passe(request.user)
    if request.method == "POST" and request.POST.get("action") == "apparence":
        # apparence (automatique, claire, sombre) : un choix de cet appareil, gardé dans un cookie (rien dans la base :
        # vaut aussi pour les comptes en lecture seule, et sur la page de connexion de ce navigateur)
        from parametres import couleurs as CO

        par_script = est_script(request)  # appliquée aussitôt par la page (_app/12_communs.js)
        rep = HttpResponse(status=204) if par_script else redirect(reverse("collecte:mon_compte") + "#apparence")
        choisie = request.POST.get("apparence", "")
        if choisie in CO.APPARENCES:
            if choisie == "systeme":
                rep.delete_cookie(CO.COOKIE_APPARENCE, samesite="Lax")
            else:
                rep.set_cookie(CO.COOKIE_APPARENCE, choisie, max_age=400 * 24 * 3600, samesite="Lax",
                               secure=request.is_secure(), httponly=True)
            if not par_script:
                messages.success(request, libelle("cadre.compte.apparence.enregistree"))
        return rep
    if request.method == "POST" and request.POST.get("action") == "langue":
        u, choisie = request.user, request.POST.get("langue", "")
        if choisie in [""] + [c for c, _ in langues_proposees()]:
            if choisie != u.langue:
                Journal.ecrire(u, "reglage_compte", u, "langue", u.langue or "(installation)", choisie or "(installation)")
                u.langue = choisie
                u.save(update_fields=["langue"])
                from espaces.comptes import recopier_langue

                recopier_langue(u)
            # le choix du compte remplace celui de la barre du haut
            if choisie:
                request.session[L.CLE_SESSION] = choisie
            else:
                request.session.pop(L.CLE_SESSION, None)
            messages.success(request, libelle("cadre.compte.langue.enregistree", L.interface_de(choisie)))
        return redirect("collecte:mon_compte")
    mcp = None  # carte « Assistants » (serveur MCP) : jetons de la personne, le nouveau jeton montré une seule fois
    if request.method == "POST" and request.POST.get("action") in ("jeton_creer", "jeton_revoquer"):
        from serveur_mcp.vues import action_jeton

        mcp = action_jeton(request)
        if not isinstance(mcp, dict):
            return mcp
    elif request.method == "POST":
        form = formulaire_mot_de_passe(request.user, request.POST)
        if not form.is_valid():
            form.fields[next(iter(form.errors), "old_password")].widget.attrs["autofocus"] = True
        else:
            from serveur_mcp.jetons import actifs

            avait_jetons = actifs(request.user).exists()  # révoqués par le changement (serveur_mcp/jetons.py)
            u = form.save()
            u.doit_changer_mdp = False
            u.save(update_fields=["doit_changer_mdp"])
            update_session_auth_hash(request, u)
            Journal.ecrire(u, "changement_mdp", u, "mot de passe", "", "(changé par la personne)")
            messages.success(request, libelle("cadre.compte.mdp.change"))
            if avait_jetons:
                messages.info(request, libelle("mcp.jetons.revoques_mdp"))
            return redirect("collecte:accueil")
    if mcp is None and request.method == "GET":  # jeton créé juste avant : montré une seule fois (serveur_mcp/vues.py)
        from serveur_mcp.vues import jeton_montre

        mcp = jeton_montre(request)
    defaut = L.defaut()
    nom_defaut = libelle("cadre.langue.nom", defaut) if defaut in L.langues_interface() else L.libelle(defaut)
    choix_apparence = [(c, libelle(f"cadre.compte.apparence.{c}")) for c in ("systeme", "clair", "sombre")]
    from . import corbeille as CB
    from .models import jours_corbeille
    from serveur_mcp.vues import contexte_compte

    from referentiel.historique_connexions import dernieres

    return render(request, "collecte/mon_compte.html", {"form": form, "page": "mon_compte", "langues": langues_proposees(),
                                                          "connexions": dernieres(request.user),
                                                          "langue_defaut": nom_defaut, "choix_apparence": choix_apparence,
                                                          "supprimes": CB.elements(request.user), "jours_corbeille": jours_corbeille(),
                                                          **contexte_compte(request, {"nouveau": mcp.get("mcp_nouveau"), "erreur": mcp.get("mcp_erreur"),
                                                                                      "nom": mcp.get("mcp_nom")} if mcp else None)})
