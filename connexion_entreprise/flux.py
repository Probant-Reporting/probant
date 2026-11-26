"""Connexion par le compte d'entreprise : aller vers le fournisseur (``debut``), retour du fournisseur (``retour``).

Le fournisseur prouve seulement qui est la personne. Le compte doit déjà exister dans l'outil, actif, avec une adresse
e-mail égale (sans tenir compte des majuscules) à celle que le fournisseur déclare vérifiée ; deux comptes de même
adresse : refus. Aucun compte créé, aucun rôle ni attribution tiré du fournisseur. Un refus dit seulement « demandez à
votre administrateur », sans dire si l'adresse existe.

- ``debut`` (GET, lien du bouton de la page de connexion : un lien et non un formulaire, la politique des contenus
  ``form-action 'self'`` reste entière) : ``state``, ``nonce`` et vérificateur PKCE tirés au hasard, gardés dans la
  session (clé commune à tous les espaces) avec l'espace de la page et la page demandée (``next``, gardée seulement si
  c'est une adresse de l'outil) ; puis redirection vers le fournisseur.
- ``retour`` : la demande correspondant au ``state`` est retirée de la session (un ``state`` ne sert qu'une fois),
  10 minutes au plus ; code échangé, jeton vérifié (``oidc.verifier_jeton``), compte trouvé, session ouverte dans
  l'espace de la page (ou dans l'espace où la personne a accès, comme la connexion par mot de passe).
- Chaque réussite ou refus : une ligne de l'historique des connexions (méthode « entreprise », jamais de jeton ni
  d'adresse réseau).
- Ce qu'une requête anonyme peut écrire : connexion d'entreprise éteinte, rien (ni historique, ni session, ni
  compteur) ; adresse bloquée : rien ; ``state`` inconnu, rejoué ou absent : aucune session, une ligne d'historique par
  adresse et par période (``_sans_demande``).
- Deux compteurs (15 minutes, ``connexion.DUREE``) :
  * par adresse réseau (``REFUS_MAX``) : les refus qu'on obtient sans compte chez le fournisseur (``state`` non valide,
    erreur ou annulation renvoyée par le fournisseur, code refusé, jeton faux) ; au-delà, ``debut`` et ``retour`` sont
    refusés depuis cette adresse ;
  * par personne (``REFUS_MAX_PERSONNE`` ; « sub » du fournisseur) : les refus après une authentification réussie
    (compte inconnu, désactivé, en double, adresse non vérifiée, lien). Jamais par adresse : derrière le proxy d'une
    entreprise, toute la société a la même adresse, et un refus ordinaire ne doit pas enfermer dehors tout le monde.
"""
import hashlib
import logging
import secrets
import time

from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.db import transaction
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from espaces import contexte as E
from parametres.libelles import libelle
from referentiel import connexion as CX
from referentiel import historique_connexions as HC

from . import oidc, regles
from .secret import dechiffrer

journal = logging.getLogger("connexion_entreprise")

CLE_FLUX = "_connexion_entreprise"  # demandes en cours (clé commune à tous les espaces : « _ »)
CLE_METHODE = "_connexion_methode"  # « entreprise » : session ouverte par le compte d'entreprise
FLUX_MAX = 5  # demandes gardées en même temps (plusieurs onglets)
DUREE_FLUX = 10 * 60
REFUS_MAX = 30  # par adresse, refus sans authentification chez le fournisseur
REFUS_MAX_PERSONNE = 10  # par personne (« sub »), refus après une authentification réussie
BACKEND = "referentiel.auth.EmailOuIdentifiant"
CHEMIN_RETOUR = "/connexion/entreprise/retour/"

# cause d'un refus → (message à la personne, motif de l'historique)
MOTIFS = {
    "compte": ("compte", "compte"), "lien": ("compte", "lien"), "adresse": ("adresse", "adresse"),
    "annulee": ("annulee", "annulee"), "expiree": ("expiree", "expiree"), "technique": ("technique", "fournisseur"),
}


