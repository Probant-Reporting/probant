"""Hébergement : page de santé (supervision) et Administration › Paramètres › Hébergement (version, sauvegardes à
télécharger, serveur d'envoi des e-mails avec test d'envoi : ``envoi_emails.py``)."""
import datetime
import os
import platform
import re
import logging
import shutil
from pathlib import Path
from urllib.parse import urlencode

import django
from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.mail import EmailMessage
from django.core.serializers.base import DeserializationError
from django.db import DatabaseError, connections
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.functional import lazy
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters

from collecte import dates_courtes as DC
from collecte.models import Journal
from espaces import contexte as ESP
from collecte.saisie import campagne_courante

from . import envoi_emails as EE
from . import sauvegardes as SV
from . import libelles as LB
from .libelles import libelle
from .models import Instance
from .views import exiger_admin_reglages

_l = lazy(libelle, str)  # libellé évalué à l'affichage (champs de formulaire définis à l'import)
journal = logging.getLogger("reporting.emails")
EMAILS = "emails"  # étiquette des messages montrés dans l'encart « E-mails »


@never_cache
def sante(request):
    """État pour la supervision (sans connexion, sans donnée sensible) : 200 si la base répond et que le dossier des
    données est modifiable, 503 sinon ; aussi 503 si une base est abîmée (contrôle d'intégrité du démarrage ou d'une
    sauvegarde), si une restauration a été interrompue, ou si le disque est presque plein (``etat`` : « erreur »,
    ``alerte`` : la cause, en anglais, pour l'IT). Le contrôle de cohérence des données (``controle_donnees``) ne fait
    jamais passer en 503 : un contrôle en retard ou des problèmes trouvés se lisent dans le détail (« late »,
    « problems ») et dans l'outil (Hébergement, « À traiter »). De même pour un import en arrière-plan bloqué
    (« background_imports », « avertissement »), et pour un gros export bloqué (« background_exports »).

    Qui reçoit quoi : le détail de toute l'installation (version, base, stockage, dernière
    sauvegarde, tâches de fond de tous les espaces, chemins du disque) à l'appel local sans proxy (contrôle de santé de
    Docker, install.sh) et à qui voit le détail de l'installation (``sante_installation.detail_installation_permis`` :
    administrateur de l'espace principal, gestionnaire des espaces) ; l'administrateur d'un autre espace reçoit l'état de
    son espace seulement (registre commun et disque compris, sans le nom des autres espaces ni les chemins du disque) ;
    les autres, l'état seul (la version exacte aiderait à repérer une installation pas à jour)."""
    from .sante_installation import detail_installation_permis

    u = getattr(request, "user", None)
    if _appel_local(request) or detail_installation_permis(u):
        etat = mesurer_sante()["etat"]
    elif u is not None and u.is_authenticated and getattr(u, "est_admin", False):
        etat = mesurer_sante([ESP.code_courant()], chemins=False)["etat"]
    else:
        etat = {"etat": mesurer_sante()["etat"]["etat"]}
    return JsonResponse(etat, status=200 if etat["etat"] == "ok" else 503, json_dumps_params={"ensure_ascii": False})


def mesurer_sante(codes=None, chemins=True):
    """Ce que /sante/ mesure, dans une seule écriture lue aussi par la page « Santé de l'installation »
    (``sante_installation.py``) : {"etat": détail de /sante/, "codes": espaces mesurés, "alertes": [(genre, code,
    message)]}. ``codes`` : les espaces à mesurer (par défaut tous les espaces actifs) ; le registre commun et le disque
    sont toujours mesurés. ``chemins`` : faux pour taire les chemins du disque dans les messages (administrateur d'un
    espace secondaire)."""
    etat = {"etat": "ok", "version": settings.VERSION}
    etat["base"], etat["stockage"], tous = _sante_bases(codes)
    codes = tous if codes is None else [c for c in tous if c in codes]
    structurees = alertes_structurees(codes, chemins)
    alertes = [m for _, _, m in structurees]
    if etat["base"] != "ok" or etat["stockage"] != "ok" or alertes:
        etat["etat"] = "erreur"
    try:
        derniere = SV.archives()[:1]
    except OSError:
        derniere = []
    etat["derniere_sauvegarde"] = derniere[0].date.isoformat() if derniere else None
    if derniere and derniere[0].date > timezone.localtime() + datetime.timedelta(days=1):
        etat["avertissement"] = "last backup dated in the future: check the server clock"
    if alertes:
        etat["alerte"] = "; ".join(alertes)

    # contrôle de cohérence de la base (nuit) : dit seulement, jamais en 503 (voir docs/installation.md, Monitoring)
    from collecte import controle_donnees as CD

    etat["controle_donnees"] = CD.pour_sante()
    # imports en arrière-plan : une tâche bloquée (ni planificateur ni serveur web ne la traite) est dite, jamais en 503
    from collecte import imports_arriere_plan as AP

    etat["background_imports"] = AP.pour_sante(codes)
    # gros exports en arrière-plan : même signalement
    from collecte import exports_arriere_plan as EAP

    etat["background_exports"] = EAP.pour_sante(codes)
    # copie externe des sauvegardes (copie_externe.py) : dite, jamais en 503 (la sauvegarde sur le serveur reste là)
    from . import copie_externe as CE

    etat["external_copy"] = CE.pour_sante()
    messages = [etat[c]["message"] for c in ("background_imports", "background_exports", "external_copy") if etat[c].get("message")]
    if messages:
        etat["avertissement"] = "; ".join(filter(None, [etat.get("avertissement"), *messages]))
    return {"etat": etat, "codes": codes, "alertes": structurees}


def _sante_alertes(codes):
    """Défauts notés hors de la base : base abîmée, restauration interrompue (par espace), disque presque plein."""
    return [m for _, _, m in alertes_structurees(codes)]


def espace_disque():
    """(octets libres, dossier) : le plus petit espace libre des dossiers des données, des fichiers et des sauvegardes de
    l'espace principal (ils peuvent être sur des disques différents) ; None si aucun ne se lit."""
    mesures = []
    for d in sorted({Path(settings.DOSSIER_DONNEES), ESP.dossier_medias(ESP.PRINCIPAL), ESP.dossier_sauvegardes(ESP.PRINCIPAL)}):
        try:
            mesures.append((shutil.disk_usage(d).free, d))
        except OSError:
            continue
    return min(mesures, key=lambda m: m[0]) if mesures else None


def alertes_structurees(codes, chemins=True):
    """[(genre, code de l'espace ou "", message en anglais pour l'IT)] : « base_abimee », « restauration » (par espace),
    « disque » (disque presque plein)."""
    alertes = []
    for code in codes:
        nom = "" if code == ESP.PRINCIPAL else f" (space {code})"
        try:
            if SV.base_abimee(code):
                alertes.append(("base_abimee", code, f"damaged database{nom}: restore the last good backup"))
            if SV.restauration_en_cours(code):
                alertes.append(("restauration", code,
                                f"interrupted restore{nom}: finished automatically within a minute, or at the next start"))
        except (OSError, ValueError):
            continue
    disque = espace_disque()
    if disque is not None and disque[0] < settings.ALERTE_DISQUE_MO * 1024 * 1024:
        ou = f" in {disque[1]}" if chemins else ""
        alertes.append(("disque", "", f"disk almost full: {disque[0] // (1024 * 1024)} MB free{ou}"))
    return alertes


