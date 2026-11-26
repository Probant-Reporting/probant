"""Pages des espaces : connexion (comptes communs), page « pas d'accès »."""
from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect, render

from parametres.libelles import libelle
from referentiel.connexion import FormulaireConnexion

from . import contexte as E
from .models import Compte, Espace


def espaces_de(compte_id):
    """Espaces actifs où ce compte a un accès actif : [(espace, rôle)], dans l'ordre des espaces."""
    from .models import AccesEspace

    acces = (AccesEspace.objects.filter(compte_id=compte_id, actif=True, espace__etat=Espace.Etat.ACTIF)
             .select_related("espace").order_by("espace__rang", "espace__nom"))
    return [(a.espace, a.role) for a in acces]


class Connexion(LoginView):
    """Connexion unique pour tous les espaces. Sans accès à l'espace de cette page : connexion dans l'espace où la personne
    a accès (le dernier utilisé d'abord), avec un message."""

    authentication_form = FormulaireConnexion

    def get_context_data(self, **kwargs):
        from connexion_entreprise import regles

        contexte = super().get_context_data(**kwargs)
        r = regles.reglage()
        # bouton du compte d'entreprise (docs/single_sign_on.md) : seulement allumée et réglée ; libellé choisi ou par défaut
        contexte["connexion_entreprise"] = {"libelle": r.libelle_bouton} if regles.active(r) else None
        return contexte

    def form_valid(self, form):
        user = form.get_user()
        code = form.espace_ailleurs
        if code and code != E.code_courant():
            with E.toutes_les_bases():
                auth_login(self.request, user)
            Compte.objects.filter(pk=user.pk).update(dernier_espace=code)
            ici = E.espace_courant()
            la = Espace.objects.filter(code=code).first()
            messages.info(self.request, libelle("espaces.connexion.ailleurs", ici=ici.nom, la=la.nom if la else code))
            return redirect(E.url_espace(code))
        Compte.objects.filter(pk=user.pk).update(dernier_espace=E.code_courant())
        return super().form_valid(form)


def pas_d_acces(request, compte_id):
    """Personne connectée (compte actif) sans accès à l'espace de cette adresse."""
    ici = E.espace_courant()
    return render(request, "espaces/pas_d_acces.html", {
        "espace_refuse": ici, "page": "pas_d_acces",
        "mes_espaces": [(e, E.url_espace(e.code)) for e, _ in espaces_de(compte_id) if e.code != ici.code],
    }, status=403)


# ---------------------------------------------------------------- page « Espaces » (gestionnaires)
def _exiger_gestionnaire(request):
    from django.core.exceptions import PermissionDenied

    from .comptes import est_gestionnaire

    if not est_gestionnaire(request.user):
        raise PermissionDenied(libelle("espaces.erreur.reserve"))


def liste(request):
    """Espaces de l'installation : nom, adresse, comptes ayant accès, date de création, état ; nouvel espace, renommer,
    archiver ou réactiver, reprendre une création interrompue."""
    from .creation import poursuivre
    from .models import AccesEspace

    if not request.user.is_authenticated:
        return redirect(f"{E.url_espace(E.code_courant(), 'login')}?next={request.path}")
    _exiger_gestionnaire(request)
    if request.method == "POST" and request.POST.get("action") in ("gestionnaire", "bloquer"):
        _personne(request)
        return redirect(f"{E.url_espace(E.code_courant(), 'espaces:liste')}#personnes")
    if request.method == "POST":
        e = Espace.objects.filter(code=request.POST.get("code", "")).first()
        action = request.POST.get("action")
        if e is None:
            messages.error(request, libelle("espaces.erreur.introuvable"))
        elif action == "renommer":
            nom = request.POST.get("nom", "").strip()[:80]
            if not nom:
                messages.error(request, libelle("espaces.erreur.nom_vide"))
            elif Espace.objects.filter(nom__iexact=nom).exclude(pk=e.pk).exists():
                messages.error(request, libelle("espaces.erreur.nom_pris", nom=nom))
            else:
                e.nom = nom
                e.save(update_fields=["nom"])
                messages.success(request, libelle("espaces.liste.renomme", nom=nom))
        elif action in ("archiver", "reactiver") and not e.principal:
            e.etat = Espace.Etat.ARCHIVE if action == "archiver" else Espace.Etat.ACTIF
            e.save(update_fields=["etat"])
            if action == "reactiver":
                from .comptes import reconcilier

                reconcilier([e.code])  # comptes changés pendant l'archivage
            messages.success(request, libelle("espaces.liste.archive" if action == "archiver" else "espaces.liste.reactive",
                                              nom=e.nom))
        elif action == "reprendre" and e.etat == Espace.Etat.CREATION:
            try:
                poursuivre(e, request.user)
            except Exception as x:  # noqa: BLE001 - message lisible, l'espace reste « en création »
                messages.error(request, libelle("espaces.erreur.creation", erreur=x))
            else:
                return _vers_le_nouvel_espace(request, e)
        return redirect("espaces:liste")
    nb = {}
    for a in AccesEspace.objects.filter(actif=True).values_list("espace_id", flat=True):
        nb[a] = nb.get(a, 0) + 1
    lignes = [{"e": e, "adresse": "/" if e.principal else f"/espace/{e.code}/", "comptes": nb.get(e.pk, 0),
               "etat": libelle(f"espaces.etat.{e.etat}"),
               "url": E.url_espace(e.code) if e.etat == Espace.Etat.ACTIF else ""} for e in Espace.objects.all()]
    return render(request, "espaces/liste.html", {"page": "administration", "rubrique": "parametres",
                                                  "sous_rubrique": "espaces", "lignes": lignes, **_personnes()})