def adresse_retour(request):
    """Adresse de retour (« redirect URI ») à recopier chez le fournisseur : toujours celle de la racine de l'outil, quel
    que soit l'espace. PUBLIC_URL si l'IT l'a donnée, sinon l'adresse de la page."""
    from django.conf import settings

    if settings.URL_PUBLIQUE:
        return settings.URL_PUBLIQUE.rstrip("/") + CHEMIN_RETOUR
    return request.build_absolute_uri(CHEMIN_RETOUR)


def _cle_adresse(request):
    ip = CX.reseau(request)
    return "connexion-entreprise:" + hashlib.sha256(ip.encode()).hexdigest()


def _trop_de_refus(request):
    return CX.compteur().get(_cle_adresse(request), 0) >= REFUS_MAX


def _cle_personne(emetteur, sujet):
    return "connexion-entreprise-personne:" + hashlib.sha256(f"{emetteur}\n{sujet}".encode()).hexdigest()


def _noter_refus(cle):
    cache = CX.compteur()
    n = cache.get(cle, 0) + 1
    cache.set(cle, n, CX.DUREE)
    return n


def _premier_de_la_periode(cle):
    """Vrai la première fois dans la période (marque prolongée à chaque appel, comme ``connexion.premier_refus``)."""
    cache, marque = CX.compteur(), "connexion-entreprise-notee:" + cle.split(":", 1)[1]
    if cache.add(marque, 1, CX.DUREE):
        return True
    cache.touch(marque, CX.DUREE)
    return False


