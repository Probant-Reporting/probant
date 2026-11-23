"""Hébergement : page de santé (supervision) et Administration › Paramètres › Hébergement (version, sauvegardes à
télécharger, e-mails avec test d'envoi)."""
import datetime
import os
import platform
import re
import shutil
import smtplib
import socket
from pathlib import Path
from urllib.parse import urlencode

import django
from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.core.serializers.base import DeserializationError
from django.db import DatabaseError, connections
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.functional import lazy
from django.views.decorators.cache import never_cache

from collecte import dates_courtes as DC
from collecte.models import Journal
from espaces import contexte as ESP
from collecte.saisie import campagne_courante

from . import sauvegardes as SV
from . import libelles as LB
from .libelles import libelle
from .models import Instance
from .views import exiger_admin_reglages

_l = lazy(libelle, str)  # libellé évalué à l'affichage (champs de formulaire définis à l'import)


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
    messages = [etat[c]["message"] for c in ("background_imports", "background_exports") if etat[c].get("message")]
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


@login_required
def sante_installation(request):
    """Administration › Paramètres › Santé : une ligne par point (bon, à regarder, en panne) et quoi faire. Lecture
    seule, réservée à l'administrateur de l'espace comme les autres pages des Paramètres."""
    from . import sante_installation as SI

    exiger_admin_reglages(request)
    lignes, permis = SI.lignes(request)
    etat, texte = SI.bilan(lignes)
    return render(request, "parametres/sante_installation.html", {
        "page": "administration", "rubrique": "parametres", "sous_rubrique": "sante", "lignes": lignes,
        "bilan_etat": etat, "bilan_texte": texte, "detail_permis": permis, "avec_detail": any(x["detail"] for x in lignes), "campagne": campagne_courante(),
    })


@login_required
def hebergement(request):
    exiger_admin_reglages(request)
    form = TestEmailForm(initial={"destinataire": request.user.email})
    instance = Instance.courante()
    reglages = ReglagesSauvegardeForm(instance=instance)
    corbeille = ReglageCorbeilleForm(instance=instance)
    connexions = ReglageConnexionsForm(instance=instance)
    conservation = ReglageConservationForm(instance=instance)
    exports_fond = ReglageExportsFondForm(instance=instance)
    if request.method == "POST":
        action = request.POST.get("action")
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
        if action == "tester_email":
            form = TestEmailForm(request.POST)
            if form.is_valid():
                erreur = _envoyer_test(request, form.cleaned_data["destinataire"])
                if erreur:
                    messages.error(request, erreur)
                else:
                    messages.success(request, libelle("admin.hebergement.test_envoye", destinataire=form.cleaned_data["destinataire"]) if settings.EMAIL_HOST
                                     else libelle("admin.hebergement.test_non_envoye"))
                    return redirect("parametres:hebergement")
    from .sante_installation import detail_installation_permis

    connexion = ESP.connexion()
    b = connexion.settings_dict
    # détail de l'installation (dossier des données, adresses permises, hôte de la base, identifiant SMTP, dossier des
    # sauvegardes) : seulement pour qui le voit (même règle que /sante/ et la page Santé)
    detail = detail_installation_permis(request.user)
    try:
        liste = SV.archives()
    except OSError:
        liste = []
    auto, controle = SV.etat_automatique(instance), _controle()
    if not detail:
        controle["fichier"] = Path(controle["fichier"]).name  # le nom du fichier, sans le chemin du disque
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
        "smtp": {"configure": bool(settings.EMAIL_HOST), "hote": settings.EMAIL_HOST, "port": settings.EMAIL_PORT,
                 "securite": "SSL" if settings.EMAIL_USE_SSL else "STARTTLS" if settings.EMAIL_USE_TLS else libelle("admin.hebergement.info.aucune"),
                 "utilisateur": settings.EMAIL_HOST_USER if detail else None, "expediteur": settings.DEFAULT_FROM_EMAIL},
        "contenu": [libelle(c) for c in CONTENU], "hors_contenu": [libelle(c) for c in HORS_CONTENU],
        "dossier_sauvegardes": str(SV.dossier()) if detail else "", "docker": os.environ.get("DANS_DOCKER") == "1",
        "controle": controle,
    })


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
    if settings.EMAIL_HOST:
        ok.append(libelle("admin.hebergement.etat.emails_ok", hote=settings.EMAIL_HOST))
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
    i = Instance.courante()
    try:
        send_mail(libelle("admin.hebergement.test.objet", titre=i.titre),
                  libelle("admin.hebergement.test.corps", titre=i.titre, nom=i.nom, auteur=request.user.get_full_name() or request.user.email),
                  None, [destinataire])
    except (smtplib.SMTPException, socket.error, OSError) as e:
        return libelle("admin.hebergement.test.echec", type=e.__class__.__name__, erreur=str(e))
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
