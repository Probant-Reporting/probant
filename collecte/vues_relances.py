"""Page Relances : relancer par e-mail les personnes qui ont encore quelque chose à saisir (administrateur : tout ; validateur :
son périmètre), aperçu du message, modèle réglable et relances automatiques (administrateur), historique. Sans serveur
d'envoi (SMTP) : envoi et essai refusés, rien n'est noté ; « Écrire à … » donne l'adresse, l'objet et le message à
copier dans sa messagerie, personne par personne."""
import datetime
from urllib.parse import quote

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.mail import EmailMessage
from django.shortcuts import redirect, render
from django.utils import timezone

from parametres import envoi_emails as EE
from parametres.libelles import libelle
from parametres.models import Instance
from referentiel.models import Organisation

from . import relances as R
from .models import Campagne, Journal, Relance
from .views import groupes_campagnes
from .vues_communes import campagne_affichee


def autres_langues():
    """Langues de l'interface autres que le français : un modèle de relance par langue."""
    from parametres import langues as L

    return [c for c in L.langues_interface() if c != R.REFERENCE]


class ModeleForm(forms.Form):
    sujet = forms.CharField(max_length=200)
    message = forms.CharField(widget=forms.Textarea(attrs={"rows": 14}))
    relance_auto = forms.BooleanField(required=False)
    relance_jours = forms.CharField(max_length=40, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # libellés dans la langue de la personne (fichiers de langue, zone « suivi »)
        for nom in ("sujet", "message", "relance_auto", "relance_jours"):
            self.fields[nom].label = libelle(f"suivi.relances.form.{nom}")
        self.fields["relance_jours"].help_text = libelle("suivi.relances.form.relance_jours_aide")
        # autres langues : vides = repli (texte français réglé, sinon texte fourni dans la langue), montré en exemple
        fr_sujet, fr_message = R.modele_propre(R.REFERENCE)
        self.langues = []
        for lg in autres_langues():
            nom_langue = libelle(f"commun.langue_nom.{lg}")
            self.fields[f"sujet_{lg}"] = forms.CharField(max_length=200, required=False, label=libelle(
                "suivi.relances.form.sujet_langue", nom_langue=nom_langue), widget=forms.TextInput(attrs={
                    "placeholder": fr_sujet or R.sujet_defaut(lg), "lang": lg}))
            self.fields[f"message_{lg}"] = forms.CharField(required=False, label=libelle(
                "suivi.relances.form.message_langue", nom_langue=nom_langue), widget=forms.Textarea(attrs={
                    "rows": 10, "placeholder": fr_message or R.message_defaut(lg), "lang": lg}))
            repli = libelle("suivi.relances.form.repli_francais" if (fr_sujet or fr_message) else "suivi.relances.form.repli_fourni",
                            nom_langue=nom_langue)
            self.fields[f"message_{lg}"].help_text = repli
            self.langues.append({"code": lg, "nom": nom_langue, "sujet": self[f"sujet_{lg}"], "message": self[f"message_{lg}"],
                                 "rempli": bool((self.initial.get(f"sujet_{lg}") or "") or (self.initial.get(f"message_{lg}") or ""))})

    def clean(self):
        d = super().clean()
        try:
            R.verifier_modele(d.get("sujet", ""), d.get("message", ""))
            for lg in autres_langues():
                R.verifier_modele(d.get(f"sujet_{lg}", ""), d.get(f"message_{lg}", ""))
            d["jours"] = R.jours_echeance(d.get("relance_jours", ""))
        except R.ModeleInvalide as e:
            raise forms.ValidationError(str(e)) from e
        if d.get("relance_auto") and not d["jours"]:
            raise forms.ValidationError(libelle("suivi.relances.form.jour_requis"))
        return d


NOMS_MAX = 5  # confirmation : les 5 premiers noms, puis « et N autres »
MAILTO_MAX = 1800  # au-delà, certaines messageries tronquent le lien : on ne propose que la copie


def noms(personnes):
    """« A », « A et B », « A, B, C, D, E et 3 autres » (dans la langue de la personne)."""
    liste = [str(p) for p in personnes]
    if len(liste) > NOMS_MAX:
        return libelle("suivi.relances.liste.et_autres", n=len(liste) - NOMS_MAX, debut=", ".join(liste[:NOMS_MAX]))
    if len(liste) < 2:
        return "".join(liste)
    return libelle("suivi.relances.liste.et", debut=", ".join(liste[:-1]), fin=liste[-1])


def lien_messagerie(adresse, sujet, texte):
    """Lien « mailto: » prérempli, ou None s'il serait trop long (le message se copie alors)."""
    if not adresse:
        return None
    lien = f"mailto:{quote(adresse, safe='@')}?subject={quote(sujet, safe='')}&body={quote(texte, safe='')}"
    return lien if len(lien) < MAILTO_MAX else None


def _nb_jours_auto(instance):
    """Nombre qui accorde « jour(s) » des relances automatiques : le plus grand des jours réglés (1 : singulier)."""
    try:
        return max(R.jours_echeance(instance.relance_jours), default=2)
    except R.ModeleInvalide:
        return 2


def _rattachee(o, cle):
    """L'organisation ``o`` est celle d'identifiant ``cle`` ou lui est rattachée (parents déjà reliés en mémoire)."""
    while o is not None:
        if o.pk == cle:
            return True
        o = o.parent
    return False


@login_required
def relances(request):
    if not R.peut_relancer(request.user):
        raise PermissionDenied(libelle("suivi.relances.refus.page"))
    campagne = campagne_affichee(request)
    i = Instance.courante()
    # portée : tous les référentiels ouverts (un seul e-mail par personne), ou seulement la campagne affichée
    ouvertes = R.campagnes_ouvertes(request.user)
    portee = request.POST.get("portee") or request.GET.get("portee") or R.portee_par_defaut(ouvertes)
    if campagne not in ouvertes:  # période choisie fermée (ex. 2024 clôturée) : la page montre cette période, pas les autres
        portee = "campagne"
    if portee == "toutes" and ouvertes:
        cibles = ouvertes
    else:
        portee = "campagne"
        cibles = [campagne] if campagne is not None and campagne.statut == Campagne.Statut.OUVERTE else []
    ouverte = bool(cibles)
    sujet, message = R.modele(R.REFERENCE)  # le modèle de référence, en français, quelle que soit la langue de qui règle
    initial = {"sujet": sujet, "message": message, "relance_auto": i.relance_auto, "relance_jours": i.relance_jours}
    for lg in autres_langues():
        initial[f"sujet_{lg}"], initial[f"message_{lg}"] = R.modele_propre(lg)
    form = ModeleForm(initial=initial)
    if request.method == "POST":
        action = request.POST.get("action")
        if action in ("modele", "modele_defaut"):
            if not request.user.est_admin:
                raise PermissionDenied(libelle("suivi.relances.refus.modele"))
            if action == "modele_defaut":
                i.relance_sujet = i.relance_message = ""
                i.relance_traductions = {}
                i.save(update_fields=["relance_sujet", "relance_message", "relance_traductions"])
                Journal.ecrire(request.user, "reglage_relances", i, "modèle", "personnalisé", "texte fourni")
                messages.success(request, libelle("suivi.relances.msg.texte_fourni"))
                return redirect("collecte:relances")
            form = ModeleForm(request.POST)
            if form.is_valid():
                d = form.cleaned_data
                avant = f"{i.relance_auto} {i.relance_jours}"
                i.relance_sujet = "" if d["sujet"] == R.sujet_defaut(R.REFERENCE) else d["sujet"]
                i.relance_message = ("" if d["message"].replace("\r\n", "\n") == R.message_defaut(R.REFERENCE)
                                     else d["message"].replace("\r\n", "\n"))
                traductions = {}
                for lg in autres_langues():
                    s, m = d.get(f"sujet_{lg}", "").strip(), d.get(f"message_{lg}", "").replace("\r\n", "\n").strip()
                    if s or m:
                        traductions[lg] = {"sujet": s, "message": m}
                if traductions != (i.relance_traductions or {}):
                    Journal.ecrire(request.user, "reglage_relances", i, "modèle (autres langues)",
                                   ", ".join(sorted(i.relance_traductions or {})), ", ".join(sorted(traductions)))
                i.relance_traductions = traductions
                i.relance_auto, i.relance_jours = d["relance_auto"], ",".join(map(str, d["jours"])) or i.relance_jours
                i.save(update_fields=["relance_sujet", "relance_message", "relance_traductions", "relance_auto", "relance_jours"])
                Journal.ecrire(request.user, "reglage_relances", i, "relances automatiques", avant, f"{i.relance_auto} {i.relance_jours}")
                messages.success(request, libelle("suivi.relances.msg.modele_enregistre") + (
                    " " + libelle("suivi.relances.msg.auto_jours", n=max(d["jours"]),
                                  jours=noms(i.relance_jours.split(","))) if i.relance_auto else ""))
                return redirect("collecte:relances")
        elif action == "marquer":  # relance faite hors de l'outil (téléphone, messagerie) : notée dans l'historique
            pk = request.POST.get("personne", "")
            liste = R.a_faire(cibles, par=request.user, destinataires=[int(pk)]) if ouverte and pk.isdecimal() else []
            if not liste:
                messages.error(request, libelle("suivi.relances.msg.rien_pour_personne"))
            else:
                r = R.marquer(liste[0], request.user)
                request.session["relances_nouvelles"] = [r.pk]
                messages.success(request, libelle("suivi.relances.msg.marquee", destinataire=r.destinataire))
                # retour sur la ligne cliquée (même filtres, même aperçu), pas en haut de la page
                return redirect(f"{request.get_full_path()}#relance-{r.destinataire_id}")
            return redirect(f"{request.path}?portee={portee}")
        elif action == "annuler_marque":  # erreur de clic : seule une relance notée à la main s'annule, par son auteur ou l'admin
            r = Relance.objects.filter(pk=request.POST.get("relance") or 0, statut=Relance.Statut.MANUELLE).first()
            if r is None or not (request.user.est_admin or r.envoyee_par_id == request.user.pk):
                raise PermissionDenied(libelle("suivi.relances.refus.annuler"))
            Journal.ecrire(request.user, "relance_manuelle", r.destinataire, "à faire", str(r.nombre), "annulée")
            r.delete()
            messages.success(request, libelle("suivi.relances.msg.retiree", destinataire=r.destinataire))
            return redirect(f"{request.get_full_path()}#historique")
        elif action in ("envoyer", "essai"):
            if not R.envoi_actif():  # refus avant tout calcul ; rien n'est envoyé ni noté
                messages.error(request, libelle("suivi.relances.msg.emails_inactifs"))
                return redirect(f"{request.path}?portee={portee}")
            if not ouverte:
                messages.error(request, libelle("suivi.relances.msg.pas_ouverte"))
                return redirect("collecte:relances")
            ids = [int(x) for x in request.POST.getlist("personnes") if x.isdecimal()]
            if not ids:
                messages.error(request, libelle("suivi.relances.msg.cocher_une_personne"))
                return redirect("collecte:relances")
            liste = R.a_faire(cibles, par=request.user, destinataires=ids)
            if action == "essai":
                sujet_essai, texte = R.rediger(liste[0], request) if liste else ("", "")
                if liste:
                    try:
                        connexion, expediteur = EE.connexion_envoi()
                        EmailMessage(libelle("suivi.relances.msg.objet_essai", objet=sujet_essai), texte, expediteur,
                                     [request.user.email], connection=connexion).send()
                        messages.success(request, libelle("suivi.relances.msg.essai_envoye", email=request.user.email,
                                                          personne=liste[0].personne))
                    except Exception as e:
                        R.journal.warning("Test reminder to %s: failed (%s: %s)", request.user.email, e.__class__.__name__, e)
                        messages.error(request, libelle("suivi.relances.msg.essai_echec", cause=R.cause_echec(e)))
                return redirect(f"{request.path}?portee={portee}")
            sans_adresse = [af.personne for af in liste if not af.personne.email_joignable]
            sorties = R.envoyer(liste, par=request.user, request=request)
            ok = [r for r in sorties if r.statut == Relance.Statut.ENVOYEE]
            if ok:
                messages.success(request, libelle("suivi.relances.msg.envoyees", n=len(ok), noms=noms(r.destinataire for r in ok)))
            echecs = [r for r in sorties if r.statut == Relance.Statut.ECHEC]
            if echecs:
                messages.error(request, libelle("suivi.relances.msg.echecs", n=len(echecs), noms=noms(r.destinataire for r in echecs),
                                                cause=R.cause_echec(echecs[0].erreur)))
            if sans_adresse:
                messages.warning(request, libelle("suivi.relances.msg.sans_adresse", noms=noms(sans_adresse)))
            request.session["relances_nouvelles"] = [r.pk for r in sorties]  # marquées « à l'instant » dans l'historique
            return redirect(f"{request.path}?portee={portee}")
    liste = R.a_faire(cibles, par=request.user) if ouverte else []
    sans_spoc = R.restes_sans_spoc(cibles, par=request.user) if ouverte and not liste else 0
    dernieres = R.dernieres_relances([af.personne.pk for af in liste], campagnes=cibles)  # campagnes affichées
    for af in liste:
        af.derniere = dernieres.get(af.personne.pk)
        af.organisations = sorted({l.organisation.nom for l in af.lignes})
        af.referentiels = list(dict.fromkeys(c.referentiel for c, _ in af.campagnes))
    # présélection depuis le tableau de bord (lien « Relancer » d'une ligne) : une personne, ou les personnes d'une
    # organisation et des organisations rattachées ; les autres restent dans la liste, décochées
    personne, org = request.GET.get("personne", ""), request.GET.get("org", "")
    presel = None
    if personne.isdecimal():
        presel = next((af.personne for af in liste if af.personne.pk == int(personne)), None)
    elif org.isdecimal():
        presel = Organisation.objects.filter(pk=org).first()
    for af in liste:
        af.coche = presel is None or (af.personne == presel if personne.isdecimal() else
                                      any(_rattachee(l.organisation, presel.pk) for l in af.lignes))
    apercu, messagerie, langue_apercu, langue_du_compte = None, None, "", False
    choisi = request.GET.get("apercu")
    if liste:
        af = next((x for x in liste if str(x.personne.pk) == choisi), None) or next((x for x in liste if x.coche), liste[0])
        apercu = (af, *R.rediger(af, request))
        langue_apercu = R.langue_de(af.personne)
        from parametres import langues as L

        langue_du_compte = bool(L.preference(af.personne))  # sinon : langue par défaut de l'installation
        messagerie = lien_messagerie(af.personne.email_joignable, apercu[1], apercu[2])
    # historique des campagnes affichées (celles relancées, sinon la campagne choisie) : changer d'année le change aussi
    vues = cibles or ([campagne] if campagne is not None else [])
    historique = (Relance.objects.filter(campagnes__in=vues).distinct()
                  .select_related("destinataire", "envoyee_par").prefetch_related("campagnes"))
    if not request.user.est_admin:
        historique = historique.filter(envoyee_par=request.user)
    nouvelles = set(request.session.pop("relances_nouvelles", []))
    prochaines = []
    if i.relance_auto:
        aujourdhui = timezone.localdate()
        for c in Campagne.objects.filter(statut=Campagne.Statut.OUVERTE, date_fin_saisie__isnull=False).select_related("periode", "referentiel"):
            for j in R.jours_echeance(i.relance_jours):
                jour = c.date_fin_saisie - datetime.timedelta(days=j)
                if jour >= aujourdhui:
                    prochaines.append((jour, c))
        prochaines.sort(key=lambda x: x[0])
    return render(request, "collecte/relances.html", {
        "page": "tableau_de_bord", "campagne": campagne, "groupes_campagnes": groupes_campagnes(request.user), "ouverte": ouverte,
        "liste": liste, "apercu": apercu, "langue_apercu": langue_apercu, "langue_du_compte": langue_du_compte, "historique": historique[:30], "form": form, "variables": R.VARIABLES,
        "instance_relances": i, "nb_jours_auto": _nb_jours_auto(i), "prochaines": prochaines[:6], "smtp": R.envoi_actif(), "messagerie": messagerie,
        "total": sum(af.nombre for af in liste), "sans_spoc": sans_spoc, "portee": portee, "ouvertes": ouvertes, "cibles": cibles,
        "presel": presel, "nb_coches": sum(af.coche for af in liste), "nouvelles": nouvelles,
        "modele_replie": request.GET.get("personne", "").isdecimal(),  # E16 : arrivé depuis une personne
    })
