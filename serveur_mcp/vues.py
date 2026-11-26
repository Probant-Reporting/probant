"""Pages du serveur MCP (docs/mcp.md) : le point d'entrée des assistants, Paramètres › Assistants (administrateur),
et la carte « Assistants » de Mon compte (jetons de la personne, ``collecte/compte.py``).

Le point d'entrée n'utilise ni session ni cookie : le jeton de l'en-tête ``Authorization`` désigne la personne, relue à
chaque requête (``jetons.authentifier``). Pas de jeton CSRF : sans cookie, une page tierce ne peut rien envoyer au nom de
quelqu'un ; un en-tête ``Origin`` d'un autre site est refusé (DNS rebinding)."""
import base64
import logging
import secrets
import threading
import time
from urllib.parse import urlsplit

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt

from collecte.models import Journal
from collecte.saisie import campagne_courante
from espaces import contexte as ESP
from parametres import langues as L
from parametres.libelles import libelle

from . import jetons as JT
from . import protocole as P
from .models import ReglageMCP

journal = logging.getLogger("serveur_mcp")


# ---------------------------------------------------------------- point d'entrée des assistants
def origine_permise(request):
    """Sans en-tête ``Origin`` (assistants, scripts) ou d'origine identique au site : permise."""
    origine = request.headers.get("Origin")
    if not origine:
        return True
    try:
        return urlsplit(origine).netloc.lower() == request.get_host().lower()
    except ValueError:
        return False


REFUS_INTERVALLE = 60  # secondes : au plus un avertissement par espace et par minute au journal du serveur
_refus = {}  # code de l'espace → (instant du dernier avertissement, refus tus depuis) ; propre à chaque processus
_refus_verrou = threading.Lock()


def noter_refus(code, cause):
    """Jeton refusé, noté au journal du serveur sans le jeton ; au plus une ligne par espace et par minute (un script
    qui envoie de mauvais jetons en boucle ne remplit pas le journal) : la ligne suivante dit combien ont été tus."""
    maintenant = time.monotonic()
    with _refus_verrou:
        dernier, tus = _refus.get(code, (None, 0))
        if dernier is not None and maintenant - dernier < REFUS_INTERVALLE:
            _refus[code] = (dernier, tus + 1)
            return
        _refus[code] = (maintenant, 0)
    journal.warning("MCP: token refused in space %s (%s)%s", code, cause,
                    f"; {tus} other refusal(s) not logged in the previous minute" if tus else "")


def refus_jeton():
    rep = P.erreur(None, P.SERVER_ERROR, libelle("mcp.refus.jeton"), {"reason": "invalid_token"}, http=401)
    rep["WWW-Authenticate"] = 'Bearer realm="probant", error="invalid_token"'
    return rep


@csrf_exempt
@never_cache
def point(request):
    """``POST /mcp/`` (``/espace/<code>/mcp/`` dans un autre espace) : une requête JSON-RPC, une réponse JSON."""
    if request.method != "POST":  # pas de flux d'événements (GET) ni de session à fermer (DELETE)
        rep = HttpResponse(status=405)
        rep["Allow"] = "POST"
        return rep
    if not origine_permise(request):
        return P.erreur(None, P.SERVER_ERROR, "Origin not allowed", {"reason": "origin"}, http=403)
    reglage = ReglageMCP.courant()
    if not reglage.actif:
        return P.erreur(None, P.SERVER_ERROR, libelle("mcp.refus.eteint"), {"reason": "mcp_disabled"}, http=403)
    try:
        utilisateur, jeton = JT.authentifier(JT.lire_entete(request.headers.get("Authorization")))
    except JT.JetonRefuse as e:
        noter_refus(ESP.code_courant(), e.cause)
        if e.entreprise:  # jeton valable, accès retiré par la connexion d'entreprise : 403, avec la raison
            return P.erreur(None, P.SERVER_ERROR, libelle("mcp.refus.entreprise"), {"reason": "company_sign_in"}, http=403)
        return refus_jeton()
    request.user = utilisateur
    with ESP.acteur(utilisateur.pk), L.pour(utilisateur):
        return P.repondre(request, utilisateur, jeton, reglage)