def _personnes():
    """« Personnes et accès » : chaque compte, son rôle dans chaque espace (index des accès), gestionnaire ou non,
    connexion permise ou bloquée (tous les espaces)."""
    from .contexte_gabarits import role
    from .models import AccesEspace

    espaces = [e for e in Espace.objects.all() if e.etat != Espace.Etat.CREATION]
    acces = {}
    for a in AccesEspace.objects.all():
        acces.setdefault(a.compte_id, {})[a.espace_id] = a
    personnes = []
    for c in Compte.objects.order_by("last_name", "first_name", "email"):
        roles = []
        for e in espaces:
            a = acces.get(c.pk, {}).get(e.pk)
            roles.append("" if a is None else role(a.role) if a.actif else libelle("espaces.personnes.desactive",
                                                                                    role=role(a.role)))
        if any(roles) or c.gestionnaire:
            personnes.append({"c": c, "roles": roles})
    return {"espaces_colonnes": espaces, "personnes": personnes}


def _personne(request):
    """Gestionnaire des espaces oui / non ; connexion bloquée ou permise dans tous les espaces."""
    c = Compte.objects.filter(pk=request.POST.get("compte") or 0).first()
    oui = request.POST.get("valeur") == "1"
    if c is None:
        messages.error(request, libelle("espaces.erreur.compte_introuvable"))
    elif c.pk == request.user.pk and not (oui if request.POST["action"] == "gestionnaire" else not oui):
        messages.error(request, libelle("espaces.erreur.soi_meme"))
    elif request.POST["action"] == "gestionnaire":
        Compte.objects.filter(pk=c.pk).update(gestionnaire=oui)
        messages.success(request, libelle("espaces.personnes.nomme" if oui else "espaces.personnes.retire", nom=c))
    else:
        Compte.objects.filter(pk=c.pk).update(actif=not oui)
        messages.success(request, libelle("espaces.personnes.bloque" if oui else "espaces.personnes.debloque", nom=c))

def _vers_le_nouvel_espace(request, e):
    messages.success(request, libelle("espaces.nouveau.cree", nom=e.nom))
    return redirect(E.url_espace(e.code, "parametres:mise_en_place_etape", 2))


def nouveau(request):
    from .creation import ErreurEspace, code_propose, creer

    if not request.user.is_authenticated:
        return redirect(f"{E.url_espace(E.code_courant(), 'login')}?next={request.path}")
    _exiger_gestionnaire(request)
    valeurs = {"nom": "", "code": "", "identite": True}
    erreur = ""
    if request.method == "POST":
        valeurs = {"nom": request.POST.get("nom", "").strip(), "code": request.POST.get("code", "").strip(),
                   "identite": request.POST.get("identite") == "on"}
        valeurs["code"] = valeurs["code"] or code_propose(valeurs["nom"])
        try:
            e = creer(valeurs["nom"], valeurs["code"], request.user, valeurs["identite"])
        except ErreurEspace as x:
            erreur = str(x)
        except Exception as x:  # noqa: BLE001 - l'espace reste « en création », repris depuis la liste
            import logging

            logging.getLogger("reporting.espaces").exception("Creation of space \"%s\" interrupted", valeurs["code"])
            erreur = libelle("espaces.erreur.interrompue", erreur=x)
        else:
            return _vers_le_nouvel_espace(request, e)
    return render(request, "espaces/nouveau.html", {"page": "administration", "rubrique": "parametres",
                                                    "sous_rubrique": "espaces", "valeurs": valeurs, "erreur": erreur},
                  status=400 if erreur else 200)
