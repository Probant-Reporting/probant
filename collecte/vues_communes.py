"""Aides partagées par les vues de ``collecte`` et de ``parametres`` : garde administrateur, campagne affichée,
identifiant envoyé par le navigateur, requête du script des pages, corps JSON, mémoire de session.

Noms publics : un module qui en a besoin les importe d'ici (jamais un nom ``_privé`` d'un autre module, test
``parametres/test_structure_imports.py``).
"""
import json

from django.core.exceptions import PermissionDenied, SuspiciousOperation
from django.http.request import RawPostDataException

from espaces.requetes import est_script  # noqa: F401  (réexporté : une seule détection du script pour tout l'outil)
from parametres.libelles import libelle
from referentiel.models import Referentiel

from . import saisie as S
from .models import Campagne


def exiger_admin(request, message="saisie.erreur.reserve_admin"):
    """Refus (403) à qui n'est pas administrateur ; ``message`` : clé du libellé du refus."""
    if not request.user.est_admin:
        raise PermissionDenied(libelle(message))


def est_identifiant(valeur):
    """Vrai pour un identifiant écrit en chiffres ASCII (« ² » ou « ١ » passent ``isdigit`` mais pas ``int`` : erreur 500)."""
    t = str(valeur or "")
    return t.isascii() and t.isdigit() and len(t) < 19


def identifiant(valeur):
    """Identifiant envoyé par le navigateur : l'entier, ou 0 (aucune ligne : 404) pour un texte forgé ou vide, au lieu d'une
    erreur 500."""
    return int(valeur) if est_identifiant(valeur) else 0


def corps_envoye(request):
    """Corps brut d'un envoi qui doit être du JSON ; ``None`` quand il n'est plus lisible : un formulaire « multipart »
    a déjà été lu par les gardes (formulaire, jeton CSRF) et ``request.body`` lèverait une erreur (500)."""
    try:
        return request.body
    except RawPostDataException:
        return None


def corps_json(request):
    """Corps JSON d'une requête de la page (glisser-déposer…) : un dictionnaire ; un corps forgé ou illisible donne une
    réponse 400 (requête invalide) au lieu d'une erreur 500."""
    corps = corps_envoye(request)
    if corps is None:
        raise SuspiciousOperation("corps JSON illisible (formulaire)")
    try:
        donnees = json.loads(corps or "{}")
    except (ValueError, RecursionError):  # RecursionError : imbrication démesurée ([[[[…]]]])
        donnees = None
    if not isinstance(donnees, dict):
        raise SuspiciousOperation("corps JSON invalide")
    return donnees


def memoriser_session(request, cle, valeur):
    """Garde ``valeur`` dans la session, sans l'écrire en base quand elle n'a pas changé (une page lue n'écrit rien :
    beaucoup de personnes en même temps ne se disputent pas la base des sessions)."""
    if request.session.get(cle) != valeur:
        request.session[cle] = valeur


def campagne_affichee(request, cle=None):
    """Campagne affichée (« Je réponds à » : référentiel et période) : celle demandée (paramètre « campagne » : son
    identifiant ; « ref » : code du référentiel, dont on prend alors la campagne en cours si la campagne demandée est
    d'un autre référentiel), sinon celle mémorisée dans la session, sinon la première campagne ouverte des référentiels
    de la personne. Un choix explicite devient aussi le référentiel mémorisé des pages d'administration."""
    explicite = bool(cle or request.GET.get("campagne") or request.GET.get("ref"))
    cle = cle or request.GET.get("campagne") or request.session.get("campagne")
    campagne = Campagne.objects.select_related("referentiel", "periode").filter(pk=cle).first() if est_identifiant(cle) else None
    ref = request.GET.get("ref", "")
    if ref and (campagne is None or campagne.referentiel_id != ref):
        r = Referentiel.objects.filter(pk=ref).first()
        campagne = (S.campagne_courante(r) if r else None) or campagne
    campagne = campagne or S.campagne_par_defaut(request.user)
    if campagne:
        memoriser_session(request, "campagne", campagne.pk)
        if explicite:
            memoriser_session(request, "referentiel", campagne.referentiel_id)
    return campagne
