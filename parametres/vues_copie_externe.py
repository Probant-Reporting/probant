"""Administration › Paramètres › Hébergement › Copie externe (``copie_externe.py``) : où l'outil copie les sauvegardes hors
du serveur. Réglage de l'INSTALLATION, au registre commun : page ouverte à l'administrateur de chaque espace (état de la
copie, en lecture seule ; la destination pour qui voit le détail de l'installation,
``sante_installation.detail_installation_permis``), formulaire et envois (essai compris : il joint l'adresse enregistrée)
seulement pour un gestionnaire des espaces (``espaces.comptes.est_gestionnaire``) : la destination reçoit les archives
de tous les espaces et du registre commun ; lecteur et auditeur : refusés comme toutes les pages des Paramètres.

- Les secrets ne sont jamais réaffichés : champs toujours vides, vide = garder ; « Effacer » : geste explicite.
- « Essayer la destination » : réglages ENREGISTRÉS, fichier témoin déposé, relu, supprimé ; limité (``ESSAIS_MAX``) ;
  cause en clair, jamais la réponse du service.
- SFTP : la clé du serveur montrée au premier essai est confirmée ici (empreinte renvoyée par la page et comparée à
  celle de la clé gardée), jamais acceptée sans ce geste.
- Chaque changement est noté au journal (``reglage_copie_externe``) sans la valeur de l'identifiant ni d'aucun secret.
"""
import re

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.functional import lazy
from django.views.decorators.debug import sensitive_post_parameters

from collecte.models import Journal
from collecte.saisie import campagne_courante

from . import copie_externe as CE
from .copie_reseau import ErreurCopie
from .envoi_emails import HOTE
from .libelles import libelle
from .models import Instance
from .views import exiger_admin_reglages

_l = lazy(libelle, str)
ACTION = "reglage_copie_externe"
ESSAI = "copie-essai"  # étiquette des messages montrés à côté du bouton « Essayer la destination »
PREFIXE = re.compile(r"^[A-Za-z0-9._/-]{0,200}$")
REGION = re.compile(r"^[A-Za-z0-9-]{0,60}$")
CONSERVER_MAX = 1000


def _sans_controle(texte):
    return not any(ord(c) < 32 or ord(c) == 127 for c in texte)