# ---------------------------------------------------------------- Mon compte › Assistants
def adresse(request):
    return request.build_absolute_uri(reverse("serveur_mcp:point"))


SESSION_NOUVEAU = "mcp_jeton_nouveau"
COOKIE_NOUVEAU = "probant_mcp_nouveau"
DUREE_NOUVEAU = 5 * 60  # secondes : le jeton créé n'est plus montré au-delà, même si la page suivante n'est jamais ouverte


def _maintenant():
    return time.time()


def _masque(octets, cle):
    return bytes(a ^ b for a, b in zip(octets, cle))


def action_jeton(request):
    """Envoi de la carte « Assistants » de Mon compte (``action`` : ``jeton_creer`` ou ``jeton_revoquer``). Renvoie une
    redirection, ou les erreurs du formulaire. Jeton créé : montré sur une seule page (``jeton_montre``), puis
    redirection : un rechargement ne crée pas un second jeton ; la page qui le montre n'est gardée par aucun cache (Mon
    compte : ``never_cache``). Le temps de la redirection, le jeton n'est jamais gardé en clair : la session garde le
    jeton masqué par une clé au hasard de même longueur (masque jetable), la clé va dans un cookie du navigateur qui
    expire après ``DUREE_NOUVEAU`` ; la session garde aussi l'heure, refusée au-delà de cette durée."""
    action = request.POST.get("action")
    if request.user.doit_changer_mdp:  # mot de passe provisoire : aucun jeton (il serait refusé de toute façon)
        return redirect("collecte:mon_compte")
    if action == "jeton_revoquer":
        j = JT.revoquer(request.user, request.POST.get("jeton"))
        if j is not None:
            messages.success(request, libelle("mcp.jetons.revoque", nom=j.nom))
        return redirect(reverse("collecte:mon_compte") + "#assistants")
    try:
        clair, j = JT.creer(request.user, request.POST.get("nom", ""), request.POST.get("jours"))
    except (ValidationError, PermissionDenied) as e:
        return {"mcp_erreur": " ".join(e.messages) if isinstance(e, ValidationError) else str(e), "mcp_nom": request.POST.get("nom", "")}
    octets = clair.encode("utf-8")
    cle = secrets.token_bytes(len(octets))
    request.session[SESSION_NOUVEAU] = {"id": j.pk, "utilisateur": request.user.pk, "le": _maintenant(),
                                        "masque": base64.urlsafe_b64encode(_masque(octets, cle)).decode("ascii")}
    page = reverse("collecte:mon_compte")
    rep = redirect(page + "#assistants")
    rep.set_cookie(COOKIE_NOUVEAU, base64.urlsafe_b64encode(cle).decode("ascii"), max_age=DUREE_NOUVEAU, path=page,
                   secure=request.is_secure(), httponly=True, samesite="Strict")
    return rep


def jeton_montre(request):
    """Jeton créé juste avant par cette personne (``action_jeton``), à montrer une seule fois : effacé de la session dès
    qu'il est lu. None s'il n'y en a pas, s'il est d'un autre compte, s'il date de plus de ``DUREE_NOUVEAU``, si le
    cookie de sa clé n'est plus là, ou s'il n'est plus utilisable."""
    e = request.session.pop(SESSION_NOUVEAU, None)
    if not isinstance(e, dict) or e.get("utilisateur") != request.user.pk:
        return None
    try:
        age = _maintenant() - float(e.get("le"))
        masque = base64.urlsafe_b64decode(e.get("masque") or "")
        cle = base64.urlsafe_b64decode(request.COOKIES.get(COOKIE_NOUVEAU) or "")
    except (TypeError, ValueError):
        return None
    if not 0 <= age <= DUREE_NOUVEAU or len(cle) != len(masque) or not masque:
        return None
    try:
        clair = _masque(masque, cle).decode("utf-8")
    except UnicodeDecodeError:
        return None
    j = JT.actifs(request.user).filter(pk=e.get("id")).first()
    if j is None or JT.empreinte(clair) != j.empreinte:
        return None
    return {"mcp_nouveau": {"jeton": clair, "objet": j, **configurations(adresse(request), clair)}}


