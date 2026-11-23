"""Connexion protégée contre les essais répétés : après ESSAIS_MAX échecs pour un même identifiant depuis une même
adresse (ou ESSAIS_MAX_ADRESSE échecs depuis une adresse, tous identifiants confondus, ou ESSAIS_MAX_COMPTE échecs sur
un même compte, toutes adresses confondues), la connexion est refusée pendant DUREE secondes, avec un message neutre
(il ne dit pas si le compte existe) et une ligne au journal du serveur.

Compteur par compte : il suit la personne du registre commun (même compte quel que soit
l'espace, l'e-mail ou l'identifiant tapé, la casse) ; un identifiant inconnu a son propre compteur, pour que le blocage
ne dise pas si le compte existe. Seuls les mots de passe vérifiés comptent (un envoi déjà refusé par une autre limite
ne pousse pas la personne vers un blocage partout), et une connexion réussie le remet à zéro. Contrepartie acceptée :
quelqu'un qui connaît l'identifiant d'une personne peut bloquer exprès sa connexion par mot de passe pendant DUREE
(une session déjà ouverte et les jetons d'assistant ne sont pas touchés).

Le compteur est gardé dans le cache « connexion » (``CACHES`` de config/settings.py : des fichiers dans le dossier des
données, partagés par tous les processus du serveur et gardés après un redémarrage ; avant, en mémoire de chaque
processus, la limite valait 5 essais par processus et repartait de zéro au redémarrage). Il vaut pour la page de
connexion de l'outil et pour celle du mode expert (/admin/)."""
import hashlib
import ipaddress
import logging

from django import forms
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.core.cache import caches
from django.dispatch import receiver

from parametres.libelles import libelle

ESSAIS_MAX = 5
ESSAIS_MAX_ADRESSE = 50
ESSAIS_MAX_COMPTE = 20
DUREE = 15 * 60

journal = logging.getLogger("referentiel.connexion")


def adresse(request):
    """Adresse du visiteur. Derrière un proxy (Caddy, hébergeur) qui se connecte depuis une adresse privée, c'est la
    dernière de X-Forwarded-For : celle que le proxy a ajoutée (les précédentes peuvent être forgées).

    L'en-tête n'est lu qu'avec DJANGO_HTTPS=1 (outil derrière un proxy HTTPS, seule installation avec proxy prévue) :
    sans proxy, sur le réseau de l'entreprise (adresses privées), chaque visiteur pourrait l'écrire lui-même et changer
    d'adresse à chaque essai, ce qui annulerait le blocage."""
    if request is None:
        return ""
    distante = request.META.get("REMOTE_ADDR", "")
    transmise = request.META.get("HTTP_X_FORWARDED_FOR", "") if getattr(settings, "HTTPS", False) else ""
    try:
        privee = ipaddress.ip_address(distante).is_private
    except ValueError:
        privee = False
    if transmise and privee:
        return transmise.split(",")[-1].strip()
    return distante


def _reseau(ip):
    """Adresse qui porte le compteur : une adresse IPv6 est ramenée à son réseau /64 (un abonné en a un entier : changer
    d'adresse à chaque essai dans ce réseau annulait le blocage)."""
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if a.version == 6 and a.ipv4_mapped is None:
        return str(ipaddress.ip_network(f"{a}/64", strict=False).network_address)
    return ip


def _cles(identifiant, request):
    ip = _reseau(adresse(request))
    empreinte = hashlib.sha256(f"{(identifiant or '').strip().lower()}|{ip}".encode()).hexdigest()
    return f"connexion:{empreinte}", f"connexion-adresse:{hashlib.sha256(ip.encode()).hexdigest()}"


def _cle_compte(identifiant):
    """Clé du compteur par compte, toutes adresses confondues : le numéro du compte au registre commun (même recherche
    que la connexion, ``auth.EmailOuIdentifiant`` : e-mail, identifiant exact, identifiant sans casse), donc la même
    personne dans tous les espaces ; un identifiant inconnu a sa propre clé (sans casse ni espaces autour), pour que le
    blocage ne dise pas si le compte existe."""
    from django.db import DatabaseError

    from espaces.models import Compte

    ident = (identifiant or "").strip()
    personne = None
    if ident:
        try:
            for filtre in ({"email__iexact": ident}, {"username": ident}, {"username__iexact": ident}):
                personne = Compte.objects.filter(**filtre).order_by("pk").values_list("pk", "date_joined").first()
                if personne is not None:
                    break
        except DatabaseError:  # registre illisible : le compteur par identifiant tapé garde la limite
            personne = None
    base = f"compte:{_personne(*personne)}" if personne is not None else f"identifiant:{ident.lower()}"
    return f"connexion-compte:{hashlib.sha256(base.encode()).hexdigest()}"