def _refus_espace(d):
    try:
        SV.controler_espace(d)
    except SV.ErreurSauvegarde as e:
        return str(e)
    return ""


def _nom_espace(code):
    from espaces.models import Espace

    e = Espace.objects.filter(code=code).first()
    return e.nom if e else code


def _sante_bases(seulement=None):
    """(base, stockage, codes des espaces) : « ok » si le registre commun et la base de chaque espace actif répondent
    (le schéma se lit), et si le dossier des fichiers de chaque espace est modifiable ; sinon le premier défaut (avec
    l'espace en cause). ``seulement`` : les codes des espaces à vérifier (par défaut tous les espaces actifs)."""
    base, stockage = "ok", "ok"
    try:
        with ESP.toutes_les_bases():
            with connections[ESP.COMMUN].cursor() as c:
                c.execute("SELECT 1")
            codes = ESP.codes_actifs()
    except Exception:
        return "unreachable (shared registry)", "ok", [ESP.PRINCIPAL]
    for code in codes if seulement is None else [c for c in codes if c in seulement]:
        with ESP.toutes_les_bases():
            try:
                with connections[ESP.declarer(code)].cursor() as c:
                    c.execute("SELECT 1")
                    if connections[ESP.declarer(code)].vendor == "sqlite":  # en-tête du fichier lisible
                        c.execute("SELECT count(*) FROM sqlite_master")
            except Exception:
                base = "unreachable" if code == ESP.PRINCIPAL else f"unreachable (space {code})"
        media = ESP.dossier_medias(code)
        if not ((media.is_dir() and os.access(media, os.W_OK)) or (not media.exists() and os.access(media.parent, os.W_OK))):
            stockage = "not writable" if code == ESP.PRINCIPAL else f"not writable (space {code})"
    if not os.access(settings.DOSSIER_DONNEES, os.W_OK):
        stockage = "not writable (data folder)"
    return base, stockage, codes


def _appel_local(request):
    """Appel depuis la machine elle-même sans passer par un proxy : aucun des en-têtes qu'un proxy ajoute
    (X-Forwarded-For, X-Real-IP, Forwarded). Un proxy local qui n'en poserait qu'un (nginx : X-Real-IP seul) donnerait
    sinon le détail à Internet."""
    return (request.META.get("REMOTE_ADDR") in ("127.0.0.1", "::1")
            and not any(request.META.get(h) for h in EN_TETES_PROXY))


EN_TETES_PROXY = ("HTTP_X_FORWARDED_FOR", "HTTP_X_REAL_IP", "HTTP_FORWARDED")


class TestEmailForm(forms.Form):
    destinataire = forms.EmailField(label=_l("admin.hebergement.form.destinataire"),
                                    error_messages={"invalid": _l("admin.compte.email_invalide")})