def configurations(url, clair):
    """Configuration d'un assistant (docs/mcp.md, section 3) : commande de Claude Code ; fichier de Claude Desktop, qui
    passe par le pont « mcp-remote » (Node.js) pour un serveur distant avec un en-tête."""
    import json

    desktop = {"mcpServers": {"probant": {"command": "npx", "args": ["-y", "mcp-remote", url, "--header",
                                                                      f"Authorization:Bearer {clair}"]}}}
    return {"config_code": f'claude mcp add --transport http probant {url} --header "Authorization: Bearer {clair}"',
            "config_desktop": json.dumps(desktop, indent=2)}


def contexte_compte(request, plus=None):
    """Ce que montre la carte « Assistants » de Mon compte."""
    from connexion_entreprise import regles as RE

    reglage = ReglageMCP.courant()
    durees = JT.durees_proposees(reglage)
    return {"mcp": {"actif": reglage.actif, "ecriture": reglage.ecriture, "jetons": list(JT.actifs(request.user)),
                    "entreprise": reglage.actif and not RE.assistants_permis(request.user.pk),
                    "durees": durees, "duree_defaut": JT.duree_par_defaut(durees), "adresse": adresse(request),
                    "max": JT.JETONS_MAX, **(plus or {})}}


# ---------------------------------------------------------------- Paramètres › Assistants
class ReglageForm(forms.ModelForm):
    class Meta:
        model = ReglageMCP
        fields = ["actif", "ecriture", "lecteur_lit", "kpi_sensibles", "appels_minute", "duree_max_jours"]
        widgets = {"appels_minute": forms.NumberInput(attrs={"min": 1, "max": 600, "aria-describedby": "aide-appels"}),
                   "duree_max_jours": forms.NumberInput(attrs={"min": 1, "max": 365, "aria-describedby": "aide-duree"}),
                   "actif": forms.CheckboxInput(attrs={"aria-describedby": "aide-actif"}),
                   "ecriture": forms.CheckboxInput(attrs={"aria-describedby": "aide-ecriture"}),
                   "lecteur_lit": forms.CheckboxInput(attrs={"aria-describedby": "aide-lecteur-lit"}),
                   "kpi_sensibles": forms.CheckboxInput(attrs={"aria-describedby": "aide-kpi-sensibles"})}


@login_required
def reglages(request):
    """Administration › Paramètres › Assistants : permettre les assistants dans l'espace (éteint par défaut), leurs
    écritures, ce qu'ils reçoivent (lecteur, KPI sensibles), la limite de débit, la durée de vie maximale d'un jeton ; jetons actifs de l'espace (révocables). Chaque
    changement est noté dans le Journal."""
    if not request.user.est_admin:
        raise PermissionDenied(libelle("admin.reserve_admin"))
    reglage = ReglageMCP.courant()
    form = ReglageForm(instance=reglage)
    if request.method == "POST" and request.POST.get("action") == "revoquer":
        j = JT.revoquer(request.user, request.POST.get("jeton"), tous=True)
        if j is not None:
            messages.success(request, libelle("mcp.reglages.revoque", nom=j.nom, personne=j.utilisateur))
        return redirect(reverse("serveur_mcp:reglages") + "#jetons")
    if request.method == "POST":
        champs = ReglageForm.Meta.fields
        with ESP.atomic():
            reglage = ReglageMCP.objects.select_for_update().get(pk=reglage.pk)  # relu sous verrou avant d'écrire
            avant = {c: getattr(reglage, c) for c in champs}
            form = ReglageForm(request.POST, instance=reglage)
            if form.is_valid():
                form.save()
                for c, v in avant.items():
                    if getattr(reglage, c) != v:
                        Journal.ecrire(request.user, "reglage_mcp", reglage, f"mcp_{c}", v, getattr(reglage, c))
        if form.is_valid():
            messages.success(request, libelle("mcp.reglages.enregistre"))
            return redirect("serveur_mcp:reglages")
    jetons = list(JT.actifs().order_by("utilisateur__first_name", "utilisateur__last_name", "-cree_le"))
    return render(request, "serveur_mcp/reglages.html", {
        "page": "administration", "rubrique": "parametres", "sous_rubrique": "assistants", "form": form,
        "jetons": jetons, "adresse": adresse(request), "campagne": campagne_courante(),
    })