class _Base(forms.Form):
    identifiant = forms.CharField(max_length=254, label=_l("admin.copie.form.identifiant"),
                                  widget=forms.TextInput(attrs={"autocomplete": "off", "spellcheck": "false",
                                                                "autocapitalize": "none"}))
    secret = forms.CharField(required=False, strip=False, max_length=CE.SECRET_MAX, label=_l("admin.copie.form.secret_s3"),
                             widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password",
                                                                                  "aria-describedby": "aide-copie-secret"}))
    conserver = forms.IntegerField(min_value=0, max_value=CONSERVER_MAX, initial=0, label=_l("admin.copie.form.conserver"),
                                   error_messages={k: _l("admin.copie.erreur.conserver") for k in ("invalid", "min_value",
                                                                                                   "max_value", "required")},
                                   widget=forms.NumberInput(attrs={"min": 0, "max": CONSERVER_MAX, "inputmode": "numeric",
                                                                   "aria-describedby": "aide-copie-conserver"}))

    GENRE = ""

    def __init__(self, *args, secret_present=False, ligne=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.secret_present, self.ligne = secret_present, ligne

    def secret_garde(self, d):
        """Le secret enregistré sert-il encore ? Pas si la destination change : il est alors à saisir de nouveau
        (``copie_externe.destination_changee``) ; vrai : le secret manquant vient d'un changement de destination."""
        change = self.secret_present and CE.destination_changee(self.ligne, self.GENRE, d)
        return self.secret_present and not change, change

    def clean_identifiant(self):
        v = (self.cleaned_data.get("identifiant") or "").strip()
        if not _sans_controle(v):
            raise forms.ValidationError(libelle("admin.copie.erreur.caracteres"))
        return v

    def clean_secret(self):
        v = self.cleaned_data.get("secret") or ""
        if not _sans_controle(v):
            raise forms.ValidationError(libelle("admin.copie.erreur.caracteres"))
        return v

    def full_clean(self):
        """Champ refusé : son message (``erreur-copie-<champ>``) est relié au champ."""
        super().full_clean()
        for nom in self.errors:
            if nom in self.fields:
                aide = self.fields[nom].widget.attrs.get("aria-describedby", "")
                self.fields[nom].widget.attrs["aria-describedby"] = f"erreur-copie-{nom} {aide}".strip()
                self.fields[nom].widget.attrs["aria-invalid"] = "true"


class DestinationS3Form(_Base):
    GENRE = "s3"
    adresse = forms.CharField(max_length=300, label=_l("admin.copie.form.adresse"),
                              widget=forms.TextInput(attrs={"autocomplete": "off", "spellcheck": "false", "inputmode": "url",
                                                            "autocapitalize": "none", "aria-describedby": "aide-copie-adresse",
                                                            "placeholder": "https://"}))
    region = forms.CharField(required=False, max_length=60, label=_l("admin.copie.form.region"),
                             widget=forms.TextInput(attrs={"autocomplete": "off", "spellcheck": "false",
                                                           "autocapitalize": "none", "aria-describedby": "aide-copie-region"}))
    compartiment = forms.CharField(max_length=63, label=_l("admin.copie.form.compartiment"),
                                   widget=forms.TextInput(attrs={"autocomplete": "off", "spellcheck": "false",
                                                                 "autocapitalize": "none"}))
    chemin = forms.CharField(required=False, max_length=200, label=_l("admin.copie.form.prefixe"),
                             widget=forms.TextInput(attrs={"autocomplete": "off", "spellcheck": "false", "autocapitalize": "none",
                                                           "aria-describedby": "aide-copie-chemin"}))
    style = forms.ChoiceField(choices=[(s, s) for s in CE.STYLES], initial="auto", label=_l("admin.copie.form.style"),
                              widget=forms.Select(attrs={"aria-describedby": "aide-copie-style"}))
    field_order = ["adresse", "region", "compartiment", "chemin", "style", "identifiant", "secret", "conserver"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["style"].choices = [(s, libelle(f"admin.copie.style.{s}")) for s in CE.STYLES]
        self.fields["identifiant"].label = libelle("admin.copie.form.cle_acces")

    def clean_adresse(self):
        from .copie_s3 import verifier_adresse

        v = (self.cleaned_data.get("adresse") or "").strip()
        try:
            verifier_adresse(v)
        except ValueError:
            raise forms.ValidationError(libelle("admin.copie.erreur.adresse")) from None
        return v.rstrip("/")

    def clean_region(self):
        v = (self.cleaned_data.get("region") or "").strip()
        if not REGION.match(v):
            raise forms.ValidationError(libelle("admin.copie.erreur.region"))
        return v

    def clean_compartiment(self):
        from .copie_s3 import COMPARTIMENT

        v = (self.cleaned_data.get("compartiment") or "").strip()
        if not COMPARTIMENT.match(v) or ".." in v:
            raise forms.ValidationError(libelle("admin.copie.erreur.compartiment"))
        return v

    def clean_chemin(self):
        v = (self.cleaned_data.get("chemin") or "").strip().strip("/")
        if not PREFIXE.match(v) or any(p in ("", ".", "..") for p in v.split("/")) and v:
            raise forms.ValidationError(libelle("admin.copie.erreur.prefixe"))
        return v

    def clean(self):
        d = super().clean()
        garde, change = self.secret_garde(d)
        if not d.get("secret") and not garde and "secret" not in self.errors:
            self.add_error("secret", libelle("admin.copie.erreur.secret_s3_destination" if change else "admin.copie.erreur.secret_s3"))
        return d


class DestinationSFTPForm(_Base):
    GENRE = "sftp"
    hote = forms.CharField(max_length=253, label=_l("admin.copie.form.hote"),
                           widget=forms.TextInput(attrs={"autocomplete": "off", "spellcheck": "false", "autocapitalize": "none"}))
    port = forms.IntegerField(min_value=1, max_value=65535, initial=22, label=_l("admin.copie.form.port"),
                              error_messages={k: _l("admin.copie.erreur.port") for k in ("invalid", "min_value", "max_value",
                                                                                         "required")},
                              widget=forms.NumberInput(attrs={"min": 1, "max": 65535, "inputmode": "numeric"}))
    cle_privee = forms.CharField(required=False, strip=False, max_length=CE.CLE_PRIVEE_MAX, label=_l("admin.copie.form.cle_privee"),
                                 widget=forms.Textarea(attrs={"rows": 4, "autocomplete": "off", "spellcheck": "false",
                                                              "autocapitalize": "none", "aria-describedby": "aide-copie-cle"}))
    chemin = forms.CharField(required=False, max_length=300, label=_l("admin.copie.form.dossier"),
                             widget=forms.TextInput(attrs={"autocomplete": "off", "spellcheck": "false", "autocapitalize": "none",
                                                           "aria-describedby": "aide-copie-chemin"}))
    field_order = ["hote", "port", "identifiant", "secret", "cle_privee", "chemin", "conserver"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["secret"].label = libelle("admin.copie.form.mot_de_passe")
        self.fields["identifiant"].label = libelle("admin.copie.form.compte")

    def clean_hote(self):
        v = (self.cleaned_data.get("hote") or "").strip()
        if not HOTE.match(v):
            raise forms.ValidationError(libelle("admin.copie.erreur.hote"))
        return v

    def clean_chemin(self):
        v = (self.cleaned_data.get("chemin") or "").strip()
        if len(v) > 1:
            v = v.rstrip("/")
        if not _sans_controle(v) or ".." in v.split("/"):
            raise forms.ValidationError(libelle("admin.copie.erreur.dossier"))
        return v

    def clean_cle_privee(self):
        from .copie_sftp import lire_cle_privee

        v = (self.cleaned_data.get("cle_privee") or "").strip()
        if not v:
            return ""
        try:
            lire_cle_privee(v)
        except ErreurCopie as e:
            raise forms.ValidationError(libelle(f"admin.copie.cause.{e.code}")) from None
        return v + "\n"

    def clean(self):
        d = super().clean()
        garde, change = self.secret_garde(d)
        if d.get("secret") and d.get("cle_privee"):
            self.add_error("cle_privee", libelle("admin.copie.erreur.deux_secrets"))
        elif not d.get("secret") and not d.get("cle_privee") and not garde \
                and "secret" not in self.errors and "cle_privee" not in self.errors:
            self.add_error("secret", libelle("admin.copie.erreur.secret_sftp_destination" if change else "admin.copie.erreur.secret_sftp"))
        return d


FORMULAIRES = {"s3": DestinationS3Form, "sftp": DestinationSFTPForm}


def _formulaire(genre, d, donnees=None):
    r = CE.reglage(d)
    present = bool(d is not None and d.genre == genre and (r.secret or r.cle_privee) and not (r.secret_illisible or r.cle_privee_illisible))
    initial = {"conserver": 0, "style": "auto", "port": 22}
    if d is not None and d.genre == genre:
        initial.update({c: getattr(d, c) for c in CE.CHAMPS[genre]})
    return FORMULAIRES[genre](donnees, initial=initial, secret_present=present, ligne=d)


def _nom_compte(numero):
    if not numero:
        return ""
    from espaces.models import Compte

    c = Compte.objects.filter(pk=numero).first()
    return (f"{c.first_name} {c.last_name}".strip() or c.email) if c else ""


def _page(request):
    return reverse("parametres:copie_externe")


@login_required
@sensitive_post_parameters("secret", "cle_privee")
def copie_externe(request):
    from espaces.comptes import est_gestionnaire

    from .copie_sftp import empreinte
    from .sante_installation import detail_installation_permis

    exiger_admin_reglages(request)
    detail = detail_installation_permis(request.user)
    ecrire = est_gestionnaire(request.user)  # tout envoi : réglage, secrets, clé SFTP, essai (joint l'adresse), retrait
    disponible = CE.disponible()
    d = CE.ligne()
    essai = None
    form = None
    instance = Instance.courante()
    if request.method == "POST":
        if not ecrire:
            raise PermissionDenied(libelle("admin.copie.reserve"))
        action = request.POST.get("action")
        if not disponible:
            messages.error(request, libelle("admin.copie.indisponible"))
            return redirect(_page(request))
        if action == "enregistrer":
            genre = request.POST.get("genre")
            if genre not in CE.GENRES:
                return redirect(_page(request))
            form = _formulaire(genre, d, request.POST)
            if form.is_valid():
                c = form.cleaned_data
                valeurs = {k: c.get(k) for k in CE.CHAMPS[genre]}
                changements = CE.enregistrer(request.user, genre, valeurs, secret=c.get("secret") or "",
                                             cle_privee=c.get("cle_privee") or "")
                for champ, avant, apres in changements:
                    Journal.ecrire(request.user, ACTION, instance, champ, avant, apres)
                messages.success(request, libelle("admin.copie.enregistre"), extra_tags=ESSAI)
                return redirect(_page(request) + "#essai")
        elif action == "effacer_secrets":
            if CE.effacer_secrets(request.user):
                Journal.ecrire(request.user, ACTION, instance, "secret", "", "effacé")
            messages.success(request, libelle("admin.copie.secrets_effaces"))
            return redirect(_page(request) + "#destination")
        elif action == "retirer":
            if CE.retirer(request.user):
                Journal.ecrire(request.user, ACTION, instance, "genre", d.genre if d else "", "")
            messages.success(request, libelle("admin.copie.retiree"))
            return redirect(_page(request))
        elif action == "confirmer_cle":
            vue = CE.confirmer_cle(request.user, request.POST.get("empreinte", ""))
            if vue:
                Journal.ecrire(request.user, ACTION, instance, "cle_serveur", "", vue)
                messages.success(request, libelle("admin.copie.cle_confirmee", empreinte=vue), extra_tags=ESSAI)
                return redirect(_page(request) + "#essai")
            messages.error(request, libelle("admin.copie.cle_perimee"), extra_tags=ESSAI)
            return redirect(_page(request) + "#essai")
        elif action == "essayer":
            attente = CE.reserver_essai()
            if attente is not None:
                messages.error(request, libelle("admin.copie.essai.attendre", n=attente), extra_tags=ESSAI)
                return redirect(_page(request) + "#essai")
            essai = CE.essayer(d)
            Journal.ecrire(request.user, "essai_copie_externe", instance, "resultat", "", essai["cause"] or "ok")
            d = CE.ligne()
        else:
            return redirect(_page(request))
    r = CE.reglage(d)
    genre = request.GET.get("type", "") if request.GET.get("type", "") in CE.GENRES else (d.genre if d is not None else "")
    if form is None and ecrire and disponible and genre:
        form = _formulaire(genre, d)
    if essai is not None:
        essai["message"] = libelle(f"admin.copie.cause.{essai['cause']}", delai=CE.DELAI_ESSAI) if essai["cause"] else ""
        essai["empreinte"] = empreinte(essai["cle"]) if essai["cle"] else ""
    proposee = d.cle_proposee if d is not None and d.genre == "sftp" else ""
    tous = list(messages.get_messages(request))
    messages_essai = [m for m in tous if ESSAI in m.extra_tags.split()] if ecrire else []
    return render(request, "parametres/copie_externe.html", {
        "page": "administration", "rubrique": "parametres", "sous_rubrique": "hebergement", "campagne": campagne_courante(),
        "disponible": disponible, "detail": detail, "ecrire": ecrire, "d": d if detail else None, "r": r, "genre": genre, "form": form,
        "etat": CE.resume_etat() if disponible else {"etat": "absente"}, "essai": essai,
        "cause_echec": libelle(f"admin.copie.cause.{CE.etat().echec}", delai=CE.DELAI_COPIE) if CE.etat().echec else "",
        "cle_serveur": {"type": d.cle_serveur.split(" ", 1)[0], "empreinte": empreinte(d.cle_serveur),
                        "le": d.cle_serveur_le, "par": _nom_compte(d.cle_serveur_par)} if detail and d and d.cle_serveur else None,
        "cle_proposee": {"type": proposee.split(" ", 1)[0], "empreinte": empreinte(proposee), "le": d.cle_proposee_le}
        if ecrire and proposee else None,
        "modifie_par": _nom_compte(d.modifie_par) if detail and d else "",
        "messages_essai": messages_essai, "messages_haut": [m for m in tous if m not in messages_essai],
        "essais_max": CE.ESSAIS_MAX, "essais_minutes": int(CE.ESSAIS_FENETRE.total_seconds() // 60),
    })