def _personne(numero, creation):
    """Repère stable d'une personne du registre commun : son numéro et sa date de création (un numéro seul pourrait être
    repris par un autre compte après une restauration, et l'est entre deux tests)."""
    return f"{numero}:{creation.isoformat() if creation else ''}"


def compteur():
    """Cache qui garde les essais manqués (``CACHES["connexion"]``)."""
    return caches["connexion"]


def _bloquee_compte(identifiant):
    return compteur().get(_cle_compte(identifiant), 0) >= ESSAIS_MAX_COMPTE


def bloquee(identifiant, request):
    cache = compteur()
    cle, cle_ip = _cles(identifiant, request)
    return (cache.get(cle, 0) >= ESSAIS_MAX or cache.get(cle_ip, 0) >= ESSAIS_MAX_ADRESSE
            or _bloquee_compte(identifiant))


def noter_echec(identifiant, request, compte=True):
    """Un échec de plus pour l'identifiant depuis cette adresse, pour l'adresse, et (``compte``) pour le compte, toutes
    adresses confondues : seulement quand le mot de passe a été vérifié (pas pour un envoi déjà refusé)."""
    cache = compteur()
    cle, cle_ip = _cles(identifiant, request)
    n = cache.get(cle, 0) + 1
    cache.set(cle, n, DUREE)  # 15 minutes après le dernier échec
    cache.set(cle_ip, cache.get(cle_ip, 0) + 1, DUREE)
    if n == ESSAIS_MAX:
        journal.warning("Sign-in blocked for %s min after %s failures: username \"%s\", address %s", DUREE // 60, n,
                        (identifiant or "")[:150], adresse(request))
    if compte:
        cle_compte = _cle_compte(identifiant)
        m = cache.get(cle_compte, 0) + 1
        cache.set(cle_compte, m, DUREE)
        if m == ESSAIS_MAX_COMPTE:
            journal.warning("Sign-in blocked for %s min after %s failures on one account from all addresses: username \"%s\"",
                            DUREE // 60, m, (identifiant or "")[:150])


def oublier(identifiant, request):
    compteur().delete_many([_cles(identifiant, request)[0], _cle_compte(identifiant)])


def premier_refus(identifiant, request, par_compte=False):
    """Vrai pour le premier refus d'une période de blocage (même identifiant et même adresse ; ou, ``par_compte``, même
    compte depuis toutes les adresses) : l'historique des connexions n'en garde qu'une ligne « bloquee », au lieu d'une
    par envoi (table et sauvegardes qui grossissaient sans borne). La marque est prolongée à chaque refus, comme le
    compteur des échecs : elle dure autant que le blocage."""
    cache = compteur()
    source = _cle_compte(identifiant) if par_compte else _cles(identifiant, request)[0]
    cle = "connexion-bloquee-notee:" + source.split(":", 1)[1]
    if cache.add(cle, 1, DUREE):
        return True
    cache.touch(cle, DUREE)
    return False


def noter_refus(identifiant, request):
    """Envoi refusé par la limite d'essais : prolonge le blocage, ligne « bloquee » au premier refus de la période."""
    par_compte = _bloquee_compte(identifiant)
    noter_echec(identifiant, request, compte=False)  # insister prolonge le blocage (identifiant et adresse, adresse)
    if par_compte:
        compteur().touch(_cle_compte(identifiant), DUREE)  # et celui du compte
    if premier_refus(identifiant, request, par_compte):
        from . import historique_connexions as HC

        HC.noter("bloquee", identifiant)


# ---------------------------------------------------------------- ancien mot de passe (Mon compte)
def _cle_mdp_actuel(utilisateur):
    """Essais manqués sur l'ancien mot de passe du changement de mot de passe : par personne (numéro du registre commun,
    le même dans tous les espaces), distincts de ceux de la connexion."""
    from espaces.models import Compte

    creation = Compte.objects.filter(pk=utilisateur.pk).values_list("date_joined", flat=True).first()
    return f"mdp-actuel:{_personne(utilisateur.pk, creation)}"


def mdp_actuel_bloque(utilisateur):
    """Vrai après ESSAIS_MAX échecs sur l'ancien mot de passe (même seuil que la connexion), pendant DUREE après le
    dernier : l'ancien mot de passe n'est plus vérifié (une session volée ne sert pas à le deviner)."""
    return compteur().get(_cle_mdp_actuel(utilisateur), 0) >= ESSAIS_MAX


def noter_echec_mdp_actuel(utilisateur):
    """Un échec de plus (ou un envoi refusé : insister prolonge l'attente, comme à la connexion)."""
    cache, cle = compteur(), _cle_mdp_actuel(utilisateur)
    n = cache.get(cle, 0) + 1
    cache.set(cle, n, DUREE)
    if n == ESSAIS_MAX:
        journal.warning("Password change blocked for %s min after %s wrong current passwords: account no. %s",
                        DUREE // 60, n, utilisateur.pk)


def oublier_mdp_actuel(utilisateur):
    compteur().delete(_cle_mdp_actuel(utilisateur))


@receiver(user_login_failed)
def _echec(sender, credentials, request=None, **kwargs):
    identifiant = credentials.get("username", "")
    if request is not None and bloquee(identifiant, request):  # refusé avant même la vérification du mot de passe
        noter_refus(identifiant, request)
        return
    noter_echec(identifiant, request)
    # historique des connexions (historique_connexions.py) : pas pour un bon mot de passe sans accès à cet espace sur la
    # page de l'outil (elle connecte alors la personne dans l'espace où elle a accès : c'est une réussite, notée là-bas) ;
    # le mode expert (/admin/) ne le fait pas : l'essai y reste un échec, noté ici
    vers_ailleurs = getattr(request, "espaces_connexion_ailleurs", None) and getattr(request, "connexion_par_l_outil", False)
    if request is not None and not vers_ailleurs:
        from . import historique_connexions as HC

        HC.noter("echec", identifiant)


@receiver(user_logged_in)
def _reussite(sender, request, user, **kwargs):
    if request is not None and request.method == "POST":
        oublier(request.POST.get("username", ""), request)
        # historique des connexions : une connexion par une page (pas une session ouverte par le code, comme les tests)
        from . import historique_connexions as HC

        HC.noter("reussie", utilisateur=user)
    # langue du compte gardée dans la session, commune à tous les espaces : chaque espace (page « pas d'accès »
    # comprise) s'ouvre dans la langue de la personne, même là où la copie de son compte ne la porte pas encore
    from parametres.langues import CLE_SESSION

    session = getattr(request, "session", None) if request is not None else None
    if session is not None and getattr(user, "langue", "") and not session.get(CLE_SESSION):
        session[CLE_SESSION] = user.langue


class FormulaireConnexion(AuthenticationForm):
    """Formulaire de la page Connexion : dit « Trop d'essais » quand la connexion est bloquée."""

    bloquee = False
    espace_ailleurs = None  # code de l'espace où la personne a accès, si ce n'est pas celui de cette page

    def clean(self):
        if bloquee(self.data.get("username", ""), self.request):
            self.bloquee = True
            noter_refus(self.data.get("username", ""), self.request)
            raise forms.ValidationError(libelle("cadre.connexion.bloquee"), code="trop_d_essais")
        if self.request is not None:
            self.request.connexion_par_l_outil = True  # cette page sait connecter dans l'espace où la personne a accès
        try:
            return super().clean()
        except forms.ValidationError:
            ailleurs = getattr(self.request, "espaces_connexion_ailleurs", None)
            if not ailleurs:
                raise
            # bon mot de passe, mais pas d'accès à cet espace : connexion dans un espace où la personne a accès
            code, u = ailleurs
            oublier(self.data.get("username", ""), self.request)
            self.confirm_login_allowed(u)
            self.user_cache, self.espace_ailleurs = u, code
            return self.cleaned_data
