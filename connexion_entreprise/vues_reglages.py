"""Administration › Paramètres › Connexion d'entreprise (docs/single_sign_on.md) : réglage de l'installation, réservé aux
gestionnaires des espaces (comme la page Espaces) : il vaut pour tous les espaces, et la personne qui l'allume garde
toujours son mot de passe (compte de secours).

- Champs : adresse du fournisseur (émetteur), identifiant du client, secret du client (jamais réaffiché : un champ
  toujours vide et la date de son enregistrement), libellé du bouton, deux choix prudents éteints par défaut.
- « Essayer » : lit la découverte et les clés du fournisseur, sans rien enregistrer, et dit ce qui manque.
- Allumer : seulement si le réglage est complet et que l'essai réussit ; sinon le reste est enregistré et la connexion
  d'entreprise reste éteinte, avec la liste de ce qui manque.
- Chaque changement est noté au journal (``reglage_connexion_entreprise``) ; le secret jamais : « enregistré » ou
  « retiré » seulement.
"""
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.debug import sensitive_post_parameters

from collecte.models import Journal
from espaces import contexte as E
from espaces.comptes import est_gestionnaire
from espaces.models import Compte
from parametres.libelles import libelle

from . import oidc, regles, sortant
from .flux import adresse_retour
from .models import LienEntreprise, ReglageEntreprise
from .secret import chiffrer, dechiffrer, valide

journal = logging.getLogger("connexion_entreprise")
ACTION = "reglage_connexion_entreprise"
CHAMPS = ["actif", "emetteur", "client_id", "libelle_bouton", "email_non_declare", "mot_de_passe_pour_tous"]
# cause d'un essai manqué (oidc.ErreurOIDC.code) → message de l'écran (admin.connexion_entreprise.cause.<message>)
CAUSES = {
    "reseau_adresse_refusee": "adresse", "decouverte_adresse": "adresse", "reseau_injoignable": "injoignable",
    "reseau_delai": "delai", "reseau_tls": "tls", "emetteur_different": "emetteur",
    "sans_flux_code": "exigences", "sans_pkce": "exigences", "algorithmes": "exigences", "authentification_client": "exigences",
    "cles_illisibles": "cles", "sans_cle": "cles", "indisponible": "indisponible",
}


def message_cause(code):
    return libelle(f"admin.connexion_entreprise.cause.{CAUSES.get(code, 'document')}") if code else ""


def exiger_gestionnaire(request):
    if not est_gestionnaire(request.user):
        raise PermissionDenied(libelle("admin.connexion_entreprise.reserve"))


def valider_emetteur(texte):
    """Émetteur nettoyé (sans « / » final), ou ValueError (message en clair)."""
    texte = oidc.normaliser_emetteur(texte)
    if not texte:
        return ""
    try:
        u = sortant.verifier_url(texte)
    except sortant.ErreurReseau:
        raise ValueError(libelle("admin.connexion_entreprise.erreur.emetteur")) from None
    if u.query or u.fragment or len(texte) > 500:
        raise ValueError(libelle("admin.connexion_entreprise.erreur.emetteur"))
    return texte


def _forme_emetteur(texte):
    """Émetteur comparé sans la casse du protocole et du nom du serveur ni la « / » finale ; le chemin tel quel (il
    peut désigner un autre locataire chez le même fournisseur)."""
    from urllib.parse import urlsplit

    texte = oidc.normaliser_emetteur(texte)
    try:
        u = urlsplit(texte)
    except ValueError:
        return texte
    return u._replace(scheme=u.scheme.lower(), netloc=u.netloc.lower()).geturl()


def fournisseur_change(r, valeurs):
    """Le secret enregistré partirait-il vers un autre fournisseur, ou pour un autre client, que ceux pour lesquels il a
    été saisi ? Vrai pour une autre adresse du fournisseur (émetteur) ou un autre identifiant du client (le secret est
    celui d'un client : avec un autre, il serait au mieux faux)."""
    return (_forme_emetteur(r.emetteur) != _forme_emetteur(valeurs.get("emetteur"))
            or (r.client_id or "").strip() != (valeurs.get("client_id") or "").strip())


def _texte(request, nom, longueur):
    return " ".join((request.POST.get(nom) or "").split())[:longueur]