class ServeurEnvoiForm(forms.Form):
    """Serveur d'envoi des e-mails réglé dans l'outil (``envoi_emails``). Le mot de passe n'est jamais réaffiché : champ
    toujours vide, vide à l'enregistrement = garder celui qui est enregistré. Serveur vide : l'outil n'envoie plus rien."""

    hote = forms.CharField(required=False, max_length=253, label=_l("admin.hebergement.smtp.form.hote"),
                           widget=forms.TextInput(attrs={"autocomplete": "off", "spellcheck": "false", "autocapitalize": "none",
                                                         "aria-describedby": "aide-smtp-hote"}))
    port = forms.IntegerField(required=False, min_value=1, max_value=65535, label=_l("admin.hebergement.smtp.form.port"),
                              error_messages={"invalid": _l("admin.hebergement.smtp.erreur.port"),
                                              "min_value": _l("admin.hebergement.smtp.erreur.port"),
                                              "max_value": _l("admin.hebergement.smtp.erreur.port")},
                              widget=forms.NumberInput(attrs={"min": 1, "max": 65535, "inputmode": "numeric"}))
    securite = forms.ChoiceField(label=_l("admin.hebergement.smtp.form.securite"), choices=[(s, s) for s in EE.SECURITES],
                                 widget=forms.Select(attrs={"aria-describedby": "aide-smtp-securite"}))
    identifiant = forms.CharField(required=False, max_length=254, label=_l("admin.hebergement.smtp.form.identifiant"),
                                  widget=forms.TextInput(attrs={"autocomplete": "off", "spellcheck": "false", "autocapitalize": "none"}))
    mot_de_passe = forms.CharField(required=False, strip=False, max_length=EE.MOT_DE_PASSE_MAX,
                                   label=_l("admin.hebergement.smtp.form.mot_de_passe"),
                                   widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password",
                                                                                        "aria-describedby": "aide-smtp-mdp"}))
    expediteur = forms.EmailField(required=False, max_length=254, label=_l("admin.hebergement.smtp.form.expediteur"),
                                  error_messages={"invalid": _l("admin.compte.email_invalide")},
                                  widget=forms.EmailInput(attrs={"autocomplete": "off", "spellcheck": "false"}))
    # sécurité « Aucune » avec un mot de passe (saisi ou déjà enregistré) : il partirait en clair ; confirmation explicite
    en_clair = forms.BooleanField(required=False, label=_l("admin.hebergement.smtp.form.en_clair"),
                                  widget=forms.CheckboxInput(attrs={"aria-describedby": "aide-smtp-en-clair"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["securite"].choices = [(s, libelle(f"admin.hebergement.smtp.securite.{s}")) for s in EE.SECURITES]
        s = EE.ligne()
        self.ligne = s
        self.mot_de_passe_enregistre = bool(s and s.mot_de_passe_chiffre)
        # la case n'est montrée que là où elle sert : réglage en vigueur déjà « Aucune » avec un mot de passe, ou envoi refusé
        self.demander_en_clair = bool(s and s.securite == "none" and s.mot_de_passe_chiffre)

    def clean_hote(self):
        h = (self.cleaned_data.get("hote") or "").strip()
        if h and not EE.HOTE.match(h):
            raise forms.ValidationError(libelle("admin.hebergement.smtp.erreur.hote"))
        return h

    def clean_identifiant(self):
        v = (self.cleaned_data.get("identifiant") or "").strip()
        if any(ord(c) < 32 or ord(c) == 127 for c in v):
            raise forms.ValidationError(libelle("admin.hebergement.smtp.erreur.caracteres"))
        return v

    def clean_mot_de_passe(self):
        v = self.cleaned_data.get("mot_de_passe") or ""
        if any(c in v for c in "\r\n\x00"):  # ni retour à la ligne ni caractère nul : jamais injecté dans l'échange SMTP
            raise forms.ValidationError(libelle("admin.hebergement.smtp.erreur.caracteres"))
        return v

    def full_clean(self):
        """Champ refusé : son message (``erreur-smtp-<champ>``) est relié au champ."""
        super().full_clean()
        for nom in self.errors:
            if nom in self.fields:
                aide = self.fields[nom].widget.attrs.get("aria-describedby", "")
                self.fields[nom].widget.attrs["aria-describedby"] = f"erreur-smtp-{nom} {aide}".strip()

    def clean(self):
        d = super().clean()
        if d.get("hote"):
            if not d.get("port") and "port" not in self.errors:
                self.add_error("port", libelle("admin.hebergement.smtp.erreur.port"))
            if not d.get("expediteur") and "expediteur" not in self.errors:
                self.add_error("expediteur", libelle("admin.hebergement.smtp.erreur.expediteur"))
            # le mot de passe enregistré ne compte que s'il est gardé : une autre destination l'efface (envoi_emails)
            garde = self.mot_de_passe_enregistre and not EE.destination_changee(
                self.ligne, d.get("hote"), d.get("port") or 587, d.get("securite"), d.get("identifiant") or "")
            if d.get("securite") == "none" and (d.get("mot_de_passe") or garde) and not d.get("en_clair"):
                self.demander_en_clair = True
                self.add_error("securite", libelle("admin.hebergement.smtp.erreur.en_clair"))
        return d


def _form_serveur(donnees=None):
    s = EE.ligne()
    initial = {c: getattr(s, c) for c in EE.CHAMPS} if s else {"port": 587, "securite": "starttls"}
    return ServeurEnvoiForm(donnees, initial=initial)


class ReglagesSauvegardeForm(forms.ModelForm):
    class Meta:
        model = Instance
        fields = ["sauvegarde_auto", "sauvegarde_frequence", "sauvegarde_heure", "sauvegarde_conserver"]
        widgets = {"sauvegarde_heure": forms.TimeInput(attrs={"type": "time"}, format="%H:%M")}
        labels = {"sauvegarde_auto": _l("admin.hebergement.activee"), "sauvegarde_frequence": _l("admin.hebergement.frequence"),
                  "sauvegarde_heure": _l("admin.hebergement.heure"), "sauvegarde_conserver": _l("admin.hebergement.nombre")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        LB.traduire_choix(self)  # fréquences dans la langue de l'interface
        # même plage que ``clean_sauvegarde_conserver`` : le champ ne propose pas 0 (le modèle, lui, accepte 0)
        self.fields["sauvegarde_conserver"].widget.attrs.update({"min": 1, "max": 365, "inputmode": "numeric"})

    def clean_sauvegarde_heure(self):
        h = (self.cleaned_data.get("sauvegarde_heure") or "").strip()[:5]
        try:
            hh, mm = (int(x) for x in h.split(":"))
            assert 0 <= hh < 24 and 0 <= mm < 60
        except (ValueError, AssertionError):
            raise forms.ValidationError(libelle("admin.hebergement.erreur.heure"))
        return f"{hh:02d}:{mm:02d}"

    def clean_sauvegarde_conserver(self):
        n = self.cleaned_data.get("sauvegarde_conserver") or 0
        if not 1 <= n <= 365:
            raise forms.ValidationError(libelle("admin.hebergement.erreur.nombre"))
        return n


class ReglageCorbeilleForm(forms.ModelForm):
    """Délai de la corbeille (collecte/corbeille.py) : nombre de jours pendant lesquels un objet supprimé reste
    restaurable, de 1 à 365 ; la purge et la limite de restauration le lisent. Un seul message d'erreur, dans la langue
    de la personne, quelle que soit la saisie (vide, hors plage, pas un nombre)."""

    corbeille_jours = forms.IntegerField(
        label=_l("admin.hebergement.corbeille.jours"),
        error_messages={"invalid": _l("admin.hebergement.corbeille.erreur"), "required": _l("admin.hebergement.corbeille.erreur")},
        widget=forms.NumberInput(attrs={"min": 1, "max": 365, "inputmode": "numeric", "aria-describedby": "aide-corbeille"}))

    class Meta:
        model = Instance
        fields = ["corbeille_jours"]

    def clean_corbeille_jours(self):
        n = self.cleaned_data.get("corbeille_jours") or 0
        if not 1 <= n <= 365:
            raise forms.ValidationError(libelle("admin.hebergement.corbeille.erreur"))
        return n


class ReglageConnexionsForm(forms.ModelForm):
    """Durée de l'historique des connexions (referentiel/historique_connexions.py), en jours de 1 à 730 ; le ménage de
    la nuit efface les connexions plus anciennes, les pages ne les montrent plus. Un seul message d'erreur."""

    connexions_jours = forms.IntegerField(
        label=_l("admin.hebergement.connexions.jours"),
        error_messages={"invalid": _l("admin.hebergement.connexions.erreur"), "required": _l("admin.hebergement.connexions.erreur")},
        widget=forms.NumberInput(attrs={"min": 1, "max": 730, "inputmode": "numeric", "aria-describedby": "aide-connexions"}))

    class Meta:
        model = Instance
        fields = ["connexions_jours"]

    def clean_connexions_jours(self):
        n = self.cleaned_data.get("connexions_jours") or 0
        if not 1 <= n <= 730:
            raise forms.ValidationError(libelle("admin.hebergement.connexions.erreur"))
        return n


class ReglageConservationForm(forms.ModelForm):
    """Durée de conservation des preuves des KPI sensibles (collecte/conservation.py), en mois de 1 à 240 ; vide : pas de
    durée, aucune preuve n'est proposée à la suppression. Un seul message d'erreur, quelle que soit la saisie."""

    preuves_sensibles_mois = forms.IntegerField(
        required=False, label=_l("admin.hebergement.conservation.mois"),
        error_messages={"invalid": _l("admin.hebergement.conservation.erreur")},
        widget=forms.NumberInput(attrs={"min": 1, "max": 240, "inputmode": "numeric", "aria-describedby": "aide-conservation"}))

    class Meta:
        model = Instance
        fields = ["preuves_sensibles_mois"]

    def clean_preuves_sensibles_mois(self):
        n = self.cleaned_data.get("preuves_sensibles_mois")
        if n is not None and not 1 <= n <= 240:
            raise forms.ValidationError(libelle("admin.hebergement.conservation.erreur"))
        return n


class ReglageExportsFondForm(forms.ModelForm):
    """Gros exports en arrière-plan (collecte/exports_arriere_plan.py) : seuil en cellules (0 : jamais, jusqu'à
    100 000 000) et jours de conservation du fichier (1 à 30). Un message d'erreur par champ, quelle que soit la saisie."""

    exports_fond_cellules = forms.IntegerField(
        label=_l("admin.hebergement.exports_fond.seuil"),
        error_messages={"invalid": _l("admin.hebergement.exports_fond.erreur_seuil"),
                        "required": _l("admin.hebergement.exports_fond.erreur_seuil")},
        widget=forms.NumberInput(attrs={"min": 0, "max": 100_000_000, "inputmode": "numeric",
                                        "aria-describedby": "aide-exports-fond"}))
    exports_fond_jours = forms.IntegerField(
        label=_l("admin.hebergement.exports_fond.jours"),
        error_messages={"invalid": _l("admin.hebergement.exports_fond.erreur_jours"),
                        "required": _l("admin.hebergement.exports_fond.erreur_jours")},
        widget=forms.NumberInput(attrs={"min": 1, "max": 30, "inputmode": "numeric", "aria-describedby": "aide-exports-fond"}))

    class Meta:
        model = Instance
        fields = ["exports_fond_cellules", "exports_fond_jours"]

    def full_clean(self):
        """Champ refusé : son message (``erreur-<champ>``, sous le champ) est relié au champ avant l'aide (seconde recette,
        B7) ; Django marque déjà le champ ``aria-invalid``."""
        super().full_clean()
        for nom in self.errors:
            if nom in self.fields:
                self.fields[nom].widget.attrs["aria-describedby"] = f"erreur-{nom} aide-exports-fond"

    def clean_exports_fond_cellules(self):
        n = self.cleaned_data.get("exports_fond_cellules")
        if n is None or not 0 <= n <= 100_000_000:
            raise forms.ValidationError(libelle("admin.hebergement.exports_fond.erreur_seuil"))
        return n

    def clean_exports_fond_jours(self):
        n = self.cleaned_data.get("exports_fond_jours")
        if n is None or not 1 <= n <= 30:
            raise forms.ValidationError(libelle("admin.hebergement.exports_fond.erreur_jours"))
        return n


CONTENU = [  # ce qu'une sauvegarde contient, pour la page (clés de libellé)
    "admin.hebergement.contenu.comptes", "admin.hebergement.contenu.identite", "admin.hebergement.contenu.reglages",
    "admin.hebergement.contenu.organisations", "admin.hebergement.contenu.referentiels", "admin.hebergement.contenu.valeurs",
    "admin.hebergement.contenu.preuves", "admin.hebergement.contenu.journal",
]
HORS_CONTENU = ["admin.hebergement.hors_contenu.programme", "admin.hebergement.hors_contenu.serveur"]


class AlertesForm(forms.Form):
    """Alertes par e-mail de la santé de l'installation (``alertes.py``) : un réglage pour toute l'installation."""

    actives = forms.BooleanField(required=False, label=_l("admin.alertes.form.actives"))
    aux_comptes = forms.BooleanField(required=False, label=_l("admin.alertes.form.aux_comptes"))
    adresses = forms.CharField(required=False, max_length=5000, label=_l("admin.alertes.form.adresses"),
                               widget=forms.Textarea(attrs={"rows": 3, "autocomplete": "off", "spellcheck": "false",
                                                            "autocapitalize": "none", "aria-describedby": "aide-alertes-adresses"}))

    def clean_adresses(self):
        from . import alertes as AL

        bonnes, refusees = AL.lire_adresses(self.cleaned_data.get("adresses"))
        if refusees:
            raise forms.ValidationError(libelle("admin.alertes.erreur.adresses", liste=", ".join(refusees[:5])))
        if len(bonnes) > AL.ADRESSES_MAX:
            raise forms.ValidationError(libelle("admin.alertes.erreur.trop", n=AL.ADRESSES_MAX))
        return "\n".join(bonnes)

    def clean(self):
        d = super().clean()
        if d.get("actives") and not d.get("aux_comptes") and not d.get("adresses") and "adresses" not in self.errors:
            self.add_error("adresses", libelle("admin.alertes.erreur.aucun"))
        return d

    def full_clean(self):
        """Champ refusé : son message (``erreur-alertes-<champ>``) est relié au champ avant l'aide."""
        super().full_clean()
        for nom in self.errors:
            if nom in self.fields:
                aide = self.fields[nom].widget.attrs.get("aria-describedby", "")
                self.fields[nom].widget.attrs["aria-describedby"] = f"erreur-alertes-{nom} {aide}".strip()


ALERTES = "alertes"  # étiquette des messages montrés dans le bloc « Alertes par e-mail » de la page Santé


class MiseAJourAutoForm(forms.Form):
    """Mise à jour automatique (``mise_a_jour_auto.py``) : choix de l'administrateur, écrit dans le dossier des données pour
    la tâche de la machine. Valeurs d'une liste fermée seulement."""

    mode = forms.ChoiceField(label=_l("admin.maj_auto.form.mode"), widget=forms.RadioSelect)
    delai = forms.TypedChoiceField(label=_l("admin.maj_auto.form.delai"), coerce=int,
                                   widget=forms.Select(attrs={"aria-describedby": "aide-maj-auto-delai"}))

    def __init__(self, *args, **kwargs):
        from . import mise_a_jour_auto as MA

        super().__init__(*args, **kwargs)
        self.fields["mode"].choices = [(m, libelle(f"admin.maj_auto.mode.{m}")) for m in MA.MODES]
        self.fields["delai"].choices = [(d, libelle("admin.maj_auto.delai.jours", n=d) if d else libelle("admin.maj_auto.delai.aucun"))
                                        for d in MA.DELAIS]


MAJ_AUTO = "maj_auto"  # étiquette des messages montrés dans le bloc « Mises à jour automatiques » de la page Hébergement


@login_required
def sante_installation(request):
    """Administration › Paramètres › Santé : une ligne par point (bon, à regarder, en panne) et quoi faire, réservée à
    l'administrateur de l'espace comme les autres pages des Paramètres. Les mêmes lignes partent en alertes par e-mail
    (``alertes.py``) : réglées ici par un gestionnaire des espaces seulement (« reglage_alertes »,
    ``espaces.comptes.est_gestionnaire``) ; l'alerte d'essai aux destinataires enregistrés (« tester_alertes ») reste
    permise à qui voit le détail de l'installation ; tout autre administrateur : refusé."""
    from espaces.comptes import est_gestionnaire

    from . import alertes as AL
    from . import sante_installation as SI

    exiger_admin_reglages(request)
    form_alertes = None
    ecrire = est_gestionnaire(request.user)
    if request.method == "POST":
        action = request.POST.get("action")
        if not SI.detail_installation_permis(request.user):
            raise PermissionDenied(libelle("admin.alertes.reserve"))
        if action == "reglage_alertes":
            if not ecrire:  # réglage de toute l'installation : gestionnaire des espaces seulement
                raise PermissionDenied(libelle("admin.alertes.reserve"))
            form_alertes = AlertesForm(request.POST)
            if form_alertes.is_valid():
                d = form_alertes.cleaned_data
                for champ, avant, apres in AL.enregistrer(request.user, d["actives"], d["aux_comptes"], d["adresses"]):
                    if champ == "adresses":  # le nombre d'adresses, pas les adresses elles-mêmes
                        avant, apres = len(AL.lire_adresses(avant)[0]), len(AL.lire_adresses(apres)[0])
                    Journal.ecrire(request.user, "reglage_alertes", Instance.courante(), champ, avant, apres)
                messages.success(request, libelle("admin.alertes.enregistre_on" if d["actives"] else "admin.alertes.enregistre_off"),
                                 extra_tags=ALERTES)
                return redirect(reverse("parametres:sante_installation") + "#alertes")
        elif action == "tester_alertes":
            n, erreur = AL.envoyer_essai(request.user)
            Journal.ecrire(request.user, "test_alerte_echec" if erreur else "test_alerte", Instance.courante(), "destinataires",
                           "", str(n))
            if erreur:
                messages.error(request, erreur, extra_tags=ALERTES)
            else:
                messages.success(request, libelle("admin.alertes.essai.envoye", n=n), extra_tags=ALERTES)
            return redirect(reverse("parametres:sante_installation") + "#alertes")
        else:
            return redirect("parametres:sante_installation")
    lignes, permis = SI.lignes(request)
    etat, texte = SI.bilan(lignes)
    r, e = AL.reglage(), AL.etat()
    if form_alertes is None and permis and ecrire:
        form_alertes = AlertesForm(initial={"actives": r.actives, "aux_comptes": r.aux_comptes, "adresses": r.adresses})
    tous = list(messages.get_messages(request))
    messages_alertes = [m for m in tous if ALERTES in m.extra_tags.split()]
    return render(request, "parametres/sante_installation.html", {
        "page": "administration", "rubrique": "parametres", "sous_rubrique": "sante", "lignes": lignes,
        "bilan_etat": etat, "bilan_texte": texte, "detail_permis": permis, "reglage_permis": ecrire, "avec_detail": any(x["detail"] for x in lignes), "campagne": campagne_courante(),
        "alertes": {"actives": r.actives, "pourquoi": AL.pourquoi(r, court=not permis), "envoi": EE.envoi_actif(), "nb": len(AL.destinataires(r)) if permis else 0,
                    "comptes": AL.comptes_permis() if permis else [], "envoye_le": e.envoye_le,
                    "echec_le": e.echec_le if e.echec_le and (e.envoye_le is None or e.echec_le > e.envoye_le) else None,
                    "echec": EE.texte_cause(e.echec) if e.echec else "",
                    "echec_resume": e.echec_resume, "minutes": int(AL.INTERVALLE.total_seconds() // 60)},
        "form_alertes": form_alertes, "messages_alertes": messages_alertes,
        "messages_haut": [m for m in tous if m not in messages_alertes],
    })


@login_required
@sensitive_post_parameters("mot_de_passe")
def hebergement(request):
    from espaces.comptes import est_gestionnaire

    from .sante_installation import detail_installation_permis

    exiger_admin_reglages(request)
    # détail de l'installation (dossier des données, adresses permises, hôte de la base, identifiant SMTP, dossier des
    # sauvegardes) : seulement pour qui le voit (même règle que /sante/ et la page Santé). Les réglages de toute
    # l'installation (serveur d'envoi des e-mails, mises à jour automatiques) ne s'ÉCRIVENT que par un gestionnaire des
    # espaces (``est_gestionnaire``) : ils décident par où partent les e-mails de tous les espaces
    detail = detail_installation_permis(request.user)
    ecrire = est_gestionnaire(request.user)
    form = TestEmailForm(initial={"destinataire": request.user.email})
    form_smtp = _form_serveur() if ecrire and not EE.par_environnement() else None
    instance = Instance.courante()
    reglages = ReglagesSauvegardeForm(instance=instance)
    corbeille = ReglageCorbeilleForm(instance=instance)
    connexions = ReglageConnexionsForm(instance=instance)
    conservation = ReglageConservationForm(instance=instance)
    exports_fond = ReglageExportsFondForm(instance=instance)
    form_maj_auto = None
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "reglage_mise_a_jour_auto":
            from . import mise_a_jour_auto as MA

            # réglage de toute l'installation : gestionnaire des espaces seulement (même règle que les e-mails), et
            # seulement là où la tâche de la machine existe (image Docker)
            if not ecrire:
                raise PermissionDenied(libelle("admin.maj_auto.reserve"))
            if not MA.disponible():
                messages.error(request, libelle("admin.maj_auto.indisponible"), extra_tags=MAJ_AUTO)
                return redirect(reverse("parametres:hebergement") + "#mise-a-jour-auto")
            form_maj_auto = MiseAJourAutoForm(request.POST)
            if form_maj_auto.is_valid():
                d = form_maj_auto.cleaned_data
                try:
                    changements = MA.ecrire_choix(d["mode"], d["delai"])
                except OSError as e:
                    messages.error(request, libelle("admin.maj_auto.ecriture_impossible", erreur=e.strerror or str(e)),
                                   extra_tags=MAJ_AUTO)
                    return redirect(reverse("parametres:hebergement") + "#mise-a-jour-auto")
                for champ, avant, apres in changements:
                    Journal.ecrire(request.user, "reglage_mise_a_jour_auto", instance, champ, avant, apres)
                messages.success(request, libelle(f"admin.maj_auto.enregistre.{d['mode']}"), extra_tags=MAJ_AUTO)
                return redirect(reverse("parametres:hebergement") + "#mise-a-jour-auto")
        if action == "reglage_exports_fond":
            from collecte.templatetags.collecte import entier

            avant = {c: getattr(instance, c) for c in ReglageExportsFondForm.Meta.fields}
            exports_fond = ReglageExportsFondForm(request.POST, instance=instance)
            if exports_fond.is_valid():
                exports_fond.save()
                for c, v in avant.items():
                    if getattr(instance, c) != v:
                        Journal.ecrire(request.user, "reglage_exports_fond", instance, c, v, getattr(instance, c))
                if instance.exports_fond_cellules:
                    cellules = libelle("admin.hebergement.exports_fond.cellules", n=instance.exports_fond_cellules,
                                       nombre=entier(instance.exports_fond_cellules))  # « 1 cellule », « 250 000 cellules »
                    messages.success(request, libelle("admin.hebergement.exports_fond.enregistre", n=instance.exports_fond_jours,
                                                      cellules=cellules))
                else:
                    messages.success(request, libelle("admin.hebergement.exports_fond.enregistre_jamais"))
                return redirect(reverse("parametres:hebergement") + "#reglage-exports-fond")
            instance.refresh_from_db()  # la page affiche les réglages en vigueur, l'erreur à côté du champ
        if action == "reglage_conservation":
            avant = instance.preuves_sensibles_mois
            conservation = ReglageConservationForm(request.POST, instance=instance)
            if conservation.is_valid():
                conservation.save()
                apres = instance.preuves_sensibles_mois
                if apres != avant:
                    Journal.ecrire(request.user, "reglage_conservation", instance, "preuves_sensibles_mois",
                                   "" if avant is None else avant, "" if apres is None else apres)
                if apres:
                    messages.success(request, libelle("admin.hebergement.conservation.enregistre", n=apres))
                else:
                    messages.success(request, libelle("admin.hebergement.conservation.enregistre_vide"))
                return redirect(reverse("parametres:hebergement") + "#reglage-conservation")
            instance.refresh_from_db()  # la page affiche la durée en vigueur, l'erreur à côté du champ
        if action == "reglage_connexions":
            avant = instance.connexions_jours
            connexions = ReglageConnexionsForm(request.POST, instance=instance)
            if connexions.is_valid():
                connexions.save()
                if instance.connexions_jours != avant:
                    Journal.ecrire(request.user, "reglage_connexions", instance, "connexions_jours", avant, instance.connexions_jours)
                messages.success(request, libelle("admin.hebergement.connexions.enregistre", n=instance.connexions_jours))
                return redirect(reverse("parametres:hebergement") + "#reglage-connexions")
            instance.refresh_from_db()  # la page affiche la durée en vigueur, l'erreur à côté du champ
        if action == "reglage_corbeille":
            avant = instance.corbeille_jours
            corbeille = ReglageCorbeilleForm(request.POST, instance=instance)
            if corbeille.is_valid():
                corbeille.save()
                if instance.corbeille_jours != avant:
                    Journal.ecrire(request.user, "reglage_corbeille", instance, "corbeille_jours", avant, instance.corbeille_jours)
                messages.success(request, libelle("admin.hebergement.corbeille.enregistre", n=instance.corbeille_jours))
                return redirect(reverse("parametres:hebergement") + "#reglage-corbeille")
            instance.refresh_from_db()  # la page affiche le délai en vigueur, l'erreur à côté du champ
        if action == "reglages_sauvegarde":
            avant = {c: getattr(instance, c) for c in ReglagesSauvegardeForm.Meta.fields}
            reglages = ReglagesSauvegardeForm(request.POST, instance=instance)
            if reglages.is_valid():
                reglages.save()
                for c, v in avant.items():
                    if getattr(instance, c) != v:
                        Journal.ecrire(request.user, "reglage_sauvegarde", instance, c, v, getattr(instance, c))
                messages.success(request, libelle("admin.hebergement.reglages_enregistres"))
                return redirect("parametres:hebergement")
        if action == "sauvegarder":
            if SV.base_vide():
                messages.error(request, libelle("admin.hebergement.base_vide"))
                return redirect("parametres:hebergement")
            try:
                a = SV.creer("manuelle")
                SV.tourner()
            except (SV.ErreurSauvegarde, OSError) as e:
                messages.error(request, libelle("admin.hebergement.sauvegarde_impossible", erreur=str(e)))
                return redirect("parametres:hebergement")
            Journal.ecrire(request.user, "sauvegarde", Instance.courante(), "sauvegarde", "", a.nom)
            messages.success(request, libelle("admin.hebergement.sauvegarde_creee", nom=a.nom, taille=SV.taille_lisible(a.taille)))
            return redirect(f"{request.path}?telecharger={a.nom}")
        if action == "controler":  # contrôle de cohérence de la base, tout de suite (lecture seule, résultat gardé)
            from collecte import controle_donnees as CD

            try:
                r = CD.controler_et_enregistrer()
            except OSError as e:
                messages.error(request, libelle("admin.controle.impossible", erreur=str(e)))
            else:
                Journal.ecrire(request.user, "controle_donnees", instance, "controle", "", f"{r['errors']} / {r['warnings']}")
                messages.success(request, libelle("admin.controle.fait"))
            return redirect(reverse("parametres:hebergement") + "#controle-donnees")
        if action in ("reglage_emails", "effacer_mdp_emails"):
            if not ecrire:
                raise PermissionDenied(libelle("admin.hebergement.smtp.reserve"))
            if EE.par_environnement():  # le fichier de réglages gagne : rien à enregistrer dans l'outil
                messages.error(request, libelle("admin.hebergement.smtp.par_it"), extra_tags=EMAILS)
                return redirect(reverse("parametres:hebergement") + "#resultat-emails")
            if action == "effacer_mdp_emails":
                if EE.effacer_mot_de_passe(request.user):
                    Journal.ecrire(request.user, "reglage_emails", instance, "mot_de_passe", "", "mot de passe effacé")
                messages.success(request, libelle("admin.hebergement.smtp.mdp_efface"), extra_tags=EMAILS)
                return redirect(reverse("parametres:hebergement") + "#resultat-emails")
            form_smtp = _form_serveur(request.POST)
            if form_smtp.is_valid():
                d = form_smtp.cleaned_data
                changements = EE.enregistrer(request.user, d["hote"], d["port"] or 587, d["securite"], d["identifiant"],
                                             d["expediteur"] or "", d["mot_de_passe"])
                for champ, avant, apres in changements:
                    Journal.ecrire(request.user, "reglage_emails", instance, champ, avant, apres)
                if ("mot_de_passe", "", EE.EFFACE_SERVEUR_CHANGE) in changements:
                    messages.warning(request, libelle("admin.hebergement.smtp.mdp_efface_serveur"), extra_tags=EMAILS)
                    return redirect(reverse("parametres:hebergement") + "#resultat-emails")
                messages.success(request, libelle("admin.hebergement.smtp.enregistre", hote=d["hote"]) if d["hote"]
                                 else libelle("admin.hebergement.smtp.enregistre_vide"), extra_tags=EMAILS)
                return redirect(reverse("parametres:hebergement") + "#resultat-emails")
        if action == "tester_email":
            form = TestEmailForm(request.POST)
            if form.is_valid():
                erreur = _envoyer_test(request, form.cleaned_data["destinataire"])
                if erreur:  # page rendue tout de suite, ouverte sur le résultat (action du formulaire : #resultat-emails)
                    messages.error(request, erreur, extra_tags=EMAILS)
                else:
                    messages.success(request, libelle("admin.hebergement.test_envoye", destinataire=form.cleaned_data["destinataire"])
                                     if EE.envoi_actif() else libelle("admin.hebergement.test_non_envoye"), extra_tags=EMAILS)
                    return redirect(reverse("parametres:hebergement") + "#resultat-emails")
    connexion = ESP.connexion()
    b = connexion.settings_dict
    try:
        liste = SV.archives()
    except OSError:
        liste = []
    auto, controle = SV.etat_automatique(instance), _controle()
    if not detail:
        controle["fichier"] = Path(controle["fichier"]).name  # le nom du fichier, sans le chemin du disque
    # messages des e-mails (réglage, e-mail de test) : dans l'encart « E-mails », à côté du bouton de test, où la page
    # s'ouvre ; les autres en haut de la page, comme ailleurs
    from . import mise_a_jour_auto as MA

    maj_auto = MA.etat_ecran()
    if form_maj_auto is None and ecrire and maj_auto["disponible"]:
        form_maj_auto = MiseAJourAutoForm(initial={"mode": maj_auto["choix"]["mode"], "delai": maj_auto["choix"]["delai"]})
    tous = list(messages.get_messages(request))
    messages_emails = [m for m in tous if EMAILS in m.extra_tags.split()]
    messages_maj_auto = [m for m in tous if MAJ_AUTO in m.extra_tags.split()]
    return render(request, "parametres/hebergement.html", {
        "bilan": _bilan(liste[0] if liste else None, auto, controle),
        "page": "administration", "rubrique": "parametres", "sous_rubrique": "hebergement", "campagne": campagne_courante(),
        "form": form, "reglages": reglages, "corbeille": corbeille, "connexions": connexions, "conservation": conservation, "exports_fond": exports_fond, "nb_preuves": _nb_preuves(), "nb_supprimes": nb_supprimes(), "auto": auto, "restauree": request.GET.get("restauree", ""), "restaurations": _historique(), "archives": liste, "derniere": liste[0] if liste else None, "telecharger": request.GET.get("telecharger", ""),
        "taille_totale": SV.taille_lisible(sum(a.taille for a in liste)),
        "infos": [
            (libelle("admin.hebergement.info.version"), settings.VERSION + (f" ({settings.VERSION_COMMIT[:12]})" if settings.VERSION_COMMIT else "")),
            (libelle("admin.hebergement.info.base"), libelle("admin.hebergement.info.sqlite") if connexion.vendor == "sqlite"
             else f"PostgreSQL ({b.get('HOST')})" if detail else "PostgreSQL"),
            *([(libelle("admin.hebergement.info.dossier"), str(settings.DOSSIER_DONNEES)),
               (libelle("admin.hebergement.info.adresses"), ", ".join(settings.ALLOWED_HOSTS))] if detail else []),
            ("HTTPS", libelle("admin.hebergement.info.https_oui") if settings.HTTPS else libelle("admin.hebergement.info.https_non")),
            (libelle("admin.hebergement.info.taille"), libelle("admin.hebergement.info.taille_valeur", preuve=_mo(settings.PREUVE_TAILLE_MAX), import_=_mo(settings.IMPORT_TAILLE_MAX))),
            (libelle("admin.hebergement.info.logiciels"), f"Python {platform.python_version()}, Django {django.get_version()}"),
            (libelle("admin.hebergement.info.heure"), f"{DC.date_heure_courte(timezone.localtime())} ({settings.TIME_ZONE})"),  # fuseau : TIME_ZONE
        ],
        "smtp": _smtp(detail, ecrire), "form_smtp": form_smtp, "messages_emails": messages_emails,
        "messages_haut": [m for m in tous if m not in messages_emails and m not in messages_maj_auto],
        "maj_auto": maj_auto, "form_maj_auto": form_maj_auto, "messages_maj_auto": messages_maj_auto,
        "contenu": [libelle(c) for c in CONTENU], "hors_contenu": [libelle(c) for c in HORS_CONTENU],
        "dossier_sauvegardes": str(SV.dossier()) if detail else "", "docker": os.environ.get("DANS_DOCKER") == "1",
        "controle": controle, "copie": _copie(ecrire),
    })


def _copie(ecrire):
    """Encart « Copie hors du serveur » de la page Hébergement (copie_externe.py) : état, lien vers son réglage."""
    from . import copie_externe as CE

    s = CE.resume_etat()
    r = CE.reglage() if s["etat"] != "absente" else None
    return {**s, "genre": r.genre if r else "", "modifiable": ecrire}


def _smtp(detail, ecrire):
    """Encart « E-mails » : réglages en vigueur, jamais le mot de passe ; l'identifiant pour qui voit le détail."""
    r = EE.reglage()
    modifie_par = ""
    s = EE.ligne() if r.source == EE.OUTIL else None
    if s is not None and s.modifie_par:
        from espaces.models import Compte

        c = Compte.objects.filter(pk=s.modifie_par).first()
        modifie_par = (f"{c.first_name} {c.last_name}".strip() or c.email) if c else ""
    return {"source": r.source, "configure": r.actif, "par_it": r.source == EE.ENVIRONNEMENT, "outil": r.source == EE.OUTIL,
            "hote": r.hote, "port": r.port, "securite": r.nom_securite,
            "utilisateur": r.identifiant if detail else None, "expediteur": r.expediteur,
            "mot_de_passe": r.mot_de_passe, "illisible": r.mot_de_passe_illisible, "mot_de_passe_le": r.mot_de_passe_le,
            "modifie_le": r.modifie_le, "modifie_par": modifie_par if detail else "",
            "modifiable": ecrire and r.source != EE.ENVIRONNEMENT, "essais_max": EE.ESSAIS_MAX,
            "essais_minutes": int(EE.ESSAIS_FENETRE.total_seconds() // 60)}


def _bilan(derniere, auto, controle):
    """Haut de la page Hébergement : ce qui va bien, en phrases courtes réunies en un paragraphe,
    puis une ligne par point à traiter, avec un lien vers le bloc de la page qui permet de le régler.
    Renvoie {"ok": [phrases], "points": [{"texte", "ancre", "lien"}]}."""
    from collecte.templatetags.collecte import depuis

    def jour(d, forme=None):  # date courte de la langue ; ``forme`` : un autre morceau (heure, « jj/mm »)
        d = timezone.localtime(d) if timezone.is_aware(d) else d
        return DC.date_courte(d) if forme is None else d.strftime(forme)

    ok, points = [], []

    def point(cle, ancre, lien, **params):
        points.append({"texte": libelle(f"admin.hebergement.etat.{cle}", **params), "ancre": ancre,
                       "lien": libelle(f"admin.hebergement.etat.{lien}")})

    if derniere:
        ok.append(libelle("admin.hebergement.etat.sauvegarde_ok", date=jour(derniere.date), heure=jour(derniere.date, "%H:%M"),
                          duree=depuis(derniere.date)))
    else:
        point("sauvegarde_aucune", "sauvegarder-maintenant", "sauvegarde_aucune_lien")
    if not auto["active"]:
        point("auto_desactivee", "sauvegarde-automatique", "auto_desactivee_lien")
    elif auto["en_retard"]:
        point("auto_retard", "sauvegarde-automatique", "auto_retard_lien", date=jour(auto["prochaine"]),
              heure=jour(auto["prochaine"], "%H:%M"))
    else:
        ok.append(libelle("admin.hebergement.etat.auto_ok", date=jour(auto["prochaine"]), heure=jour(auto["prochaine"], "%H:%M")))
    if controle["etat"] == "never":
        ok.append(libelle("admin.hebergement.etat.controle_jamais", heure=controle["heure"]))
    elif controle["etat"] == "late":
        point("controle_retard", "controle-donnees", "controle_lien")
    elif controle["constats_a_voir"]:
        point("controle_points", "controle-donnees", "controle_lien", n=controle["constats_a_voir"])
    elif controle["date"]:
        ok.append(libelle("admin.hebergement.etat.controle_ok", date=jour(controle["date"])))
    from . import copie_externe as CE  # copie externe : dite seulement quand une destination est réglée (aucun bruit sinon)

    copie = CE.resume_etat()
    if copie["etat"] == "echec":
        point("copie_echec", "copie-externe", "copie_lien", n=copie["attente"])
    elif copie["etat"] in ("a_confirmer", "retard"):
        point("copie_regarder", "copie-externe", "copie_lien")
    elif copie["etat"] == "ok" and copie.get("reussie_le"):
        ok.append(libelle("admin.hebergement.etat.copie_ok", date=jour(copie["reussie_le"]),
                          heure=jour(copie["reussie_le"], "%H:%M")))
    r = EE.reglage()
    if r.mot_de_passe_illisible:
        point("emails_mdp", "emails", "emails_mdp_lien")
    elif r.actif:
        ok.append(libelle("admin.hebergement.etat.emails_ok", hote=r.hote))
    else:
        point("emails_non", "emails", "emails_non_lien")
    return {"ok": ok, "points": points}


def _nb_preuves():
    """Preuves à supprimer (Administration › Preuves à supprimer), pour le lien sous le réglage de conservation."""
    from collecte.conservation import nombre

    return nombre()


def nb_supprimes():
    from collecte.administration import nb_supprimes as nb

    return nb()


def _controle():
    """Encart « Contrôle des données » : état du dernier contrôle et ses constats, titres dans la langue de la personne."""
    from collecte import controle_donnees as CD

    e = CD.etat()
    r = e["resultat"] or {}
    ordre = {CD.ERREUR: 0, CD.AVERTISSEMENT: 1, CD.INFO: 2}
    constats = sorted((c for c in r.get("problems", []) if c.get("count")), key=lambda c: ordre.get(c.get("severity"), 3))
    return {**e, "heure": settings.CONTROLE_HEURE, "secondes": r.get("seconds"), "version": r.get("version", ""),
            "infos": r.get("infos", 0), "fichier": str(CD.fichier()),
            "constats": [{**c, "titre": CD.titre(c), "deja": c.get("check") in CD.DEJA_SIGNALES,
                          "reste": max(c.get("count", 0) - len(c.get("examples", [])), 0)} for c in constats],
            "constats_a_voir": len(CD.a_signaler(r))}


def _historique():
    try:
        h = SV.historique_restaurations()
    except OSError:
        return []
    for e in h:
        e["date_sauvegarde_texte"] = _date_texte(e.get("date_sauvegarde", ""))
    return h


def _date_texte(iso):
    """« 2026-10-26T20:04:35+01:00 » → « à 20:04 »."""
    import datetime

    try:
        quand = timezone.localtime(datetime.datetime.fromisoformat(iso))
        return libelle("admin.hebergement.date_heure", date=DC.date_courte(quand), heure=quand.strftime("%H:%M"))
    except (ValueError, TypeError):
        return libelle("admin.hebergement.date_heure", date=iso[:10], heure=iso[11:16])


def _mo(octets):
    from collecte.fichiers import mo

    return mo(octets)


def _envoyer_test(request, destinataire):
    """E-mail de test avec les réglages ENREGISTRÉS (``envoi_emails.connexion_envoi``) ; message d'erreur en clair, sans
    la réponse du serveur. Réglages de l'outil : limite d'essais pour toute l'installation et délai court (le serveur et
    le port sont saisis dans l'outil : pas de bouton pour sonder le réseau interne)."""
    i = Instance.courante()
    r = EE.reglage()
    if r.source == EE.OUTIL:
        attente = EE.reserver_essai()
        if attente:
            return libelle("admin.hebergement.test.trop", n=attente)
    delai = EE.delai_essai()
    try:
        connexion, expediteur = EE.connexion_envoi(timeout=delai)
        EmailMessage(libelle("admin.hebergement.test.objet", titre=i.titre),
                     libelle("admin.hebergement.test.corps", titre=i.titre, nom=i.nom, auteur=request.user.get_full_name() or request.user.email),
                     expediteur, [destinataire], connection=connexion).send()
    except OSError as e:  # erreurs SMTP, réseau, certificat, mot de passe illisible : toutes des OSError
        resume = EE.resume_technique(e)
        journal.warning("Test email to %s through %s:%s failed (%s)", destinataire, r.hote or "-", r.port, resume)
        Journal.ecrire(request.user, "test_email_echec", i, "serveur", "", f"{r.hote}:{r.port} · {resume}"[:200])
        texte = libelle("admin.hebergement.test.echec", cause=EE.cause(e, delai), detail=resume)
        if r.source == EE.ENVIRONNEMENT:
            texte += " " + libelle("admin.hebergement.test.echec_env")
        return texte
    Journal.ecrire(request.user, "test_email", i, "destinataire", "", destinataire)
    return ""


@login_required
def sauvegarde_telecharger(request, nom):
    exiger_admin_reglages(request)
    try:
        a = SV.archive(nom)
    except SV.ErreurSauvegarde as e:
        raise Http404(str(e)) from e
    Journal.ecrire(request.user, "telechargement_sauvegarde", Instance.courante(), "sauvegarde", "", a.nom)
    return FileResponse(open(a.chemin, "rb"), as_attachment=True, filename=a.nom, content_type="application/zip")


def mot_confirmation():
    """Mot à écrire pour confirmer une restauration, dans la langue de la personne (« RESTAURER »)."""
    return libelle("admin.restauration.mot")


def motif_mot(mot):
    """Motif HTML de la zone de saisie : le mot en majuscules ou en minuscules ([Rr][Ee]…)."""
    return "".join(f"[{c.upper()}{c.lower()}]" if c.upper() != c.lower() else re.escape(c) for c in mot)


TABLES_RESUME = [("referentiel.Utilisateur", "comptes"), ("referentiel.Organisation", "organisations"), ("referentiel.KPI", "kpi"),
                 ("collecte.Campagne", "campagnes"), ("collecte.Reponse", "valeurs"), ("collecte.Preuve", "preuves"),
                 ("collecte.Journal", "journal")]  # (table, fin de la clé admin.restauration.table.*)


@login_required
def sauvegarde_restaurer(request, nom=None):
    """Restaurer une sauvegarde depuis l'outil : choisie dans la liste (GET : page de confirmation ; POST : restauration)
    ou déposée (fichier .zip téléchargé auparavant, rangé dans le dossier des sauvegardes puis confirmé)."""
    exiger_admin_reglages(request)
    if nom is None:  # dépôt d'un fichier
        if request.method != "POST" or not request.FILES.get("fichier"):
            return redirect("parametres:hebergement")
        try:
            a = SV.deposer(request.FILES["fichier"])
        except SV.ErreurSauvegarde as e:
            messages.error(request, str(e))
            return redirect("parametres:hebergement")
        Journal.ecrire(request.user, "depot_sauvegarde", Instance.courante(), "sauvegarde", "", a.nom)
        return redirect("parametres:sauvegarde_restaurer", nom=a.nom)
    try:
        a = SV.archive(nom)
        d = SV.lire_descriptif(a.chemin)
        SV.controler_signature(a.chemin)  # seules les archives de cette installation, intactes (IT : « restore --unsigned »)
    except SV.ErreurSauvegarde as e:
        messages.error(request, str(e))
        return redirect("parametres:hebergement")
    erreur = ""
    if request.method == "POST":
        if request.POST.get("confirmation", "").strip().upper() != mot_confirmation().upper() or not request.POST.get("compris"):
            erreur = libelle("admin.restauration.erreur.confirmation", mot=mot_confirmation().upper())
        else:
            auteur = request.user.get_full_name() or request.user.email
            try:
                fait = SV.restaurer(a.chemin, par=auteur, origine="outil", exiger_signature=True)
            except (SV.ErreurSauvegarde, OSError, DatabaseError, DeserializationError) as e:  # base laissée telle quelle
                erreur = libelle("admin.restauration.erreur.impossible", erreur=str(e))
            else:
                from referentiel.models import Utilisateur

                u = Utilisateur.objects.filter(email=request.user.email).first()  # la base restaurée a ses propres comptes
                Journal.ecrire(u, "restauration", Instance.courante(), "sauvegarde", "", f"{a.nom} (par {auteur})")
                # La base restaurée a ses propres sessions : on déconnecte toujours (même comportement sous SQLite et
                # PostgreSQL, quelle que soit la date de la sauvegarde) et la page de connexion dit que tout s'est bien
                # passé. Le message passe par le cookie (la session vient d'être vidée). Après la reconnexion, retour à
                # Hébergement avec la confirmation détaillée.
                logout(request)
                messages.success(request, libelle("admin.restauration.reussie", date=_date_texte(d.get("date", ""))))
                if fait.get("comptes_sans_mot_de_passe"):  # comptes inconnus du registre : les sauvegardes n'ont aucun mot de passe
                    messages.warning(request, libelle("admin.restauration.sans_mot_de_passe", n=fait["comptes_sans_mot_de_passe"]))
                suite = reverse("parametres:hebergement") + f"?restauree={a.nom}"
                return redirect(reverse("login") + "?" + urlencode({"next": suite}))
    actuel = SV.comptes()
    sauve = d.get("tables") or {}
    resume = [(libelle(f"admin.restauration.table.{nom_table}"), actuel.get(cle), sauve.get(cle)) for cle, nom_table in TABLES_RESUME
              if cle in actuel or cle in sauve]
    date = d.get("date", "")
    return render(request, "parametres/restauration.html", {
        "page": "administration", "rubrique": "parametres", "sous_rubrique": "hebergement", "campagne": campagne_courante(),
        "archive": a, "descriptif": d, "resume": resume, "erreur": erreur, "mot": mot_confirmation().upper(),
        "motif_mot": motif_mot(mot_confirmation().upper()),
        "meme_installation": (d.get("installation") or "") in ("", Instance.courante().nom),
        "refus_espace": _refus_espace(d), "espace_archive": _nom_espace(d.get("espace") or ESP.PRINCIPAL),
        "version_differente": d.get("version") != settings.VERSION, "version_installee": settings.VERSION, "date_texte": _date_texte(date),
    })