def page_suivante_sure(request, suivante):
    """``next`` gardé seulement si c'est une adresse de l'outil (chemin, même hôte) : jamais vers un autre site."""
    if not suivante or not suivante.startswith("/") or suivante.startswith(("//", "/\\")):
        return ""
    if not url_has_allowed_host_and_scheme(suivante, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return ""
    return suivante


def _vers_connexion(request, code_espace, cle_message, niveau=messages.ERROR):
    messages.add_message(request, niveau, libelle(f"cadre.connexion.entreprise.refus.{cle_message}"))
    return redirect(E.url_espace(code_espace, "login"))


def refuser(request, code_espace, cause, detail="", identifiant="", personne=""):
    """Refus : ligne de l'historique dans l'espace de la page, message simple, retour à la page de connexion. Compté pour
    ``personne`` (refus après une authentification réussie : clé ``_cle_personne``), sinon pour l'adresse réseau."""
    message, motif = MOTIFS[cause]
    # cause technique (fournisseur, jeton refusé) : avertissement ; refus ordinaire (compte, adresse, annulée) : information
    (journal.warning if cause == "technique" else journal.info)("Company sign-in refused (%s%s)", cause,
                                                                 f": {detail}" if detail else "")
    _noter_refus(personne or _cle_adresse(request))
    HC.noter("echec", identifiant, alias=E.declarer(code_espace), methode=HC.ENTREPRISE, motif=motif)
    return _vers_connexion(request, code_espace, message)


def _sans_demande(request, code_espace):
    """``state`` inconnu, déjà servi, expiré ou absent : aucune session écrite ; le compteur de l'adresse avance ; une
    seule ligne d'historique (et de journal du serveur) par adresse et par période."""
    cle = _cle_adresse(request)
    _noter_refus(cle)
    if _premier_de_la_periode(cle):
        journal.info("Company sign-in refused (expiree: state unknown, used or expired)")
        HC.noter("echec", "", alias=E.declarer(code_espace), methode=HC.ENTREPRISE, motif=MOTIFS["expiree"][1])
    return _vers_connexion(request, code_espace, MOTIFS["expiree"][0])


def _personne_bloquee(request, code_espace, personne, identifiant):
    """Trop de refus pour cette personne : refusée tout de suite, une ligne « bloquee » par période ; None sinon."""
    if CX.compteur().get(personne, 0) < REFUS_MAX_PERSONNE:
        return None
    CX.compteur().touch(personne, CX.DUREE)
    if _premier_de_la_periode(personne):
        journal.info("Company sign-in refused: too many refusals for one provider account")
        HC.noter("bloquee", identifiant, alias=E.declarer(code_espace), methode=HC.ENTREPRISE, motif="trop")
    return _vers_connexion(request, code_espace, "trop")


@never_cache
@require_GET
def debut(request):
    code = E.code_courant()
    r = regles.reglage()
    if not regles.active(r):
        return _vers_connexion(request, code, "eteinte")
    if _trop_de_refus(request):
        return _vers_connexion(request, code, "trop")
    try:
        doc = oidc.decouvrir(r.emetteur)
    except oidc.ErreurOIDC as e:
        return refuser(request, code, "technique", e.code)
    etat, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    verificateur, defi = oidc.pkce()
    maintenant = time.time()
    flux = {k: v for k, v in (request.session.get(CLE_FLUX) or {}).items()
            if isinstance(v, dict) and maintenant - v.get("t", 0) < DUREE_FLUX}
    for ancien in sorted(flux, key=lambda k: flux[k]["t"])[:max(len(flux) - FLUX_MAX + 1, 0)]:
        del flux[ancien]
    flux[etat] = {"nonce": nonce, "verificateur": verificateur, "espace": code, "t": maintenant,
                  "suivante": page_suivante_sure(request, request.GET.get("next", "")),
                  "emetteur": r.emetteur, "client_id": r.client_id}
    request.session[CLE_FLUX] = flux
    return redirect(oidc.lien_autorisation(doc, r.client_id, adresse_retour(request), etat, nonce, defi))


def _prendre_flux(request, etat):
    """Demande en cours de ce ``state``, retirée de la session (un ``state`` ne sert qu'une fois), ou None. La session
    n'est écrite que si la demande y était (un ``state`` inconnu ne crée ni ne modifie aucune session)."""
    flux = request.session.get(CLE_FLUX) or {}
    if not etat or not isinstance(flux, dict) or etat not in flux:
        return None
    flux = dict(flux)
    f = flux.pop(etat)
    request.session[CLE_FLUX] = flux
    if not isinstance(f, dict) or time.time() - f.get("t", 0) >= DUREE_FLUX:
        return None
    return f


def adresse_verifiee(claims, r):
    """Adresse e-mail déclarée vérifiée par le fournisseur (sans espaces autour), ou "". ``email_verified`` absent :
    acceptée seulement si le réglage le permet (fournisseur qui ne l'envoie pas) ; faux : jamais."""
    email = claims.get("email")
    if not isinstance(email, str) or "@" not in email or len(email) > 254:
        return ""
    verifiee = claims.get("email_verified")
    if isinstance(verifiee, str):
        verifiee = {"true": True, "false": False}.get(verifiee.strip().lower())
    if verifiee is True or (verifiee is None and "email_verified" not in claims and r.email_non_declare):
        return email.strip()
    return ""


def _copie(compte, code):
    """(code de l'espace, copie active) : l'espace de la page, sinon un espace où la personne a accès (le dernier
    utilisé d'abord), comme la connexion par mot de passe ; ou (None, None)."""
    from espaces import comptes as EC
    from referentiel.auth import copie_active

    with E.toutes_les_bases():
        u = copie_active(compte, E.declarer(code))
        if u is not None:
            return code, u
        codes = EC.codes_ouverts()
        for autre in ([compte.dernier_espace] if compte.dernier_espace in codes else []) + codes:
            u = copie_active(compte, E.declarer(autre))
            if u is not None:
                return autre, u
    return None, None


def _lier(compte, emetteur, sujet):
    """Lien du compte avec ce compte d'entreprise, relu sous verrou : "" si la connexion peut continuer, sinon la cause.
    Un compte déjà lié à un autre « sub » de ce fournisseur, ou ce « sub » déjà lié à un autre compte : refus."""
    from .models import LienEntreprise

    with transaction.atomic(using=E.COMMUN):
        lien = LienEntreprise.objects.select_for_update().filter(compte_id=compte.pk).first()
        if LienEntreprise.objects.filter(emetteur=emetteur, sujet=sujet).exclude(compte_id=compte.pk).exists():
            return "sub already linked to another account"
        maintenant = timezone.now()
        if lien is None:
            LienEntreprise.objects.create(compte_id=compte.pk, emetteur=emetteur, sujet=sujet, derniere_le=maintenant)
        elif lien.emetteur == emetteur and lien.sujet != sujet:
            return "account linked to another sub"
        else:  # même lien, ou lien d'un ancien fournisseur : remplacé
            lien.emetteur, lien.sujet, lien.derniere_le = emetteur, sujet, maintenant
            lien.save(update_fields=["emetteur", "sujet", "derniere_le"])
    return ""


def _nom(code):
    from espaces.models import Espace

    e = Espace.objects.filter(code=code).first()
    return e.nom if e else code


@never_cache
@require_GET
def retour(request):
    from espaces.models import Compte

    etat = request.GET.get("state", "")
    en_cours = request.session.get(CLE_FLUX) or {}  # lecture seule : ne crée aucune session
    attendue = en_cours.get(etat) if etat and isinstance(en_cours, dict) else None
    code = attendue.get("espace") if isinstance(attendue, dict) and attendue.get("espace") in E.codes_actifs() \
        else E.code_courant()
    r = regles.reglage()
    if not regles.active(r):  # éteinte (défaut) : rien n'est écrit ; le message seulement à qui avait commencé
        return _vers_connexion(request, code, "eteinte") if attendue is not None else redirect(E.url_espace(code, "login"))
    if _trop_de_refus(request):  # adresse bloquée : refusée avant tout, rien n'est écrit
        return _vers_connexion(request, code, "trop")
    f = _prendre_flux(request, etat)
    if f is None:
        return _sans_demande(request, code)
    if f.get("emetteur") != r.emetteur or f.get("client_id") != r.client_id:
        return refuser(request, code, "expiree", "settings changed during the sign-in")
    erreur = request.GET.get("error", "")
    if erreur:
        return refuser(request, code, "annulee" if erreur == "access_denied" else "technique", f"provider error {erreur[:40]}")
    code_fournisseur = request.GET.get("code", "")
    if not code_fournisseur or len(code_fournisseur) > 4096:
        return refuser(request, code, "technique", "no code")
    try:
        doc = oidc.decouvrir(r.emetteur)
        secret = dechiffrer(r.secret_chiffre)
        jeton = oidc.echanger_code(doc, r.client_id, secret, code_fournisseur, adresse_retour(request), f["verificateur"])
        claims = oidc.verifier_jeton(jeton, doc, r.client_id, f["nonce"])
    except oidc.ErreurOIDC as e:
        return refuser(request, code, "technique", e.code + (f" {e.detail}" if e.detail else ""))
    # authentifiée chez le fournisseur : les refus qui suivent comptent pour cette personne, jamais pour l'adresse
    personne = _cle_personne(doc["issuer"], claims["sub"])
    email = adresse_verifiee(claims, r)
    bloquee = _personne_bloquee(request, code, personne, email)
    if bloquee is not None:
        return bloquee
    if not email:
        return refuser(request, code, "adresse", "email missing or not verified", personne=personne)
    comptes = list(Compte.objects.filter(email__iexact=email).order_by("pk")[:2])
    if len(comptes) != 1:
        return refuser(request, code, "compte", "no account" if not comptes else "two accounts with this email", email,
                       personne=personne)
    compte = comptes[0]
    if not compte.actif:
        return refuser(request, code, "compte", "account blocked", email, personne=personne)
    code_session, u = _copie(compte, code)
    if u is None or not u.is_active:
        return refuser(request, code, "compte", "no active account in any space", email, personne=personne)
    probleme = _lier(compte, doc["issuer"], claims["sub"])
    if probleme:
        return refuser(request, code, "lien", probleme, email, personne=personne)
    CX.compteur().delete(personne)  # réussite : les refus de cette personne sont oubliés
    with E.toutes_les_bases():
        auth_login(request, u, backend=BACKEND)
    request.session[CLE_METHODE] = "entreprise"
    Compte.objects.filter(pk=compte.pk).update(dernier_espace=code_session)
    HC.noter("reussie", utilisateur=u, methode=HC.ENTREPRISE)
    if code_session != code:
        messages.info(request, libelle("cadre.connexion.entreprise.ailleurs", ici=_nom(code), la=_nom(code_session)))
        return redirect(E.url_espace(code_session))
    suivante = page_suivante_sure(request, f.get("suivante", ""))
    return redirect(suivante or E.url_espace(code_session))