def _lire_formulaire(request):
    """(valeurs, secret nouveau ou "", erreurs {champ: message})."""
    erreurs = {}
    valeurs = {"actif": request.POST.get("actif") == "on", "client_id": _texte(request, "client_id", 255),
               "libelle_bouton": _texte(request, "libelle_bouton", 80),
               "email_non_declare": request.POST.get("email_non_declare") == "on",
               "mot_de_passe_pour_tous": request.POST.get("mot_de_passe_pour_tous") == "on"}
    try:
        valeurs["emetteur"] = valider_emetteur(request.POST.get("emetteur", ""))
    except ValueError as e:
        valeurs["emetteur"] = (request.POST.get("emetteur") or "").strip()[:500]
        erreurs["emetteur"] = str(e)
    if any(ord(c) < 32 for c in valeurs["client_id"]):
        erreurs["client_id"] = libelle("admin.connexion_entreprise.erreur.client_id")
    secret = (request.POST.get("secret") or "").strip()
    if secret and not valide(secret):
        erreurs["secret"] = libelle("admin.connexion_entreprise.erreur.secret")
    return valeurs, secret, erreurs


def _manques(valeurs, secret_lisible):
    """Ce qui manque pour allumer la connexion d'entreprise (codes de libellés)."""
    manques = []
    if not regles.disponible():
        manques.append("indisponible")
    if not valeurs.get("emetteur"):
        manques.append("emetteur")
    if not valeurs.get("client_id"):
        manques.append("client_id")
    if not secret_lisible:
        manques.append("secret")
    return manques


def _essai(emetteur):
    """(contrôles réussis, cause du premier échec ou "") pour l'écran ; jamais d'appel sans émetteur."""
    if not emetteur or not regles.bibliotheques():
        return [], "sans_emetteur" if emetteur == "" else "indisponible"
    return oidc.essayer(emetteur)


def _contexte(request, r, valeurs, erreurs, essai=None):
    if essai is not None:
        essai["message"] = message_cause(essai.get("cause"))
    return {
        "page": "administration", "rubrique": "parametres", "sous_rubrique": "connexion_entreprise",
        "r": r, "v": valeurs, "erreurs": erreurs, "essai": essai,
        "disponible": regles.disponible(), "bibliotheques": regles.bibliotheques(), "active": regles.active(r),
        "secret_present": bool(r.secret_chiffre), "secret_illisible": bool(r.secret_chiffre) and regles.bibliotheques()
        and dechiffrer(r.secret_chiffre) is None,
        "adresse_retour": adresse_retour(request), "liens": LienEntreprise.objects.count(),
    }


def _noter(request, r, avant):
    for c in CHAMPS:
        if getattr(r, c) != avant[c]:
            Journal.ecrire(request.user, ACTION, r, c, avant[c], getattr(r, c))


@login_required
@sensitive_post_parameters("secret")
def reglages(request):
    exiger_gestionnaire(request)
    r = regles.reglage()
    valeurs = {c: getattr(r, c) for c in CHAMPS}
    erreurs, essai = {}, None
    if request.method == "POST":
        action = request.POST.get("action", "enregistrer")
        if action == "oublier_lien":
            return _oublier_lien(request)
        if action == "retirer_secret":
            return _retirer_secret(request)
        valeurs, secret, erreurs = _lire_formulaire(request)
        if action == "essayer":
            if not erreurs.get("emetteur"):
                faits, cause = _essai(valeurs["emetteur"])
                garde = not fournisseur_change(r, valeurs)
                essai = {"faits": faits, "cause": cause, "manques": _manques(valeurs, bool(secret) or (
                    garde and bool(r.secret_chiffre) and regles.bibliotheques() and dechiffrer(r.secret_chiffre) is not None))}
            return render(request, "connexion_entreprise/reglages.html", _contexte(request, r, valeurs, erreurs, essai))
        if erreurs:
            return render(request, "connexion_entreprise/reglages.html", _contexte(request, r, valeurs, erreurs), status=400)
        if secret and not regles.bibliotheques():
            erreurs["secret"] = libelle("admin.connexion_entreprise.manque.indisponible")
            return render(request, "connexion_entreprise/reglages.html", _contexte(request, r, valeurs, erreurs), status=400)
        allumer = valeurs["actif"]
        cause = ""
        if allumer:  # allumer : réglage complet et fournisseur qui répond (geste de la personne : un appel permis)
            lisible = bool(secret) or (not fournisseur_change(r, valeurs) and bool(r.secret_chiffre)
                                       and dechiffrer(r.secret_chiffre) is not None)
            manques = _manques(valeurs, lisible)
            if not manques:
                _, cause = _essai(valeurs["emetteur"])
            if manques or cause:
                valeurs["actif"] = False
                essai = {"faits": [], "cause": cause, "manques": manques}
        with transaction.atomic(using=E.COMMUN):  # relu sous verrou : deux enregistrements à la fois se suivent
            r = ReglageEntreprise.objects.select_for_update().filter(pk=1).first() or ReglageEntreprise()
            avant = {c: getattr(r, c) for c in CHAMPS}
            # autre fournisseur sans nouveau secret : le secret enregistré est effacé (relu sous verrou), jamais envoyé
            # à un fournisseur pour lequel il n'a pas été saisi ; sans secret, la connexion d'entreprise s'éteint
            efface = not secret and bool(r.secret_chiffre) and fournisseur_change(r, valeurs)
            for c in CHAMPS:
                setattr(r, c, valeurs[c])
            if secret:
                remplace = bool(r.secret_chiffre)
                r.secret_chiffre, r.secret_le = chiffrer(secret), timezone.now()
            elif efface:
                r.secret_chiffre, r.secret_le, r.actif = "", None, False
            r.modifie_le, r.modifie_par = timezone.now(), request.user.pk
            r.save()
        oidc.oublier_caches()
        _noter(request, r, avant)
        if secret:
            Journal.ecrire(request.user, ACTION, r, "secret",
                           libelle("admin.connexion_entreprise.journal.secret_enregistre", langue="fr") if remplace else "",
                           libelle("admin.connexion_entreprise.journal.secret_remplace" if remplace else
                                   "admin.connexion_entreprise.journal.secret_enregistre", langue="fr"))
        if efface:
            Journal.ecrire(request.user, ACTION, r, "secret",
                           libelle("admin.connexion_entreprise.journal.secret_enregistre", langue="fr"),
                           libelle("admin.connexion_entreprise.journal.secret_efface_fournisseur", langue="fr"))
            messages.warning(request, libelle("admin.connexion_entreprise.secret_efface_fournisseur"))
        if avant["actif"] != r.actif:
            journal.warning("Company sign-in turned %s by account no. %s", "on" if r.actif else "off", request.user.pk)
        if essai is not None:
            messages.warning(request, libelle("admin.connexion_entreprise.reste_eteinte"))
            return render(request, "connexion_entreprise/reglages.html", _contexte(request, r, valeurs, erreurs, essai))
        messages.success(request, libelle("admin.connexion_entreprise.enregistre"))
        return redirect("connexion_entreprise:reglages_entreprise")
    return render(request, "connexion_entreprise/reglages.html", _contexte(request, r, valeurs, erreurs))


def _retirer_secret(request):
    with transaction.atomic(using=E.COMMUN):
        r = ReglageEntreprise.objects.select_for_update().filter(pk=1).first()
        if r is None or not r.secret_chiffre:
            return redirect("connexion_entreprise:reglages_entreprise")
        r.secret_chiffre, r.secret_le, r.actif = "", None, False  # sans secret, la connexion d'entreprise s'éteint
        r.modifie_le, r.modifie_par = timezone.now(), request.user.pk
        r.save()
    Journal.ecrire(request.user, ACTION, r, "secret", libelle("admin.connexion_entreprise.journal.secret_enregistre", langue="fr"),
                   libelle("admin.connexion_entreprise.journal.secret_retire", langue="fr"))
    messages.success(request, libelle("admin.connexion_entreprise.secret_retire"))
    return redirect("connexion_entreprise:reglages_entreprise")


def _oublier_lien(request):
    """Défait le lien d'un compte avec son compte d'entreprise (adresse donnée à une autre personne chez le
    fournisseur) : sa prochaine connexion d'entreprise crée un nouveau lien."""
    email = (request.POST.get("email") or "").strip()
    c = Compte.objects.filter(email__iexact=email).order_by("pk").first() if email else None
    n = LienEntreprise.objects.filter(compte_id=c.pk).delete()[0] if c is not None else 0
    if n:
        Journal.ecrire(request.user, ACTION, ReglageEntreprise(pk=1), "lien", email, "")
        messages.success(request, libelle("admin.connexion_entreprise.lien_oublie", email=email))
    else:
        messages.info(request, libelle("admin.connexion_entreprise.lien_absent"))
    return redirect("connexion_entreprise:reglages_entreprise")
