"""Espace Administration (administrateurs) : campagnes, organisations, comptes, journal.

Remplace l'interface technique de Django pour les tâches courantes (cahier des charges, sections 4.2, 4.3,
4.5 et 5.6). Chaque fiche s'ouvre dans le panneau latéral ; sans JavaScript, en page complète.
"""
import datetime
import re
from collections import defaultdict
from decimal import Decimal
from functools import lru_cache

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
from django.db.models import BigIntegerField, BooleanField, CharField, Count, Exists, Func, OuterRef, Q, Value
from django.db.models.functions import Cast, Lower
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.functional import lazy
from django.utils.safestring import mark_safe

from parametres import langues as L
from parametres import libelles as LB
from parametres import niveaux as N
from parametres import sauvegardes as SV
from parametres.libelles import libelle
from parametres.models import CategorieDescription, ChampPersonnalise, Instance, TypeReponse, TypeSaisie, Unite
from referentiel.models import KPI, Attribution, Organisation, OrgAlias, Referentiel, Theme, Utilisateur, porteurs_orphelins

from . import dates_courtes as DC
from . import relances as RL
from . import saisie as S
from . import tri as TRI
from .calcul import chiffres_gardes, figee, recalculer
from .models import Campagne, Journal, ReglageExport, Reponse, SelectionKPI, VueVisu
from .templatetags.collecte import arrondi, entier, nom_porte_niveau, nombre
from .vues_communes import est_script, exiger_admin, identifiant
from espaces import comptes as EC
from espaces import contexte as ESP

CENT = Decimal(100)
_l = lazy(libelle, str)  # libellé évalué à l'affichage (champs de formulaire définis à l'import)


EMAIL_INVALIDE = _l("admin.compte.email_invalide")  # au lieu du « courriel » de Django


def _pct(fraction):
    """0,2 → 20 (sans notation scientifique)."""
    return Decimal(format((fraction * CENT).normalize(), "f"))


_LISTE_DE_LA_FICHE = {
    "collecte/administration/_campagne.html": ("collecte:admin_campagnes", "admin.nav.campagnes"),
    "collecte/administration/_organisation.html": ("collecte:admin_organisations", "admin.nav.organisations"),
    "collecte/administration/_compte.html": ("collecte:admin_comptes", "admin.nav.comptes"),
}


def _panneau(request, gabarit, ctx, page_complete="collecte/administration/page_panneau.html"):
    """Réponse d'une fiche : JSON pour le panneau, page complète sinon."""
    if est_script(request):
        return JsonResponse({"html": render_to_string(gabarit, ctx, request=request), "ok": bool(ctx.get("succes"))})
    if "retour" not in ctx and gabarit in _LISTE_DE_LA_FICHE:  # retour à la liste d'où l'on vient, pas à la vue d'ensemble
        url_liste, cle_nav = _LISTE_DE_LA_FICHE[gabarit]
        ctx = {**ctx, "retour": (reverse(url_liste), libelle(cle_nav))}
    return render(request, page_complete, {**ctx, "gabarit": gabarit})


# ---------------------------------------------------------------- accueil
@login_required
def accueil(request):
    exiger_admin(request)
    ouvertes = list(Campagne.objects.filter(statut=Campagne.Statut.OUVERTE).select_related("referentiel", "periode"))
    ouverte = ouvertes[0] if ouvertes else None
    revues = list(Campagne.objects.filter(statut=Campagne.Statut.REVUE).select_related("referentiel", "periode"))
    orgs = Organisation.objects.aggregate(total=Count("id"), inactives=Count("id", filter=Q(actif=False)))
    comptes = Utilisateur.objects.aggregate(total=Count("id"), inactifs=Count("id", filter=Q(is_active=False)))
    depuis = timezone.now() - datetime.timedelta(days=7)
    a_traiter, sans_spoc = _a_traiter(request, ouvertes, revues)
    return render(request, "collecte/administration/accueil.html", {
        "page": "administration", "ouverte": ouverte, "ouvertes": ouvertes, "revue": revues[0] if revues else None,
        "campagne": ouverte or S.campagne_courante(), "a_traiter": a_traiter,
        "nb_campagnes": Campagne.objects.count(), "orgs": orgs, "comptes": comptes,
        "nb_kpi": KPI.objects.filter(actif=True).count(), "nb_journal": Journal.objects.filter(date__gte=depuis).count(),
        "sans_spoc": sans_spoc, "nb_referentiels": Referentiel.objects.filter(actif=True).count(),
        "smtp": RL.envoi_actif(), "langues": [l.libelle for l in L.actives()], "sauvegarde": SV.etat_automatique(),
        # textes assemblés ici : un paramètre de libellé reçoit du texte déjà prêt
        "langues_texte": ", ".join(l.libelle for l in L.actives()),
        "liste_ouvertes": ", ".join(c.nom_complet_affiche for c in ouvertes),
    })


def _a_traiter(request, ouvertes, revues):
    """Ce qui attend l'administrateur, le plus urgent d'abord : [{titre, detail, action, url}], et le nombre de cellules sans
    SPOC (KPI × organisation) qui restent à faire dans les campagnes ouvertes."""
    from parametres import sauvegardes as SV
    from referentiel.plans import Plan

    from . import a_traiter as AT
    from .models import Alerte
    from .views import suivi

    aujourdhui, liste, sans = timezone.localdate(), [], set()

    def ajouter(rang, titre, detail, action, url):
        ranger(rang, AT.point("", titre, detail, action, url))

    def ranger(rang, sujet):
        liste.append((rang, len(liste), sujet))

    for c in ouvertes:
        plan = Plan(c.referentiel)
        lignes = list(S.lignes(request.user, c, plan=plan, legere=True))  # compter seulement (mêmes chiffres)
        attendu, retards, _ = suivi(c, S.tableau_de_bord(lignes, plan))
        sans |= {(l.kpi.code, l.organisation.id) for l in lignes if l.attendue and not l.spocs and l.statut != Reponse.Statut.VALIDE}
        fiche = reverse("collecte:admin_campagne", args=[c.pk])
        if c.date_fin_saisie and c.date_fin_saisie < aujourdhui:
            ajouter(1, libelle("admin.a_traiter.fin_depassee"),
                    libelle("admin.a_traiter.fin_depassee_detail", campagne=c.nom_complet_affiche, date=DC.date_courte(c.date_fin_saisie)),
                    libelle("admin.a_traiter.fin_depassee_action"), fiche)
        elif not c.date_fin_saisie:
            ajouter(5, libelle("admin.a_traiter.sans_fin"), libelle("admin.a_traiter.sans_fin_detail", campagne=c.nom_complet_affiche),
                    libelle("admin.a_traiter.sans_fin_action"), fiche)
        if retards:
            ranger(3, AT.retards(len(retards), c, attendu, f"{reverse('collecte:tableau_de_bord')}?campagne={c.pk}&tri=taux"))
    suivies = {c.pk: c for c in ouvertes + revues}
    justifiees = (Alerte.objects.filter(campagne__in=suivies, statut=Alerte.Statut.JUSTIFIEE)
                  .values("campagne").annotate(n=Count("id")).order_by("campagne"))
    for j in justifiees:
        c, n = suivies[j["campagne"]], j["n"]
        ajouter(2, libelle("admin.a_traiter.justifications", n=n), libelle("admin.a_traiter.justifications_detail", campagne=c.nom_complet_affiche),
                libelle("admin.a_traiter.justifications_action"), f"{reverse('collecte:coherence')}?campagne={c.pk}&statut=justifiee")
    from . import forcage as FO

    for c in ouvertes + revues:  # demandes de valeur forcée qui attendent un accord
        n = len(FO.demandes_a_traiter(request.user, [c]))
        if n:
            ajouter(2, libelle("admin.a_traiter.forcages", n=n), libelle("admin.a_traiter.forcages_detail", campagne=c.nom_complet_affiche),
                    libelle("admin.a_traiter.forcages_action"), f"{reverse('collecte:forcages')}?campagne={c.pk}")
    vues_periodes = set()
    for c in ouvertes + revues:  # chiffres importés tels quels sur des cases calculées : jamais changés en silence
        if c.periode_id in vues_periodes:
            continue
        vues_periodes.add(c.periode_id)
        n = len(FO.importees(c))
        if n:
            ajouter(2, libelle("admin.a_traiter.importees", n=n), libelle("admin.a_traiter.importees_detail", campagne=c.nom_complet_affiche),
                    libelle("admin.a_traiter.importees_action"), f"{reverse('collecte:forcages')}?campagne={c.pk}#importees")
    if sans:
        ranger(4, AT.sans_spoc(len(sans)))
    from . import attributions_lecture_seule as ALS

    point = ALS.point_a_traiter()  # lecteurs et auditeurs qui ont encore des attributions (d'avant la mise à jour)
    if point:
        ranger(4, point)
    for c in revues:
        ajouter(6, libelle("admin.a_traiter.revue"), libelle("admin.a_traiter.revue_detail", campagne=c.nom_complet_affiche),
                libelle("admin.a_traiter.revue_action"), reverse("collecte:admin_campagne", args=[c.pk]))
    from . import formules as FM

    n = FM.nombre()
    if n:  # formules cassées : rien ne se calcule pour ces KPI tant qu'elles ne sont pas corrigées
        ajouter(1, libelle("admin.a_traiter.formules", n=n), libelle("admin.a_traiter.formules_detail"),
                libelle("admin.a_traiter.formules_action"), reverse("collecte:admin_formules"))
    from . import unites_mal_rapprochees as UM

    cas = UM.douteux()  # unité qui ressemble au rapprochement fautif d'avant la mise à jour : l'administrateur vérifie
    if cas:
        codes = ", ".join(c.kpi.code for c in cas[:3]) + (" …" if len(cas) > 3 else "")
        url = (reverse("collecte:referentiel_kpi", args=[cas[0].kpi.code]) if len(cas) == 1 else reverse("collecte:referentiel"))
        ajouter(3, libelle("admin.a_traiter.unites", n=len(cas)), libelle("admin.a_traiter.unites_detail", kpis=codes),
                libelle("admin.a_traiter.unites_action"), url)
    from . import conservation as CV

    n = CV.nombre()  # preuves des KPI sensibles gardées au-delà de la durée réglée : l'administrateur décide, rien n'est supprimé seul
    if n:
        ajouter(3, libelle("admin.a_traiter.preuves", n=n), libelle("admin.a_traiter.preuves_detail", n=CV.mois_reglage()),
                libelle("admin.a_traiter.preuves_action"), reverse("collecte:admin_preuves"))
    from . import controle_donnees as CD

    controle = CD.etat()  # contrôle de cohérence de la base (chaque nuit)
    signales = CD.a_signaler(controle["resultat"])
    if signales:
        quand = timezone.localtime(controle["date"])
        erreur = any(c["severity"] == CD.ERREUR for c in signales)
        ajouter(1 if erreur else 4, libelle("admin.a_traiter.controle", n=len(signales)),
                libelle("admin.a_traiter.controle_detail", date=DC.date_courte(quand), heure=f"{quand:%H:%M}",
                        liste=" · ".join(CD.titre(c) for c in signales[:3]) + (" …" if len(signales) > 3 else "")),
                libelle("admin.a_traiter.controle_action"), reverse("parametres:hebergement") + "#controle-donnees")
    if controle["etat"] == "late":
        quand = timezone.localtime(controle["date"]) if controle["date"] else None
        ajouter(8, libelle("admin.a_traiter.controle_retard"),
                libelle("admin.a_traiter.controle_retard_detail", date=DC.date_courte(quand) if quand else "—"),
                libelle("admin.a_traiter.hebergement"), reverse("parametres:hebergement") + "#controle-donnees")
    from . import imports_arriere_plan as AP

    for t in AP.a_signaler(request.user):  # imports en arrière-plan de l'administrateur : en cours, ou fini et pas encore vu
        url = f"{reverse('collecte:echanges_importer')}?tache={t.pk}"
        if t.active:
            ajouter(9, libelle("admin.a_traiter.import_en_cours", nom=t.nom_fichier),
                    libelle("admin.a_traiter.import_en_cours_detail", pct=t.pourcentage), libelle("admin.a_traiter.import_action"), url)
        elif t.statut == t.Statut.TERMINEE:
            ajouter(2, libelle("admin.a_traiter.import_fini", nom=t.nom_fichier),
                    libelle("admin.a_traiter.import_fini_detail", n=t.ecrites), libelle("admin.a_traiter.import_action"), url)
        else:
            ajouter(1, libelle("admin.a_traiter.import_probleme", nom=t.nom_fichier),
                    libelle("admin.a_traiter.import_probleme_detail"), libelle("admin.a_traiter.import_action"), url)
    from referentiel.models import Referentiel

    if not Referentiel.objects.filter(actif=True).exists():
        ajouter(0, libelle("admin.a_traiter.sans_referentiel"), libelle("admin.a_traiter.sans_referentiel_detail"),
                libelle("admin.a_traiter.sans_referentiel_action"), reverse("parametres:referentiel_nouveau"))
    hebergement = reverse("parametres:hebergement")
    if not RL.envoi_actif():
        # relances automatiques réglées mais sautées faute de SMTP : plus urgent (rang 3, comme un retard)
        auto = Instance.courante().relance_auto
        ranger(3 if auto else 7, AT.emails(auto))
    sauvegarde = SV.etat_automatique()
    if not sauvegarde["active"]:
        ajouter(8, libelle("admin.a_traiter.sauvegarde_off"), libelle("admin.a_traiter.sauvegarde_off_detail"), libelle("admin.a_traiter.hebergement"), hebergement)
    elif sauvegarde["en_retard"]:
        derniere = timezone.localtime(sauvegarde["derniere"])
        ajouter(8, libelle("admin.a_traiter.sauvegarde_retard"),
                libelle("admin.a_traiter.sauvegarde_retard_detail", date=DC.date_courte(derniere), heure=f"{derniere:%H:%M}"),
                libelle("admin.a_traiter.hebergement"), hebergement)
    return [t for _, _, t in sorted(liste, key=lambda x: x[:2])], len(sans)


# ---------------------------------------------------------------- campagnes
class CampagneForm(forms.ModelForm):
    """Réglages d'une campagne. À la création : le référentiel, l'exercice et la période dans l'exercice (mois,
    trimestre ou semestre selon la fréquence du référentiel), ou toutes les périodes de l'exercice d'un coup."""

    seuil_pct = forms.DecimalField(label=_l("admin.campagne.form.seuil_pct"), required=False, min_value=0, max_value=100,
                                   help_text=_l("admin.campagne.form.seuil_pct_aide"))
    referentiel = forms.ModelChoiceField(Referentiel.objects.all(), label=_l("admin.campagne.form.referentiel"), required=False, empty_label=None)
    exercice = forms.IntegerField(label=_l("admin.campagne.form.exercice"), min_value=1900, max_value=3000, required=False)
    rang = forms.TypedChoiceField(label=_l("admin.campagne.form.periode"), coerce=int, required=False, choices=[(i, str(i)) for i in range(1, 13)])
    toutes = forms.BooleanField(label=_l("admin.campagne.form.toutes"), required=False)

    class Meta:
        model = Campagne
        fields = ["date_ouverture", "date_fin_saisie", "seuil_historique"]
        widgets = {"date_ouverture": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
                   "date_fin_saisie": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}
        labels = {"date_ouverture": _l("admin.campagne.form.debut_saisie"), "date_fin_saisie": _l("admin.campagne.form.fin_saisie"),
                  "seuil_historique": _l("admin.campagne.form.seuil_historique")}
        help_texts = {"seuil_historique": _l("admin.campagne.form.seuil_historique_aide")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        seuil = self.fields["seuil_historique"]
        seuil.required = False
        # écrit avec la décimale de la langue et sans zéros inutiles (« 2 », « 1,5 »), comme les seuils des Paramètres
        seuil.localize = True
        seuil.widget = forms.TextInput(attrs={"inputmode": "decimal"})
        seuil.widget.is_localized = True
        v = self.initial.get("seuil_historique")
        if isinstance(v, Decimal):
            self.initial["seuil_historique"] = v.quantize(Decimal(1)) if v == v.to_integral() else v.normalize()
        LB.traduire_choix(self)
        self.fields["referentiel"].label_from_instance = lambda r: f"{r} ({LB.choix_phrase(r, 'frequence')})"
        if self.instance.pk:
            for f in ("referentiel", "exercice", "rang", "toutes"):
                del self.fields[f]
            if self.instance.seuil_ecart is not None:
                self.initial["seuil_pct"] = _pct(self.instance.seuil_ecart)
                if self.initial["seuil_pct"] > CENT:
                    # seuil enregistré avant la borne de 100 % : accepté tant qu'il n'est pas changé (clean_seuil_pct),
                    # pour que la campagne puisse encore être enregistrée pour un autre réglage
                    champ = self.fields["seuil_pct"]
                    champ.validators = [v for v in champ.validators if not isinstance(v, MaxValueValidator)]
                    champ.widget.attrs.pop("max", None)

    def clean(self):
        d = super().clean()
        debut, fin = d.get("date_ouverture"), d.get("date_fin_saisie")
        if debut and fin and fin < debut:
            raise ValidationError(libelle("admin.campagne.erreur.fin_avant_debut"))
        if not self.instance.pk:
            ref = d.get("referentiel") or Referentiel.objects.filter(actif=True, frequence="annee").first()
            if ref is None:
                from referentiel.composition import referentiel_par_defaut

                ref = referentiel_par_defaut()
            d["referentiel"] = ref
            if not d.get("exercice"):
                raise ValidationError(libelle("admin.campagne.erreur.exercice"))
            from .periodes import debuts

            liste = debuts(ref.frequence, d["exercice"], ref.mois_debut)
            if d.get("toutes") and len(liste) > 1:
                d["debuts"] = liste
            else:
                rang = d.get("rang") or 1
                if not 1 <= rang <= len(liste):
                    raise ValidationError(libelle("admin.campagne.erreur.periode", maximum=len(liste), frequence=LB.choix_phrase(ref, "frequence")))
                d["debuts"] = [liste[rang - 1]]
            existantes = [str(p) for p in (Campagne.objects.filter(referentiel=ref, periode__type=ref.frequence,
                                                                   periode__debut__in=d["debuts"]).values_list("periode__libelle", flat=True))]
            if existantes and not d.get("toutes"):
                raise ValidationError(libelle("admin.campagne.erreur.existe", campagne=existantes[0], referentiel=ref))
        return d

    def clean_seuil_pct(self):
        v = self.cleaned_data.get("seuil_pct")
        if v is not None and v > CENT and v != self.initial.get("seuil_pct"):
            MaxValueValidator(CENT)(v)  # nouvelle valeur au-dessus de 100 : refusée (même message que la borne du champ)
        return v

    def clean_seuil_historique(self):
        return self.cleaned_data.get("seuil_historique") or Decimal("2")

    def save(self, commit=True):
        pct = self.cleaned_data.get("seuil_pct")
        self.instance.seuil_ecart = None if pct is None else pct / CENT
        return super().save(commit)

    def creer(self):
        """Crée la (ou les) campagne(s) demandée(s) ; renvoie la liste des campagnes créées."""
        from .periodes import campagne as campagne_de_periode

        d, creees = self.cleaned_data, []
        pct = d.get("seuil_pct")
        for i, debut in enumerate(d["debuts"]):
            c, cree = campagne_de_periode(d["referentiel"], debut, seuil_historique=d["seuil_historique"],
                                          seuil_ecart=None if pct is None else pct / CENT,
                                          date_ouverture=d.get("date_ouverture") if len(d["debuts"]) == 1 else None,
                                          date_fin_saisie=d.get("date_fin_saisie") if len(d["debuts"]) == 1 else None)
            if cree:
                creees.append(c)
        return creees


def suggestion_campagne(referentiel=None):
    """Prochaine campagne du référentiel (le premier par défaut) : période suivant la dernière, même seuil ; saisie de
    janvier à mars pour un exercice annuel, sur les quinze premiers jours de la période suivante sinon."""
    from .periodes import ajouter_mois, exercice_de, fin_de, rang_dans_exercice

    ref = referentiel or Referentiel.objects.filter(actif=True).first() or Referentiel.objects.first()
    if ref is None:
        return {}
    derniere = Campagne.objects.filter(referentiel=ref).select_related("periode").order_by("-periode__debut").first()
    n = {"annee": 12, "semestre": 6, "trimestre": 3, "mois": 1}[ref.frequence]
    if derniere:
        debut = ajouter_mois(derniere.periode.debut, n)
    else:
        aujourdhui = timezone.localdate()
        debut = datetime.date(exercice_de(aujourdhui, ref.mois_debut), ref.mois_debut, 1)
        while fin_de(ref.frequence, debut) < aujourdhui and ref.frequence != "annee":
            debut = ajouter_mois(debut, n)
    exercice = exercice_de(debut, ref.mois_debut)
    lendemain = fin_de(ref.frequence, debut) + datetime.timedelta(days=1)
    ouverture, fin = ((datetime.date(exercice + 1, 1, 5), datetime.date(exercice + 1, 3, 31)) if ref.frequence == "annee"
                      else (lendemain, lendemain + datetime.timedelta(days=14)))
    return {"referentiel": ref.pk, "exercice": exercice, "rang": rang_dans_exercice(ref.frequence, debut, ref.mois_debut),
            "date_ouverture": ouverture, "date_fin_saisie": fin,
            "seuil_pct": _pct(derniere.seuil_ecart) if derniere and derniere.seuil_ecart is not None else None}


@login_required
def campagnes(request):
    exiger_admin(request)
    liste = list(Campagne.objects.select_related("referentiel", "periode").order_by("referentiel__ordre", "-periode__debut"))
    # valeurs saisies ou importées de chaque campagne : une requête groupée par période et KPI (et non une jointure sur
    # toutes les réponses), puis les KPI de son référentiel et les sources de leurs formules (comme
    # ``saisie.codes_perimetre``, nombre de requêtes constant) ; avant : toute la période, quel que soit le référentiel
    # (420 valeurs affichées pour une campagne sans aucune valeur)
    par_kpi = {}
    for periode_id, kpi_id, n in (Reponse.objects.filter(periode_id__in={c.periode_id for c in liste},
                                                        origine__in=[Reponse.Origine.SAISIE, Reponse.Origine.IMPORT])
                                  .order_by().values_list("periode_id", "kpi_id").annotate(n=Count("pk"))):
        par_kpi.setdefault(periode_id, {})[kpi_id] = n
    from referentiel.models import ElementReferentiel

    from .demande_depuis import avec_sources, graphe_formules

    elements = {}
    for ref_id, kpi_id in ElementReferentiel.objects.filter(referentiel_id__in={c.referentiel_id for c in liste}).values_list(
            "referentiel_id", "kpi_id"):
        elements.setdefault(ref_id, set()).add(kpi_id)
    graphe = graphe_formules() if elements else {}
    codes_ref = {r: avec_sources(s, graphe) for r, s in elements.items()}
    groupes = {}
    for r in Referentiel.objects.order_by("-actif", "ordre", "code"):
        groupes[r.pk] = (r, [])
    for c in liste:
        du_mois = par_kpi.get(c.periode_id, {})  # sans aucun KPI dans les référentiels : tout le catalogue est collecté
        codes = codes_ref.get(c.referentiel_id, set())
        c.nb_saisies = sum(du_mois.values()) if not elements else sum(n for k, n in du_mois.items() if k in codes)
        groupes[c.referentiel_id][1].append(c)
    return render(request, "collecte/administration/campagnes.html", {
        # (référentiel, campagnes, ouvert) : replié par défaut quand toutes ses campagnes sont clôturées
        "page": "administration", "rubrique": "campagnes",
        "groupes": [(r, cs, not cs or any(c.statut != Campagne.Statut.CLOTUREE for c in cs))
                    for r, cs in groupes.values() if cs or r.actif],
        "aujourdhui": timezone.localdate(), "campagne": S.campagne_courante(),
    })


@login_required
def campagne(request, pk=None):
    """Fiche campagne : dates, seuil d'écart, et changement de statut (ouvrir, clôturer, rouvrir)."""
    exiger_admin(request)
    c = get_object_or_404(Campagne.objects.select_related("referentiel", "periode"), pk=pk) if pk else Campagne()
    ref_demande = Referentiel.objects.filter(pk=request.GET.get("referentiel")).first()
    form = CampagneForm(instance=c, initial=suggestion_campagne(ref_demande) if not c.pk else None)
    succes, erreur = "", ""
    if request.method == "POST":
        action = request.POST.get("action", "enregistrer")
        try:
            if action == "enregistrer":
                form = CampagneForm(request.POST, instance=c)
                if form.is_valid():
                    if not c.pk:
                        creees = form.creer()
                        for n in creees:
                            Journal.ecrire(request.user, "creation_campagne", n, "statut", "", "en préparation")
                            recalculer(n)  # valeurs déjà connues : cumuls des périodes plus courtes, formules
                        succes = (libelle("admin.campagne.creee", campagne=creees[0].nom_complet_affiche) if len(creees) == 1
                                  else libelle("admin.campagne.creees", n=len(creees)) if creees else libelle("admin.campagne.existent_deja"))
                        c = creees[0] if len(creees) == 1 else c
                        form = CampagneForm(instance=c) if c.pk else form
                    else:
                        avant = {f: form.initial.get(f) for f in form.changed_data}
                        c = form.save()
                        for champ, valeur in avant.items():
                            Journal.ecrire(request.user, "reglage_campagne", c, champ, valeur, form.cleaned_data.get(champ, getattr(c, champ, "")))
                        succes = libelle("admin.campagne.enregistree")
                        form = CampagneForm(instance=c)
            elif action in TRANSITIONS:
                # réouverture d'un exercice clos : « garder les chiffres de l'époque » sauf choix contraire
                succes = changer_statut(request.user, c, action, garder=request.POST.get("reouverture") != "recalculer")
            elif action == "recalculer" and c.statut != Campagne.Statut.CLOTUREE and not chiffres_gardes(c.periode):
                n = recalculer(c)
                succes = libelle("admin.campagne.calculs_refaits", n=n)
        except ValidationError as e:
            erreur = " ".join(e.messages)
        if not est_script(request) and succes:
            return redirect("collecte:admin_campagnes")
    return _panneau(request, "collecte/administration/_campagne.html", {
        "titre_page": libelle("admin.campagne.titre_page", nom=c.libelle) if c.pk else libelle("admin.campagne.nouvelle"), "c": c, "form": form, "succes": succes, "erreur": erreur, "aujourdhui": timezone.localdate(),
        "rangs": rangs_par_frequence(), "frequences": {r.pk: r.frequence for r in Referentiel.objects.all()},
        # réouverture d'une période figée : choix entre garder les chiffres de l'époque et recalculer
        "choix_reouverture": bool(c.pk and c.statut == Campagne.Statut.CLOTUREE and figee(c.periode)),
        # « garder les chiffres de l'époque » vaut pour toute la période : pas de « Refaire les calculs »
        "periode_gardee": bool(c.pk and chiffres_gardes(c.periode)),
    })


def rangs_par_frequence():
    """Libellés des périodes d'un exercice pour le choix « Période » : [(fréquence, rang, libellé)]."""
    from parametres import langues as L
    from referentiel.models import Frequence

    from .periodes import MOIS, PREFIXES

    langue = L.interface()  # noms des mois et lettres T / S (Q / H en anglais) dans la langue de l'interface
    t = PREFIXES[Frequence.TRIMESTRE].get(langue, "Q")
    s = PREFIXES[Frequence.SEMESTRE].get(langue, "H")
    sortie = [("mois", i + 1, m) for i, m in enumerate(MOIS.get(langue, MOIS["fr"]))]
    sortie += [("trimestre", i, f"{t}{i}") for i in range(1, 5)] + [("semestre", i, f"{s}{i}") for i in (1, 2)]
    return sortie


TRANSITIONS = {
    # action : (statuts de départ, statut d'arrivée, clé du message)
    "ouvrir": ([Campagne.Statut.PREPARATION], Campagne.Statut.OUVERTE, "admin.campagne.transition.ouvrir"),
    "revue": ([Campagne.Statut.OUVERTE], Campagne.Statut.REVUE, "admin.campagne.transition.revue"),
    "cloturer": ([Campagne.Statut.OUVERTE, Campagne.Statut.REVUE], Campagne.Statut.CLOTUREE, "admin.campagne.transition.cloturer"),
    "rouvrir": ([Campagne.Statut.CLOTUREE], Campagne.Statut.REVUE, "admin.campagne.transition.rouvrir"),
    "rouvrir_contributeurs": ([Campagne.Statut.REVUE, Campagne.Statut.CLOTUREE], Campagne.Statut.OUVERTE,
                              "admin.campagne.transition.rouvrir_contributeurs"),
}


@ESP.atomic
def changer_statut(utilisateur, c, action, garder=False):
    """Préparation → saisie ouverte → revue (clôture contributeurs) → clôturée (clôture définitive).

    Plusieurs campagnes peuvent être ouvertes en même temps (ex. l'exercice annuel et le mois en cours d'un référentiel
    mensuel) ; chaque changement est tracé (section 5.6).

    Réouverture d'une période figée (toutes ses campagnes clôturées): ``garder`` vrai =
    « garder les chiffres de l'époque » : rien n'est recalculé ; ensuite seules les organisations corrigées et leurs
    totaux au-dessus le sont. Faux = « recalculer avec l'organisation d'aujourd'hui » (comportement d'avant,
    défaut de cette fonction ; l'écran propose « garder » par défaut). Le choix est écrit au journal
    (``mode_reouverture``) et vaut jusqu'à la nouvelle clôture. À la première réouverture, le périmètre de la période
    est gelé (``calcul.geler_perimetre``)."""
    departs, arrivee, cle_message = TRANSITIONS[action]
    if c.statut not in departs:
        raise ValidationError(libelle("admin.campagne.erreur.action_impossible", statut=LB.choix(c, "statut")))
    from . import calcul as C

    avant = c.statut
    reouverture = action in ("rouvrir", "rouvrir_contributeurs") and avant == Campagne.Statut.CLOTUREE
    # chiffres importés tels quels sur des cases calculées, pas encore officiels : la clôture peut les rendre officiels
    en_attente = C.importes_en_attente(c.periode) if action == "cloturer" else set()
    etait_figee = reouverture and C.figee(c.periode)
    arbre_avant = None  # arbre de la clôture de la période, que suivaient les KPI des autres campagnes clôturées
    if etait_figee:
        C.geler_perimetre(c.periode)  # un KPI ou un modèle ajouté depuis n'y crée pas de case
        # arbre des organisations de l'époque : « garder » le suit (noté maintenant s'il ne
        # l'a jamais été) ; « recalculer » l'efface, la clôture suivante notera celui de ce jour
        if not garder:
            arbre_avant = C.arbre_fige(c.periode)
            C.oublier_arbre(c.periode)
        elif C.arbre_fige(c.periode) is None:
            C.noter_arbre(c.periode)
    c.statut = arrivee
    if action == "cloturer":
        c.chiffres_gardes = False  # le choix de la réouverture vaut jusqu'à la nouvelle clôture
    elif etait_figee:
        c.chiffres_gardes = garder
    c.save(update_fields=["statut", "chiffres_gardes"])
    Journal.ecrire(utilisateur, action, c, "statut", avant, c.statut)
    if action == "cloturer":  # première clôture de la période : son périmètre est noté (``calcul.perimetre_gele``)
        C.geler_a_la_cloture(c.periode)
    if etait_figee:
        Journal.ecrire(utilisateur, "mode_reouverture", c, "chiffres", "", "gardes" if garder else "recalcules")
        if not garder:  # le choix vaut pour toute la période : les autres campagnes rouvertes de la période suivent
            for autre in Campagne.objects.filter(periode=c.periode, chiffres_gardes=True).exclude(pk=c.pk):
                autre.chiffres_gardes = False
                autre.save(update_fields=["chiffres_gardes"])
                Journal.ecrire(utilisateur, "mode_reouverture", autre, "chiffres", "gardes", "recalcules")
    # règle « Figer ses chiffres » : tant qu'une autre campagne de la période n'est pas clôturée, les KPI
    # que demande une campagne clôturée gardent leurs chiffres (``calcul.noter_figes_partiels``) ; une campagne rouverte
    # rend les siens au calcul, sauf ceux qu'une autre campagne clôturée demande aussi
    C.noter_figes_partiels(c.periode, arbre_avant)
    # « le calcul doit être à jour » (18/11/2026) : un chiffre importé devenu officiel par cette clôture est lu aussitôt
    # par les périodes ouvertes qui le citent ; la période clôturée n'est pas réécrite
    C.rendre_officiels(c.periode, en_attente)
    if reouverture and not (etait_figee and garder):
        # la période n'est plus figée : rattraper ce qui a changé pendant la clôture (sous-périodes, organisations,
        # formules) ; « garder les chiffres de l'époque » : rien n'est recalculé
        C.recalculer(c)
    return libelle(cle_message)


# ---------------------------------------------------------------- organisations
def _nom_avec_niveau(o):
    """« Exemplia Recyclage (filiale) » dans la liste des parents ; sans répéter le niveau quand le nom le porte déjà
    (« Exemplia (Groupe) », pas « Exemplia (Groupe) (groupe) »)."""
    return o.nom if nom_porte_niveau(o) else f"{o.nom} ({o.niveau})"


class OrganisationForm(forms.ModelForm):
    class Meta:
        model = Organisation
        fields = ["nom", "code", "nom_court", "niveau", "parent", "rang", "type_site", "actif", "date_desactivation",
                  "date_ouverture"]
        labels = {"code": _l("admin.organisation.form.code"), "nom_court": _l("admin.organisation.form.nom_court"),
                  "parent": _l("admin.organisation.form.parent"), "rang": _l("admin.organisation.form.rang"),
                  "type_site": _l("admin.organisation.form.type_site"), "actif": _l("admin.organisation.form.actif")}
        help_texts = {"code": _l("admin.organisation.form.code_aide"),
                      "nom_court": _l("admin.organisation.form.nom_court_aide"),
                      "rang": _l("admin.organisation.form.rang_aide")}
        widgets = {"date_desactivation": forms.DateInput(attrs={"type": "date", "aria-describedby": "aide-fermeture"}, format="%Y-%m-%d"),
                   "date_ouverture": forms.DateInput(attrs={"type": "date", "aria-describedby": "aide-ouverture"}, format="%Y-%m-%d")}
        # nom déjà pris : message de l'outil, pas celui de Django (« Un objet Organisation avec ce champ… »)
        error_messages = {"nom": {"unique": _l("admin.organisation.erreur.nom_pris")}}

    # date d'ouverture après des valeurs déjà saisies : enregistrée seulement après confirmation
    confirmer_ouverture = forms.BooleanField(required=False)

    def full_clean(self):
        """Champ refusé (accessibilité) : ``aria-invalid`` et ``aria-describedby`` vers son message
        (``err-<champ>`` dans le gabarit) ; le script des pages y met le focus après l'envoi refusé."""
        super().full_clean()
        for nom in self.errors:
            if nom in self.fields:
                w = self.fields[nom].widget
                w.attrs["aria-invalid"] = "true"
                w.attrs["aria-describedby"] = " ".join(x for x in (w.attrs.get("aria-describedby", ""), f"err-{nom}") if x)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.valeurs_avant_ouverture = 0
        self.fields["parent"].queryset = Organisation.objects.select_related("niveau").exclude(pk=self.instance.pk)
        self.fields["parent"].label_from_instance = _nom_avec_niveau
        LB.traduire_choix(self)
        self.fields["parent"].required = False
        self.fields["type_site"].choices = [("", libelle("admin.organisation.type_non_precise"))] + [
            (v, LB.choix_valeur(Organisation, "type_site", v)) for v, _ in Organisation.TypeSite.choices]

    def clean_code(self):
        from referentiel.models import normaliser_code

        code = normaliser_code(self.cleaned_data.get("code"))
        if code and Organisation.objects.exclude(pk=self.instance.pk).filter(code=code).exists():
            raise forms.ValidationError(libelle("admin.organisation.erreur.code_pris", code=code))
        return code

    def clean(self):
        d = super().clean()
        bas = N.le_plus_bas()
        if not d.get("niveau") or not bas or d["niveau"].pk != bas.pk:
            d["type_site"] = ""  # le type ne concerne que le niveau le plus bas (les sites)
        if d.get("actif", True):
            d["date_desactivation"] = None  # active : pas de date de fermeture
        elif d.get("date_desactivation") and d["date_desactivation"] > timezone.localdate():
            self.add_error("date_desactivation", libelle("admin.organisation.erreur.date_future"))
        if self.instance.pk and not d.get("actif", True):
            # une organisation collectée sous une organisation qui ne l'est plus serait demandée sans compter dans les totaux
            actives = list(self.instance.enfants.filter(actif=True).order_by("rang", "nom").values_list("nom", flat=True))
            if actives:
                noms = ", ".join(actives[:3])
                if len(actives) > 3:
                    noms = libelle("admin.organisation.erreur.et_autres", noms=noms, n=len(actives) - 3)
                self.add_error(None, libelle("admin.organisation.erreur.enfants_actifs", n=len(actives), noms=noms))
        parent = d.get("parent")
        if d.get("actif", True) and parent is not None and not parent.actif:
            # l'inverse : une organisation collectée sous une organisation qui ne l'est plus (rouverte, créée, déplacée)
            self.add_error("parent", libelle("admin.organisation.erreur.parent_ferme", parent=parent.nom))
        self._controler_ouverture(d)
        return d

    def _controler_ouverture(self, d):
        """Date d'ouverture : pas après la date de fermeture ; après des valeurs déjà saisies
        ou importées de l'organisation (sur des périodes qui finissent avant cette date), elles ne compteraient plus dans
        aucun total : la fiche le dit et n'enregistre qu'avec la case « Je confirme » cochée (choix le plus prudent :
        ni refus définitif, ni perte en silence)."""
        debut = d.get("date_ouverture")
        # date de fermeture qui sera enregistrée : laissée vide pour une organisation désactivée, c'est aujourd'hui
        # (vue ``organisation``) ; avant, une ouverture future passait, puis restait après la fermeture 
        fin = d.get("date_desactivation") or (timezone.localdate() if not d.get("actif", True) else None)
        if debut and fin and debut > fin:
            self.add_error("date_ouverture", libelle("admin.organisation.erreur.ouverture_apres_fermeture"))
            return
        if not self.instance.pk or "parent" in self.errors:
            return
        from django.db.models import Q

        from .models import Reponse

        # une organisation n'est pas ouverte avant son parent (``calcul.ouverte``) : la date qui
        # compte est la plus tardive de la sienne et de celles de ses ancêtres, avant et après l'enregistrement (date
        # changée, ou organisation rattachée sous une organisation ouverte plus tard) ; elle vaut aussi pour les
        # organisations en dessous, dont les valeurs sont comptées dans l'avertissement
        arbre = {o.id: o for o in Organisation.objects.only("id", "nom", "parent_id", "date_ouverture")}

        def effective(propre, parent_id):
            date, source, x, vus = propre, None, arbre.get(parent_id), set()
            while x is not None and x.id not in vus:
                vus.add(x.id)
                if x.date_ouverture and (date is None or x.date_ouverture > date):
                    date, source = x.date_ouverture, x
                x = arbre.get(x.parent_id)
            return date, source

        parent = d.get("parent")
        nouvelle, source = effective(debut, parent.pk if parent is not None else None)
        ancienne, _ = effective(self.instance.date_ouverture, self.instance.parent_id)
        if nouvelle is None or (ancienne is not None and nouvelle <= ancienne):
            return  # aucune valeur ne sort des totaux qu'elle ne quittait déjà
        enfants = defaultdict(list)
        for o in arbre.values():
            enfants[o.parent_id].append(o.id)
        ids, pile = set(), [self.instance.pk]
        while pile:
            x = pile.pop()
            if x not in ids:
                ids.add(x)
                pile.extend(enfants.get(x, ()))
        avant = (Reponse.objects.filter(organisation_id__in=ids, periode__fin__lt=nouvelle,
                                        origine__in=[Reponse.Origine.SAISIE, Reponse.Origine.IMPORT, Reponse.Origine.FORCEE])
                 .filter(Q(valeur__isnull=False) | Q(non_applicable=True) | ~Q(texte="")))
        n = avant.count()
        if n and not d.get("confirmer_ouverture"):
            self.valeurs_avant_ouverture = n
            premiere = avant.order_by("periode__debut").select_related("periode").first().periode
            if source is not None:  # date d'un ancêtre : l'organisation est rattachée sous une organisation ouverte plus tard
                self.add_error("parent", libelle("admin.organisation.erreur.valeurs_avant_ouverture_parent", n=n,
                                                 parent=source.nom, date=DC.date_courte(nouvelle),
                                                 periode=str(premiere)))
            elif avant.exclude(organisation_id=self.instance.pk).exists():
                self.add_error("date_ouverture", libelle("admin.organisation.erreur.valeurs_avant_ouverture_dessous", n=n,
                                                         periode=str(premiere)))
            else:
                self.add_error("date_ouverture", libelle("admin.organisation.erreur.valeurs_avant_ouverture", n=n,
                                                         periode=str(premiere)))


@login_required
def formules(request):
    """Formules à corriger : KPI calculés dont la formule est cassée, et cases en erreur au calcul."""
    exiger_admin(request)
    from . import formules as FM

    return render(request, "collecte/administration/formules.html", {
        "page": "administration", "rubrique": "referentiels",
        "dans_la_formule": FM.dans_la_formule(), "au_calcul": FM.au_calcul()})


@login_required
def organisations(request):
    exiger_admin(request)
    arbre = S.arbre_organisations()
    nb_attr = dict(Attribution.objects.values_list("organisation_id").annotate(n=Count("id")))
    alias = {}
    for a in OrgAlias.objects.all():
        alias.setdefault(a.organisation_id, []).append(a)
    orgs = sorted(arbre.values(), key=S.cle_arbre)
    nb_enfants = {}
    for o in orgs:
        o.nb_attributions, o.liste_alias = nb_attr.get(o.id, 0), alias.get(o.id, [])
        o.ids_ancetres = " ".join(str(a.id) for a in o.ancetres())
        for a in o.ancetres():
            nb_enfants[a.id] = nb_enfants.get(a.id, 0) + 1
    tous = N.tous()
    niveaux = []
    for i, n in enumerate(tous):
        du_niveau = [o for o in orgs if o.niveau_id == n.code]
        niveaux.append({"code": n.code, "libelle": n.tr("nom_pluriel"), "libelle_un": n.tr("nom"), "total": len(du_niveau), "inactives": sum(not o.actif for o in du_niveau),
                        "enfant": tous[i + 1] if i + 1 < len(tous) else None})
    enfant_de = {n["code"]: n["enfant"] for n in niveaux}
    bas = tous[-1].code if tous else None
    pas_que_bas = set()  # organisations qui ont au moins un descendant au-dessus du niveau le plus bas
    for o in orgs:
        if o.niveau_id != bas:
            pas_que_bas.update(a.id for a in o.ancetres())
    for o in orgs:
        o.nb_descendants = nb_enfants.get(o.id, 0)
        o.niveau_enfant = enfant_de.get(o.niveau_id)
        o.que_bas = o.nb_descendants and o.id not in pas_que_bas  # « Sans les sites » : replier ces organisations
    return render(request, "collecte/administration/organisations.html", {
        "page": "administration", "rubrique": "organisations", "orgs": orgs, "campagne": S.campagne_courante(), "niveaux": niveaux,
        "chaine_niveaux": " → ".join(n.tr("nom_pluriel") for n in reversed(tous)),
        "nb_orgs": len(orgs), "nb_inactives": sum(not o.actif for o in orgs),
    })


@login_required
def organisations_plusieurs(request):
    """Plusieurs organisations d'un coup : saisie rapide décalée ou collage depuis Excel, aperçu puis création."""
    from parametres import mise_en_place as M

    exiger_admin(request)
    niveaux = N.tous()
    texte, noeuds, erreurs = request.POST.get("arbre", ""), [], []
    if request.method == "POST":
        noeuds, erreurs = M.lire_arbre(texte, niveaux)
        if request.POST.get("action") == "creer" and not erreurs and noeuds:
            n = M.creer_arbre(request.user, noeuds)
            if n:
                from .calcul import recalculer_en_cours

                recalculer_en_cours()  # une organisation de plus : les totaux au-dessus d'elle changent
            messages.success(request, libelle("admin.organisations_plusieurs.creees", n=n) if n
                             else libelle("admin.organisations_plusieurs.aucune_nouvelle"))
            return redirect("collecte:admin_organisations")
    return render(request, "collecte/administration/organisations_plusieurs.html", {
        "page": "administration", "rubrique": "organisations", "niveaux": niveaux, "texte_arbre": texte,
        "noms_niveaux": ", ".join(n.nom for n in niveaux),
        "noeuds_lus": noeuds, "erreurs_arbre": erreurs, "exemple_arbre": M.exemple_arbre(niveaux),
        "limite_arbre": M.MAX_ORGANISATIONS_COLLEES})


@login_required
def organisation(request, org_id=None):
    """Fiche organisation : nom, niveau, rattachement, activité ; libellés externes (alias) pour les imports."""
    exiger_admin(request)
    o = get_object_or_404(Organisation, pk=org_id) if org_id else Organisation()
    initial = {}
    if not o.pk and request.GET.get("parent"):
        parent = get_object_or_404(Organisation, pk=identifiant(request.GET["parent"]))
        enfant = N.tous_sous(parent.niveau)[:1]
        initial = {"parent": parent, "niveau": enfant[0].code if enfant else None}
    form = OrganisationForm(instance=o, initial=initial)
    succes, erreur = "", ""
    if request.method == "POST":
        action = request.POST.get("action", "enregistrer")
        if action == "enregistrer":
            # une copie : si la fiche est refusée, l'en-tête garde l'état enregistré (active, rattachement)
            form = OrganisationForm(request.POST, instance=Organisation.objects.get(pk=o.pk) if o.pk else o)
            if form.is_valid():
                nouvelle = not o.pk
                avant = {f: form.initial.get(f) for f in form.changed_data if f != "confirmer_ouverture"}
                o = form.save(commit=False)
                if not o.actif and not o.date_desactivation:
                    o.date_desactivation = timezone.localdate()  # date laissée vide : fermée aujourd'hui
                o.save()
                if ({"actif", "parent", "niveau", "date_desactivation", "date_ouverture"} & set(form.changed_data)
                        and not (nouvelle and not o.parent_id)):
                    from .calcul import recalculer_en_cours

                    recalculer_en_cours()  # les totaux au-dessus changent : les refaire tout de suite
                noms = {n.code: n.nom for n in N.tous()}
                for champ, valeur in avant.items():
                    apres = getattr(o, champ)
                    if champ == "niveau":  # le niveau s'écrit par son nom
                        valeur, apres = noms.get(valeur, valeur), apres.nom
                    Journal.ecrire(request.user, "creation_organisation" if nouvelle else "reglage_organisation", o, champ, valeur, apres)
                succes = libelle("admin.organisation.creee") if nouvelle else libelle("admin.organisation.enregistree")
                form = OrganisationForm(instance=o)
        elif action == "ajouter_alias" and o.pk:
            texte_alias = request.POST.get("libelle", "").strip()
            source = request.POST.get("source", "").strip() or "Fichier"  # source notée dans la base : contenu, pas un texte de l'interface
            if not texte_alias:
                erreur = libelle("admin.organisation.erreur.alias_vide")
            elif OrgAlias.objects.filter(source=source, libelle=texte_alias).exists():
                erreur = libelle("admin.organisation.erreur.alias_pris", libelle=texte_alias, source=source)
            else:
                OrgAlias.objects.create(organisation=o, source=source, libelle=texte_alias)
                Journal.ecrire(request.user, "ajout_alias", o, "alias", "", f"{texte_alias} ({source})")
                succes = libelle("admin.organisation.alias_ajoute")
        elif action == "retirer_alias" and o.pk:
            a = get_object_or_404(OrgAlias, pk=request.POST.get("alias"), organisation=o)
            Journal.ecrire(request.user, "retrait_alias", o, "alias", f"{a.libelle} ({a.source})", "")
            a.delete()
            succes = libelle("admin.organisation.alias_retire")
        if not est_script(request) and succes:
            return redirect("collecte:admin_organisations")
    return _panneau(request, "collecte/administration/_organisation.html", {
        "titre_page": libelle("admin.organisation.titre_page", nom=o.nom) if o.pk else libelle("admin.organisation.nouvelle"), "o": o, "form": form, "succes": succes, "erreur": erreur, "alias": o.alias.all() if o.pk else [],
        "enfants": o.enfants.all() if o.pk else [], "nb_reponses": o.reponses.count() if o.pk else 0,
        "nb_attributions": o.attributions.count() if o.pk else 0, "parents": _parents_possibles(o),
        "niveaux": _niveaux_fiche(), "niveau_choisi": form["niveau"].value(), "parent_choisi": str(form["parent"].value() or ""),
        "niveau_bas": getattr(N.le_plus_bas(), "code", ""),
    })


def _niveaux_fiche():
    """Niveaux avec, pour l'aide de la fiche, les niveaux auxquels se rattacher (« Pays ou Groupe »)."""
    niveaux = N.tous()
    for i, n in enumerate(niveaux):
        dessus = [m.nom for m in reversed(niveaux[:i])]
        if len(dessus) > 2:
            n.dessus = libelle("admin.organisation.ou", debut=", ".join(dessus[:-1]), fin=dessus[-1])
        elif len(dessus) == 2:
            n.dessus = libelle("admin.organisation.ou", debut=dessus[0], fin=dessus[1])
        else:
            n.dessus = dessus[0] if dessus else ""
    return niveaux


def _parents_possibles(o):
    """Organisations auxquelles se rattacher (tout sauf le niveau le plus bas et elle-même), dans l'ordre de l'arbre.

    Le choix se restreint ensuite selon le niveau choisi : seulement les niveaux supérieurs (rattachement souple)."""
    arbre = S.arbre_organisations()
    bas = N.le_plus_bas()
    return [p for p in sorted(arbre.values(), key=S.cle_arbre) if p.niveau_id != getattr(bas, "code", None) and p.pk != o.pk]


# ---------------------------------------------------------------- comptes
class _RolesExpliques:
    """Les rôles avec leur explication, [(code, nom, explication)], dans la langue de la personne à chaque lecture."""

    CODES = (Utilisateur.Role.CONTRIBUTEUR, Utilisateur.Role.VALIDATEUR, Utilisateur.Role.ADMIN, Utilisateur.Role.LECTEUR,
             Utilisateur.Role.AUDITEUR)

    def liste(self):
        return [(c, LB.choix_valeur(Utilisateur, "role", c), libelle(f"admin.roles.aide.{c}")) for c in self.CODES]

    def __iter__(self):
        return iter(self.liste())

    def __len__(self):
        return len(self.CODES)

    def __getitem__(self, i):
        return self.liste()[i]


ROLES_EXPLIQUES = _RolesExpliques()


class CompteForm(forms.ModelForm):
    """Comptes créés et gérés par l'administrateur (pas de SSO). Le mot de passe provisoire est généré à la création."""

    mot_de_passe = forms.CharField(label=_l("admin.compte.form.mot_de_passe"), required=False, strip=False,
                                   widget=forms.TextInput(attrs={"autocomplete": "off", "placeholder": _l("admin.compte.form.mot_de_passe_placeholder")}),
                                   help_text=_l("admin.compte.form.mot_de_passe_aide"))

    class Meta:
        model = Utilisateur
        fields = ["first_name", "last_name", "email", "equipe", "role", "perimetre_lecture", "is_active"]
        labels = {"first_name": _l("admin.compte.form.prenom"), "last_name": _l("admin.compte.form.nom"),
                  "email": _l("admin.compte.form.email"), "equipe": _l("admin.compte.form.equipe"),
                  "is_active": _l("admin.compte.form.actif"), "perimetre_lecture": _l("admin.compte.form.perimetre")}
        widgets = {"role": forms.RadioSelect}

    # passage en lecture seule d'un compte qui a des attributions : elles seront retirées,
    # après une confirmation qui annonce leur nombre (case montrée seulement dans ce cas)
    confirmer_retrait = forms.BooleanField(required=False)
    # gestionnaire des espaces qui ne sera plus administrateur actif de l'espace principal : il perd ce rôle,
    # après une confirmation (case montrée seulement dans ce cas)
    confirmer_gestionnaire = forms.BooleanField(required=False)
    gestionnaire_perdu = False

    compte_existant = None
    retrait_a_confirmer = 0  # nombre d'attributions retirées à l'enregistrement (0 : aucune)

    def __init__(self, *args, moi=None, **kwargs):
        super().__init__(*args, **kwargs)
        LB.traduire_choix(self)
        self.moi = moi
        self.identite_verrouillee = []  # autres espaces du compte, si l'identité est hors des droits de « moi »
        if self.instance.pk and moi is not None:
            from espaces import comptes as EC

            if not EC.peut_modifier_identite(self.instance.pk, moi.pk):
                self.identite_verrouillee = EC.partage_ailleurs(self.instance.pk) or ["autre"]
                for nom in ("first_name", "last_name", "email"):
                    self.fields[nom].disabled = True
        self.fields["email"].required = True
        self.fields["email"].error_messages["invalid"] = EMAIL_INVALIDE
        self.fields["first_name"].required = True
        self.fields["last_name"].required = True
        if self.instance.pk:
            del self.fields["mot_de_passe"]  # sur un compte existant : bouton « Réinitialiser »
        orgs = sorted(S.arbre_organisations().values(), key=S.cle_arbre)
        champ = self.fields["perimetre_lecture"]
        champ.required = False
        champ.queryset = Organisation.objects.filter(actif=True)
        champ.choices = [(o.pk, "\u00a0\u00a0" * o.prof + o.nom) for o in orgs if o.actif]
        champ.widget.attrs.update({"size": min(10, max(4, len(champ.choices)))})

    def clean_perimetre_lecture(self):
        """Toutes les organisations cochées = aucune restriction (vide) : les nouvelles organisations suivront."""
        choisies = self.cleaned_data.get("perimetre_lecture")
        if choisies is not None and choisies.count() and choisies.count() >= Organisation.objects.filter(actif=True).count():
            return Organisation.objects.none()
        return choisies

    def clean_email(self):
        from espaces.models import Compte

        email = self.cleaned_data["email"].strip().lower()
        if Utilisateur.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise ValidationError(libelle("admin.compte.erreur.email_pris"))
        if self.instance.pk and Compte.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise ValidationError(libelle("admin.compte.erreur.email_pris"))  # registre commun (autre espace)
        if not self.instance.pk:  # personne qui a déjà un compte dans un autre espace : rattachée, sans mot de passe
            self.compte_existant = Compte.objects.filter(email__iexact=email).first()
        return email

    def clean(self):
        d = super().clean()
        # Toujours au moins un administrateur actif : on ne retire ni son propre rôle
        # d'administrateur ni son propre accès, et aucun changement ne laisse l'installation sans administrateur actif.
        # L'ancienne règle ne visait pas les administrateurs (ils ont aussi is_superuser) : la faille est fermée ici.
        avant = Utilisateur.objects.filter(pk=self.instance.pk).first() if self.instance.pk else None
        if avant is not None and avant.est_admin and avant.is_active:
            role = d.get("role") or avant.role
            reste_admin = bool(d.get("is_active")) and (role == Utilisateur.Role.ADMIN
                                                        or (avant.is_superuser and role == avant.role))
            if not reste_admin:
                if avant.pk == getattr(self.moi, "pk", None):
                    raise ValidationError(libelle("admin.compte.erreur.propre_compte" if not d.get("is_active")
                                                  else "admin.compte.erreur.propre_role"))
                if not admins_actifs().exclude(pk=avant.pk).exists():
                    raise ValidationError(libelle("admin.compte.erreur.dernier_admin"))
        # un lecteur ou un auditeur ne saisit ni ne valide rien : ses attributions sont retirées avec le changement de rôle
        # la fiche le dit et demande de confirmer (revenir au rôle d'avant ne les rétablit pas)
        if avant is not None and "role" in self.changed_data and d.get("role") in Utilisateur.ROLES_LECTURE:
            from . import attributions_lecture_seule as ALS

            nc, nv = ALS.nombres(avant)
            self.retrait_a_confirmer = nc + nv
            if self.retrait_a_confirmer and not d.get("confirmer_retrait"):
                raise ValidationError(libelle("admin.compte.retrait.confirmer_requis", n=nc + nv, nc=nc, nv=nv, nom=str(avant)))
        # gestionnaire des espaces (espaces.comptes.simuler, la règle de toutes les portes) : jamais sans gestionnaire
        # capable d'agir (refus) ; un gestionnaire qui n'est plus administrateur actif de l'espace principal perd ce
        # rôle, annoncé et confirmé avant l'enregistrement (case montrée seulement dans ce cas)
        if avant is not None and {"role", "is_active"} & set(self.changed_data):
            from espaces import comptes as EC

            role = d.get("role") or avant.role
            role = "admin" if role == Utilisateur.Role.ADMIN or (avant.is_superuser and role == avant.role) else role
            refus, self.gestionnaire_perdu = EC.simuler(avant.pk, code=ESP.code_courant(), role=role,
                                                        actif=bool(d.get("is_active")))
            if refus:
                raise ValidationError(refus)
            if self.gestionnaire_perdu and not d.get("confirmer_gestionnaire"):
                raise ValidationError(libelle("admin.compte.gestionnaire.perte_confirmer_requis", nom=str(avant)))
        mdp = d.get("mot_de_passe")
        if mdp and len(mdp) < 8:
            self.add_error("mot_de_passe", libelle("admin.compte.erreur.mdp_court"))
        elif mdp:  # mêmes règles que partout ailleurs (pas « 12345678 », pas le nom de la personne)
            from django.contrib.auth import password_validation

            try:
                password_validation.validate_password(mdp, self.instance)
            except ValidationError as e:
                self.add_error("mot_de_passe", e)
        return d

    def save(self, commit=True):
        u = super().save(commit=False)
        if not u.username:
            u.username = u.email
        admin = u.role == Utilisateur.Role.ADMIN
        u.is_staff = admin or u.is_superuser  # accès au mode expert
        if admin:
            u.is_superuser = True
        elif u.pk and u.is_superuser and "role" in self.changed_data:
            u.is_superuser = u.is_staff = False
        if commit:
            u.save()
            self.save_m2m()
        return u

    def _save_m2m(self):
        super()._save_m2m()
        u = self.instance
        if not u.lecture_seule and u.perimetre_lecture.exists():  # seuls le lecteur et l'auditeur en ont
            u.perimetre_lecture.clear()


def admins_actifs():
    """Comptes qui administrent l'outil et peuvent se connecter (rôle administrateur, ou compte technique de l'IT)."""
    return Utilisateur.admins().filter(is_active=True)


def supprimable(u, moi):
    """Un compte jamais utilisé (aucune connexion, attribution, saisie ni action) peut être supprimé ; sinon on le désactive."""
    return (u.pk != moi.pk and not u.last_login and not u.attributions.exists()
            and not Journal.objects.filter(utilisateur=u).exists()
            and not Reponse.objects.filter(Q(saisi_par=u) | Q(valide_par=u)).exists())


def rattache(u):
    """Compte créé dans cet espace pour une personne qui avait déjà un compte (registre commun) : pas de mot de passe
    provisoire, elle garde le sien."""
    return getattr(u, "_espaces_rattache", False)


def donner_mot_de_passe(u, mdp=None):
    from .compte import mot_de_passe_provisoire

    mdp = mdp or mot_de_passe_provisoire()
    u.set_password(mdp)
    u.doit_changer_mdp = True
    u.save(update_fields=["password", "doit_changer_mdp"])
    return mdp


@login_required
def comptes(request):
    exiger_admin(request)
    liste = Utilisateur.objects.annotate(
        nb_contrib=Count("attributions", filter=Q(attributions__role=Attribution.Role.CONTRIBUTEUR)),
        nb_valid=Count("attributions", filter=Q(attributions__role=Attribution.Role.VALIDATEUR)),
    ).order_by("-is_active", "first_name", "last_name", "email")
    liste = list(liste)
    from espaces.models import Compte

    # gestionnaires des espaces (registre commun) : étiquette à côté du rôle, visible de tout administrateur
    gestionnaires = set(Compte.objects.filter(gestionnaire=True).values_list("pk", flat=True))
    return render(request, "collecte/administration/comptes.html", {
        "page": "administration", "rubrique": "comptes", "comptes": liste, "campagne": S.campagne_courante(),
        "gestionnaires": gestionnaires,
        "nb_actifs": sum(u.is_active for u in liste), "nb_inactifs": sum(not u.is_active for u in liste),
        "nb_en_attente": sum(u.is_active and (u.doit_changer_mdp or u.last_login is None) for u in liste),  # comme la colonne « Connexion »
        "par_role": [(code, libelle(f"admin.comptes.filtre.{code}"), sum(u.role == code for u in liste)) for code, _, _ in ROLES_EXPLIQUES],
    })


@login_required
def comptes_plusieurs(request):
    """Plusieurs comptes d'un coup, chacun avec son message d'accès (mot de passe provisoire)."""
    from parametres import mise_en_place as M

    exiger_admin(request)
    crees, erreurs = [], []
    if request.method == "POST":
        with ESP.atomic():
            crees, erreurs = M.creer_comptes(request, NB_LIGNES_COMPTES)
    return render(request, "collecte/administration/comptes_plusieurs.html", {
        "page": "administration", "rubrique": "comptes", "roles": ROLES_EXPLIQUES, "lignes": range(NB_LIGNES_COMPTES),
        "crees": crees, "erreurs": erreurs, "post": request.POST if erreurs else {}, "adresse": request.build_absolute_uri(reverse("collecte:accueil"))})


NB_LIGNES_COMPTES = 10


@login_required
def compte(request, user_id=None):
    """Fiche compte : identité, rôle, accès ; mot de passe provisoire à la création ou à la réinitialisation."""
    exiger_admin(request)
    u = get_object_or_404(Utilisateur, pk=user_id) if user_id else Utilisateur(is_active=True)
    form = CompteForm(instance=u, moi=request.user)
    succes, erreur, mdp_donne = "", "", None
    if request.method == "POST":
        action = request.POST.get("action", "enregistrer")
        if action == "enregistrer":
            form = CompteForm(request.POST, instance=u, moi=request.user)
            if form.is_valid():
                nouveau = not u.pk
                avant = {f: form.initial.get(f) for f in form.changed_data
                         if f not in ("mot_de_passe", "confirmer_retrait", "confirmer_gestionnaire")}
                retirees = 0
                try:
                    u, retirees = _enregistrer_compte(request, form, avant, nouveau)
                except EC.DernierGestionnaire as x:  # changé entre-temps : relu sous verrou à l'enregistrement
                    form.add_error(None, x.message)
                    u = Utilisateur.objects.get(pk=u.pk)  # l'en-tête montre le compte tel qu'il est resté
                else:
                    if nouveau and rattache(u):
                        succes = libelle("admin.compte.rattache")
                    elif nouveau:
                        mdp_donne = donner_mot_de_passe(u, form.cleaned_data.get("mot_de_passe"))
                        succes = libelle("admin.compte.cree")
                    else:
                        succes = libelle("admin.compte.enregistre")
                        if retirees:
                            succes += " " + libelle("admin.compte.retrait.fait", n=retirees)
                        if form.gestionnaire_perdu:
                            succes += " " + libelle("admin.compte.gestionnaire.perte_faite", nom=u)
                    form = CompteForm(instance=u, moi=request.user)
        elif action == "gestionnaire" and u.pk:
            # même écriture que la page Espaces (règle, verrou, historique) ; refus (403) à qui n'est pas gestionnaire
            fait, message = EC.changer_gestionnaire(request.user, u.pk, request.POST.get("valeur") == "1")
            succes, erreur = (message, "") if fait else ("", message)
        elif action == "reinitialiser" and u.pk and form.identite_verrouillee:
            erreur = identite_verrouillee_message(form.identite_verrouillee)
        elif action == "reinitialiser" and u.pk:
            mdp_donne = donner_mot_de_passe(u)
            Journal.ecrire(request.user, "mot_de_passe", u, "mot de passe", "", "(réinitialisé)")
            succes = libelle("admin.compte.mdp_reinitialise")
        elif action == "supprimer" and u.pk:
            if supprimable(u, request.user):
                try:
                    with ESP.atomic():
                        Journal.ecrire(request.user, "suppression_compte", u, "e-mail", u.email, "")
                        u.delete()
                except EC.DernierGestionnaire as x:
                    erreur = x.message
                else:
                    if est_script(request):
                        return JsonResponse({"html": render_to_string("collecte/administration/_compte_supprime.html", {}, request=request), "ok": True})
                    return redirect("collecte:admin_comptes")
            else:
                erreur = libelle("admin.compte.erreur.deja_servi")
        if not est_script(request) and succes and not mdp_donne:
            return redirect("collecte:admin_comptes")
    nb_spoc = u.attributions.filter(role=Attribution.Role.CONTRIBUTEUR).count() if u.pk else 0
    return _panneau(request, "collecte/administration/_compte.html", {
        "gestion": _gestion_espaces(u, request.user),
        "titre_page": libelle("admin.compte.titre_page", nom=u) if u.pk else libelle("admin.compte.nouveau"), "u": u, "form": form, "succes": succes, "erreur": erreur, "mdp_donne": mdp_donne, "roles": ROLES_EXPLIQUES,
        "role_choisi": form["role"].value(), "nb_spoc": nb_spoc,
        "nb_valid": u.attributions.filter(role=Attribution.Role.VALIDATEUR).count() if u.pk else 0,
        "supprimable": u.pk and supprimable(u, request.user), "adresse": request.build_absolute_uri(reverse("collecte:accueil")),
        "moi": u.pk == request.user.pk, "perimetre": _arbre_perimetre(form),
        "identite_verrouillee": identite_verrouillee_message(form.identite_verrouillee) if form.identite_verrouillee else "",
    })


def _enregistrer_compte(request, form, avant, nouveau):
    """Compte enregistré avec ses lignes d'historique et, au passage en lecture seule, le retrait des attributions :
    tout ou rien (refus ``DernierGestionnaire`` compris). Renvoie (compte, attributions retirées)."""
    retirees = 0
    with ESP.atomic():  # rôle et retrait des attributions (passage en lecture seule) : tout ou rien
        u = form.save()
        for champ, valeur in avant.items():
            apres = getattr(u, champ)
            if champ == "perimetre_lecture":  # organisations consultées : leurs noms (aucune = toutes)
                valeur = ", ".join(str(o) for o in valeur or []) or "toutes"
                apres = ", ".join(str(o) for o in u.perimetre_lecture.all()) or "toutes"
            Journal.ecrire(request.user, "creation_compte" if nouveau else "reglage_compte", u, champ,
                           "" if nouveau else valeur, apres)
        if not nouveau and u.lecture_seule and "role" in form.changed_data:
            from . import attributions_lecture_seule as ALS

            retirees = ALS.retirer(request.user, u)  # relues sous verrou : toutes celles d'aujourd'hui
    return u, retirees


def _gestion_espaces(u, moi):
    """Encadré « Administrateur ou gestionnaire des espaces » de la fiche : montré pour un administrateur de l'espace
    ou un gestionnaire des espaces (None : pas d'encadré). Boutons seulement pour un gestionnaire des espaces
    (``espaces.comptes.changer_gestionnaire`` refuse tout autre envoi) : « Nommer » pour un administrateur actif de
    l'espace principal (``admin_actif_principal``, la règle de l'envoi), « Retirer » pour tout gestionnaire, sauf
    soi-même. ``ancien`` : gestionnaire d'avant la règle, qui n'est pas administrateur actif de l'espace principal (il
    garde le rôle jusqu'au prochain changement de son rôle ou de son état)."""
    from espaces.models import Compte

    if not u.pk:
        return None
    c = Compte.objects.filter(pk=u.pk).values("gestionnaire", "actif").first() or {"gestionnaire": False, "actif": False}
    if not (u.est_admin or c["gestionnaire"]):
        return None
    peut, soi, eligible = EC.est_gestionnaire(moi), u.pk == moi.pk, EC.admin_actif_principal(u.pk)
    return {"est": c["gestionnaire"], "peut": peut, "soi": soi, "ancien": c["gestionnaire"] and not eligible,
            "pas_eligible": peut and not c["gestionnaire"] and not eligible,
            "nommer": peut and not c["gestionnaire"] and eligible,
            "retirer": peut and c["gestionnaire"] and not soi}


def _arbre_perimetre(form):
    """Organisations consultées (lecteur, auditeur) : niveaux et arbre à cocher, comme le périmètre d'un export
    . Rien de choisi = toutes : tout est coché. [(organisation, retrait, ancêtres, cochée)]."""
    orgs = [o for o in sorted(S.arbre_organisations().values(), key=S.cle_arbre) if o.actif]
    valeur = form["perimetre_lecture"].value() or []
    choisies = {int(v) for v in valeur if str(v).isdecimal()}
    ids = {o.id for o in orgs}
    lignes = []
    for o in orgs:
        ancetres = " ".join(str(a.id) for a in o.ancetres() if a.id in ids)
        lignes.append((o, 4 + 22 * o.prof, ancetres, not choisies or o.id in choisies))
    return {"orgs": lignes, "niveaux": [(n.code, n.nom) for n in N.tous() if any(o.niveau_id == n.code for o in orgs)]}


def identite_verrouillee_message(espaces):
    noms = [libelle("admin.compte.verrouille.nom_espace", nom=e) for e in espaces if e != "autre"]
    if not noms:
        return libelle("admin.compte.verrouille.autre")
    return libelle("admin.compte.verrouille.espaces", n=len(noms), espaces=", ".join(noms))


# ---------------------------------------------------------------- attributions (grille KPI × organisations)
def _spocs(kpi_ids, org_ids):
    """{(kpi_id, org_id): [utilisateurs actifs]} des SPOC (contributeurs)."""
    res = {}
    for a in (Attribution.objects.filter(kpi_id__in=kpi_ids, organisation_id__in=org_ids, role=Attribution.Role.CONTRIBUTEUR,
                                         utilisateur__is_active=True).select_related("utilisateur")):
        res.setdefault((a.kpi_id, a.organisation_id), []).append(a.utilisateur)
    return res


class _TextesGrille:
    """Libellés et bulles de la grille des attributions, préparés une fois par page : la grille d'un grand groupe a des
    dizaines de milliers de cases (échelle, P-A4), un gabarit inclus par case coûtait environ 0,25 ms chacune."""

    def __init__(self, role=Attribution.Role.CONTRIBUTEUR):
        from .templatetags.collecte import libelle_echappe

        self.echappe = libelle_echappe
        valid = role == Attribution.Role.VALIDATEUR  # choix Validateurs : mêmes cases, autres mots
        self.fixes = {k: libelle_echappe(f"admin.attributions.{c}", None, {}, False)
                      for k, c in (("attribuer", "attribuer"), ("aucun_spoc", "aucun_validateur" if valid else "aucun_spoc"),
                                   ("cliquer_modifier", "cliquer_modifier"))}
        self.cle_infobulle = "infobulle_titre_valid" if valid else "infobulle_titre"
        self.avatars = {}
        self.sans_case = {}

    def avatar(self, u):
        from .templatetags.collecte import avatar

        if u.pk not in self.avatars:
            self.avatars[u.pk] = avatar(u)
        return self.avatars[u.pk]

    def texte(self, cle, n=None, **valeurs):
        return self.echappe(f"admin.attributions.{cle}", n, valeurs, False)


def html_cellule_attr(kpi, org, spocs, textes=None, dessus=None):
    """Une case de la grille : le même HTML, octet pour octet, que l'ancien gabarit ``_cellule_attr.html`` (preuve :
    ``test_html_cellule_attr_equivalence.py``), écrit en Python pour la vitesse. ``spocs`` : personnes triées par nom.
    ``dessus`` (choix Validateurs seulement) : (organisation au-dessus, personnes) quand la case n'a pas de validateur
    à elle mais est couverte par celui d'une organisation au-dessus."""
    from django.utils.html import escape

    from .templatetags.collecte import prenom_initiale

    t = textes or _TextesGrille()
    if dessus and not spocs:
        return _html_cellule_dessus(kpi, org, dessus, t)
    p = ['<td class="cellule-attr', "" if spocs else " sans-spoc", '" data-cle="', escape(kpi.pk), "|", escape(org.pk),
         '" data-org="', escape(org.pk), '" data-spocs="', ",".join(str(u.id) for u in spocs),
         '"><div class="contenu-cellule">\n  <input type="checkbox" class="choix-case" aria-label="',
         t.texte("selectionner", kpi=kpi.code, organisation=org.nom), '">\n  <button type="button" class="bouton-spoc">']
    if spocs:
        p += ['<span class="etiquette-spoc">', t.avatar(spocs[0]), '<span class="nom-spoc">', escape(prenom_initiale(spocs[0])),
              "</span>"]
        if len(spocs) > 1:
            p += ['<span class="plus">+', str(len(spocs) - 1), "</span>"]
        p.append("</span>")
    else:
        p += ['<span class="a-attribuer">', t.fixes["attribuer"], "</span>"]
    p += ['<span class="visually-hidden"> – ', ", ".join(escape(str(u)) for u in spocs) if spocs else t.fixes["aucun_spoc"],
          "</span></button>\n  "]
    if spocs:
        p += ['<div class="liste-spocs" hidden>\n    <div class="titre-infobulle">',
              t.texte(t.cle_infobulle, n=len(spocs), organisation=org.nom), "</div>\n    "]
        p += ['<div class="ligne-infobulle">' + t.avatar(u) + "<span><b>" + escape(str(u)) + "</b><span>" + escape(u.email)
              + "</span></span></div>" for u in spocs]
        p += ['\n    <div class="pied-infobulle">', t.fixes["cliquer_modifier"], "</div>\n  </div>"]
    p.append("\n</div></td>")
    return "".join(p)


def _html_cellule_dessus(kpi, org, dessus, t):
    """Case du choix Validateurs couverte par le validateur d'une organisation au-dessus : « via France » ; la case
    reste cochable et cliquable (on peut lui donner son propre validateur), ``data-spocs`` vide (aucun à elle)."""
    from django.utils.html import escape

    haut, personnes = dessus
    noms = ", ".join(escape(str(u)) for u in personnes)
    p = ['<td class="cellule-attr par-dessus" data-cle="', escape(kpi.pk), "|", escape(org.pk), '" data-org="', escape(org.pk),
         '" data-spocs=""><div class="contenu-cellule">\n  <input type="checkbox" class="choix-case" aria-label="',
         t.texte("selectionner", kpi=kpi.code, organisation=org.nom), '">\n  <button type="button" class="bouton-spoc">',
         '<span class="via-dessus">', t.texte("via_dessus", organisation=haut.nom), "</span>",
         '<span class="visually-hidden"> – ', t.texte("dessus_lecteur", organisation=haut.nom, noms=noms), "</span></button>\n  ",
         '<div class="liste-spocs" hidden>\n    <div class="titre-infobulle">', t.texte("dessus_titre", organisation=haut.nom),
         "</div>\n    "]
    p += ['<div class="ligne-infobulle">' + t.avatar(u) + "<span><b>" + escape(str(u)) + "</b><span>" + escape(u.email)
          + "</span></span></div>" for u in personnes]
    p += ['\n    <div class="pied-infobulle">', t.texte("dessus_pied", organisation=org.nom), "</div>\n  </div>\n</div></td>"]
    return "".join(p)


def html_sans_case(kpi, org, textes):
    """Pas de case : KPI saisi, dans la colonne d'une organisation qui ne porte que les paramètres hérités (CALC-09).
    Même HTML que l'ancienne boucle du gabarit ``attributions.html``."""
    if kpi.pk not in textes.sans_case:
        textes.sans_case[kpi.pk] = textes.texte("sans_case", kpi=kpi.code, niveau=kpi.granularite)
    titre = textes.texte("sans_case_titre", kpi=kpi.code, niveau=kpi.granularite, organisation=org.nom)
    return (f'<td class="sans-case" title="{titre}"><span aria-hidden="true">·</span><span class="visually-hidden">'
            f"{textes.sans_case[kpi.pk]}</span></td>")


def cellule_html(request, kpi, org, role=Attribution.Role.CONTRIBUTEUR):
    """Une case de la grille (mise à jour après une attribution, depuis cette page ou la page Saisie)."""
    if role == Attribution.Role.VALIDATEUR:
        arbre = S.arbre_organisations()
        directs = _validateurs_directs([kpi.pk])
        org = arbre.get(org.pk, org)
        return html_cellule_attr(kpi, org, directs.get((kpi.pk, org.pk), []), _TextesGrille(role),
                                 _dessus(kpi.pk, org, directs, arbre))
    spocs = sorted(_spocs([kpi.pk], [org.pk]).get((kpi.pk, org.pk), []), key=str)
    return html_cellule_attr(kpi, org, spocs)


# ---------------------------------------------------------------- attributions de validateur (choix Validateurs)
# Une attribution de validateur porte sur un KPI et une organisation, et vaut aussi pour les organisations du dessous
# (``saisie.cellules``, ``saisie.role_sur``) ; elle montre aussi les totaux de ces organisations (``saisie.voit_calcules``).
# La grille du choix Validateurs a donc un onglet par niveau d'organisation, une ligne par KPI saisi à ce niveau ou en
# dessous ; une case est couverte par un validateur donné sur elle ou sur une organisation au-dessus.
def _validateurs_directs(kpi_ids):
    """{(kpi_id, org_id): [utilisateurs actifs, triés par nom]} des attributions de validateur."""
    res = {}
    for a in (Attribution.objects.filter(kpi_id__in=kpi_ids, role=Attribution.Role.VALIDATEUR, utilisateur__is_active=True)
              .select_related("utilisateur")):
        res.setdefault((a.kpi_id, a.organisation_id), []).append(a.utilisateur)
    for liste in res.values():
        liste.sort(key=str)
    return res


def _dessus(kpi_id, org, directs, arbre):
    """(organisation au-dessus la plus proche qui a un validateur pour ce KPI, ses validateurs) ou None."""
    p, vus = arbre.get(org.parent_id), set()
    while p is not None and p.pk not in vus:  # garde-fou : jamais de boucle, même sur un arbre abîmé
        vus.add(p.pk)
        if (kpi_id, p.pk) in directs:
            return p, directs[(kpi_id, p.pk)]
        p = arbre.get(p.parent_id)
    return None


def _couverture(directs, arbre):
    """{kpi_id: ensemble des organisations couvertes} : celles qui ont un validateur pour le KPI et leurs descendantes.
    Calculé une fois par ensemble d'organisations attribuées (souvent le même pour beaucoup de KPI : un validateur par
    pays pour tous les KPI)."""
    enfants = {}
    for o in arbre.values():
        enfants.setdefault(o.parent_id, []).append(o.pk)
    par_kpi = {}
    for k, o in directs:
        par_kpi.setdefault(k, set()).add(o)
    deja, sortie = {}, {}
    for k, haut in par_kpi.items():
        cle = frozenset(haut)
        if cle not in deja:
            vus, pile = set(), list(haut)
            while pile:
                i = pile.pop()
                if i not in vus:
                    vus.add(i)
                    pile.extend(enfants.get(i, ()))
            deja[cle] = vus
        sortie[k] = deja[cle]
    return sortie


# Grille d'un niveau qui a beaucoup d'organisations (échelle, P-A4) : au-delà de ce nombre de colonnes, la grille montre
# un groupe d'organisations à la fois (champ « Organisations » de la barre de filtres). Limite technique (taille de la
# page), comme MAX_ORGANISATIONS_COLLEES, pas un réglage fonctionnel.
MAX_COLONNES_ATTRIBUTIONS = 60


def groupes_colonnes_attr(orgs, arbre, maxi=None):
    """Découpe les colonnes (en ordre d'arbre) en groupes d'au plus ``maxi`` organisations, par branche de l'arbre : la
    branche la plus haute qui tient (pays, puis filiale…) ; les colonnes rattachées directement à une organisation trop
    grande sont regroupées à part, coupées en parties s'il le faut. [{"cle", "ancre", "entiere", "partie", "parties", "orgs",
    "chemin"}], dans l'ordre de l'arbre (``entiere`` : toute la branche de l'ancre ; sinon ses seules colonnes directes) ; la suite des
    groupes redonne toutes les colonnes, chacune une fois. [] : la grille tient en entier."""
    maxi = maxi or MAX_COLONNES_ATTRIBUTIONS
    if len(orgs) <= maxi:
        return []

    def chemin(o):
        c, p, vus = [], arbre.get(o.parent_id), set()
        while p is not None and p.pk not in vus:  # garde-fou : jamais de boucle, même sur un arbre abîmé
            vus.add(p.pk)
            c.append(p)
            p = arbre.get(p.parent_id)
        return c[::-1]  # de la racine au parent

    chemins = {o.pk: chemin(o) for o in orgs}
    groupes = []

    def couper(ancre, profondeur, cols):
        if len(cols) <= maxi:
            groupes.append({"ancre": ancre, "orgs": cols, "entiere": True})  # toute la branche
            return
        suites = []  # suites consécutives de colonnes de la même branche sous l'ancre (None : rattachées à l'ancre même)
        for o in cols:
            ch = chemins[o.pk]
            branche = ch[profondeur] if len(ch) > profondeur else None
            if suites and suites[-1][0] is branche:
                suites[-1][1].append(o)
            else:
                suites.append((branche, [o]))
        for branche, suite in suites:
            if branche is None:
                for i in range(0, len(suite), maxi):
                    groupes.append({"ancre": ancre, "orgs": suite[i:i + maxi], "entiere": False})  # rattachées à l'ancre
            else:
                couper(branche, profondeur + 1, suite)

    couper(None, 0, list(orgs))
    parties = {}
    for g in groupes:  # numéro de la partie quand une même ancre a plusieurs groupes
        cle = g["ancre"].pk if g["ancre"] is not None else 0
        parties[cle] = parties.get(cle, 0) + 1
        g["partie"] = parties[cle]
        g["cle"] = f"{cle}-{g['partie']}"
    for g in groupes:
        g["parties"] = parties[g["ancre"].pk if g["ancre"] is not None else 0]
        g["chemin"] = (chemin(g["ancre"]) + [g["ancre"]]) if g["ancre"] is not None else []
    return groupes


def _nom_selon_nombre(niveau, nombre):
    """Nom d'un niveau, au singulier ou au pluriel selon le nombre et la règle de la langue, dans la casse où il est écrit : un nom
    de niveau n'est jamais mis en minuscules (en allemand, un nom commun porte une majuscule)."""
    langue = LB.langue_effective()
    singulier = nombre < 2 if LB.zero_singulier(langue) else nombre == 1
    return niveau.tr("nom" if singulier else "nom_pluriel")


@login_required
def attributions(request):
    """Qui saisit quoi : une ligne par KPI, une colonne par organisation du niveau de saisie du KPI."""
    exiger_admin(request)
    from .views import comptes_json, plan_de

    arbre = S.arbre_organisations()
    plan = plan_de(request)  # attributions valables pour tous les référentiels ; le filtre limite les lignes affichées
    kpis = sorted((k for k in S.kpis_collectes() if plan.referentiel is None or plan.contient(k.code)),
                  key=lambda k: plan.position(k.code, k.ordre))
    role_attr = role_affiche(request)
    if role_attr == Attribution.Role.VALIDATEUR:
        return _attributions_validateurs(request, plan, kpis, arbre)
    # KPI calculés (case « responsables des résultats ») : affichés en plus, sans compter dans ce qui reste à attribuer
    if "calcules" in request.GET:
        request.session["attr_calcules"] = request.GET["calcules"] == "1"
    calcules = bool(request.session.get("attr_calcules"))
    resultats = sorted((k for k in KPI.objects.filter(actif=True, type_saisie__comportement="calcul")
                        if plan.referentiel is None or plan.contient(k.code)),
                       key=lambda k: plan.position(k.code, k.ordre)) if calcules else []
    niveaux = N.tous()
    rangs = {n.code: n.rang for n in niveaux}
    actives = [o for o in arbre.values() if o.actif]
    orgs_par_niveau = {n.code: sorted([o for o in actives if o.niveau_id == n.code], key=S.cle_arbre) for n in niveaux}
    # CALC-09 : une organisation sous un niveau, sans ancêtre de ce niveau, porte elle-même les paramètres hérités de ce
    # niveau ; elle a sa colonne dans l'onglet du niveau, avec une case pour ces seuls KPI
    orphelins = {n.code: porteurs_orphelins(n.code, actives, rangs, arbre) for n in niveaux}
    attribuees = set(Attribution.objects.filter(role=Attribution.Role.CONTRIBUTEUR, utilisateur__is_active=True)
                     .values_list("kpi_id", "organisation_id"))

    def colonnes(code, ks):
        """Organisations en colonnes de l'onglet d'un niveau : celles du niveau, et celles qui y portent un paramètre hérité."""
        if not any(k.est_herite for k in ks):
            return orgs_par_niveau[code]
        return sorted(orgs_par_niveau[code] + orphelins[code], key=S.cle_arbre)

    def a_une_case(k, o):
        return o.niveau_id == k.granularite_id or k.est_herite

    onglets = []
    for n in niveaux:  # un onglet par niveau
        ks = [k for k in kpis if k.granularite_id == n.code]
        os_ = colonnes(n.code, ks)
        cases = [(k, o) for k in ks for o in os_ if a_une_case(k, o)]
        total = len(cases)
        sans = sum((k.pk, o.pk) not in attribuees for k, o in cases)
        faites = total - sans
        du_niveau = len(orgs_par_niveau[n.code])
        onglets.append({"code": n.code, "libelle": n.tr("nom_pluriel"), "nb_kpi": len(ks), "nb_orgs": du_niveau, "total": total, "sans": sans,
                        "faites": faites, "pct": int(arrondi(100 * faites / total)) if total else 0,
                        "orgs_libelle": _nom_selon_nombre(n, du_niveau),
                        # « + 1 paramètre hérité × 1 organisation sans entité au-dessus » (CALC-09)
                        "nb_orphelins": len(os_) - du_niveau, "nb_herites": sum(1 for k in ks if k.est_herite),
                        "niveau_nom": n.tr("nom")})
    codes = [o["code"] for o in onglets]
    niveau = request.GET.get("niveau") or request.session.get("niveau_attr")
    if niveau not in codes:  # par défaut : le niveau qui a le plus de cases à attribuer (sinon le plus de cases)
        niveau = max(onglets, key=lambda o: (o["sans"], o["total"]))["code"] if onglets else ""
    request.session["niveau_attr"] = niveau
    ks = [k for k in kpis if k.granularite_id == niveau]
    orgs = colonnes(niveau, ks) if niveau in orgs_par_niveau else []
    lignes_kpi = sorted(ks + [k for k in resultats if k.granularite_id == niveau], key=lambda k: plan.position(k.code, k.ordre))
    personne = request.GET.get("personne", "")
    groupes_orgs, groupe, nb_colonnes = _groupe_affiche(request, niveau, orgs, arbre, personne)
    if groupe and groupe != TOUTES_COLONNES:
        orgs = next(g["orgs"] for g in groupes_orgs if g["cle"] == groupe)
    spocs = _spocs([k.pk for k in lignes_kpi], [o.pk for o in orgs])
    for o in orgs:
        o.hors_niveau = o.niveau_id != niveau  # porte seulement les paramètres hérités de ce niveau
        o.nb_kpi = sum(1 for k in ks if a_une_case(k, o))
        o.nb_sans = sum((k.pk, o.pk) not in spocs for k in ks if a_une_case(k, o))
        o.nb_faites = o.nb_kpi - o.nb_sans
        o.pct = int(arrondi(100 * o.nb_faites / o.nb_kpi)) if o.nb_kpi else 0
    groupes_colonnes = []
    if len({o.parent_id for o in orgs}) > 1:  # colonnes regroupées sous leur parent quand il y en a plusieurs
        for o in orgs:
            if groupes_colonnes and groupes_colonnes[-1][0] == o.parent:
                groupes_colonnes[-1][1] += 1
            else:
                groupes_colonnes.append([o.parent, 1])
    themes = []
    textes = _TextesGrille()
    for k in lignes_kpi:
        # None : pas de case (KPI saisi, dans la colonne d'une organisation qui ne porte que les paramètres hérités)
        ligne = {"kpi": k, "cellules": [(o, sorted(spocs.get((k.pk, o.pk), []), key=str) if a_une_case(k, o) else None) for o in orgs]}
        ligne["nb_sans"] = sum(c is not None and not c for _, c in ligne["cellules"])
        # les cases de la ligne, écrites d'un bloc (un gabarit inclus par case était l'essentiel du temps de la page)
        ligne["html_cellules"] = mark_safe("".join(html_sans_case(k, o, textes) if c is None else html_cellule_attr(k, o, c, textes)
                                                   for o, c in ligne["cellules"]))
        titre = plan.titres(k.code)[0]
        if themes and themes[-1][0] == titre:
            themes[-1][1].append(ligne)
        else:
            themes.append((titre, [ligne]))
    personnes = Utilisateur.ecrivains().filter(is_active=True) \
        .order_by("first_name", "last_name")
    return render(request, "collecte/administration/attributions.html", {
        "page": "administration", "rubrique": "attributions", "campagne": S.campagne_courante(), "onglets": onglets,
        "niveau": niveau, "orgs": orgs, "themes": themes, "groupes_colonnes": groupes_colonnes, "admin": True,
        "comptes_json": comptes_json(request), "personnes": personnes, "personne": personne,
        "onglet": next((o for o in onglets if o["code"] == niveau), None), "calcules": calcules,
        "groupes_orgs": groupes_orgs, "groupe": groupe, "groupe_defaut": groupes_orgs[0]["cle"] if groupes_orgs else "",
        "nb_colonnes": nb_colonnes, "toutes_colonnes": TOUTES_COLONNES, "role_attr": role_attr,
    })


TOUTES_COLONNES = "tout"


def role_affiche(request):
    """Choix « Contributeurs / Validateurs » de la page (champ « Attribuer » de la barre de filtres) : paramètre « role »
    de l'adresse (une valeur inconnue revient aux contributeurs), sinon le dernier choisi (session), sinon contributeurs."""
    valeurs = (Attribution.Role.CONTRIBUTEUR, Attribution.Role.VALIDATEUR)
    if "role" in request.GET:
        role = request.GET["role"] if request.GET["role"] in valeurs else Attribution.Role.CONTRIBUTEUR
        request.session["attr_role"] = role
        return role
    role = request.session.get("attr_role")
    return role if role in valeurs else Attribution.Role.CONTRIBUTEUR


def personnes_validatrices():
    """Comptes proposés comme validateurs : actifs, rôle validateur ou administrateur (superutilisateur compris)."""
    return (Utilisateur.objects.filter(is_active=True)
            .filter(Q(role__in=[Utilisateur.Role.VALIDATEUR, Utilisateur.Role.ADMIN]) | Q(is_superuser=True)))


def _attributions_validateurs(request, plan, kpis, arbre):
    """Grille du choix Validateurs : un onglet par niveau d'organisation ; lignes : les KPI saisis à ce niveau ou en
    dessous ; colonnes : les organisations actives du niveau. Une case (KPI, organisation) donne un validateur pour ce
    KPI dans l'organisation et toutes celles du dessous ; elle est « couverte » quand elle a un validateur, à elle ou
    à une organisation au-dessus. Les KPI calculés n'y sont pas (rien à valider)."""
    from .views import comptes_json

    V = Attribution.Role.VALIDATEUR
    niveaux = N.tous()
    rangs = {n.code: n.rang for n in niveaux}
    actives = [o for o in arbre.values() if o.actif]
    orgs_par_niveau = {n.code: sorted([o for o in actives if o.niveau_id == n.code], key=S.cle_arbre) for n in niveaux}
    ids_par_niveau = {c: {o.pk for o in os_} for c, os_ in orgs_par_niveau.items()}
    directs = _validateurs_directs([k.pk for k in kpis])
    couvertes = _couverture(directs, arbre)
    compte = {}  # (ensemble couvert, niveau) → nombre d'organisations actives du niveau couvertes

    def nb_couvertes(k, code):
        c = couvertes.get(k.pk)
        if not c:
            return 0
        cle = (id(c), code)
        if cle not in compte:
            compte[cle] = len(c & ids_par_niveau[code])
        return compte[cle]

    def lignes_niveau(code):
        return [k for k in kpis if rangs.get(k.granularite_id, 0) >= rangs.get(code, 0)]

    directes_par_niveau = {}  # niveau → nombre d'attributions de validateur données à ses organisations actives
    for _, org_id in directs:
        o = arbre.get(org_id)
        if o is not None and o.actif:
            directes_par_niveau[o.niveau_id] = directes_par_niveau.get(o.niveau_id, 0) + 1
    onglets = []
    for n in niveaux:
        ks = lignes_niveau(n.code)
        du_niveau = len(orgs_par_niveau[n.code])
        total = len(ks) * du_niveau
        faites = sum(nb_couvertes(k, n.code) for k in ks)
        onglets.append({"code": n.code, "libelle": n.tr("nom_pluriel"), "nb_kpi": len(ks), "nb_orgs": du_niveau, "total": total,
                        "sans": total - faites, "faites": faites, "pct": int(arrondi(100 * faites / total)) if total else 0,
                        "orgs_libelle": _nom_selon_nombre(n, du_niveau), "nb_orphelins": 0,
                        "nb_herites": 0, "niveau_nom": n.tr("nom")})
    codes = [o["code"] for o in onglets if o["total"]]
    niveau = request.GET.get("niveau") or request.session.get("niveau_attr_valid")
    if niveau not in codes:  # par défaut : le niveau où sont données le plus d'attributions de validateur, sinon le plus haut
        avec = [c for c in codes if directes_par_niveau.get(c)]
        niveau = max(avec, key=lambda c: directes_par_niveau[c]) if avec else (codes[0] if codes else "")
    request.session["niveau_attr_valid"] = niveau
    ks = lignes_niveau(niveau) if niveau else []
    orgs = orgs_par_niveau.get(niveau, [])
    personne = request.GET.get("personne", "")
    groupes_orgs, groupe, nb_colonnes = _groupe_affiche(request, niveau, orgs, arbre, personne, role=V)
    if groupe and groupe != TOUTES_COLONNES:
        orgs = next(g["orgs"] for g in groupes_orgs if g["cle"] == groupe)
    for o in orgs:
        o.hors_niveau = False
        o.nb_kpi = len(ks)
        o.nb_faites = sum(1 for k in ks if o.pk in couvertes.get(k.pk, ()))
        o.nb_sans = o.nb_kpi - o.nb_faites
        o.pct = int(arrondi(100 * o.nb_faites / o.nb_kpi)) if o.nb_kpi else 0
    groupes_colonnes = []
    if len({o.parent_id for o in orgs}) > 1:  # colonnes regroupées sous leur parent quand il y en a plusieurs
        for o in orgs:
            if groupes_colonnes and groupes_colonnes[-1][0] == o.parent:
                groupes_colonnes[-1][1] += 1
            else:
                groupes_colonnes.append([o.parent, 1])
    themes = []
    textes = _TextesGrille(V)
    for k in ks:
        cellules = []
        for o in orgs:
            d = directs.get((k.pk, o.pk), [])
            cellules.append((o, d, None if d or o.pk not in couvertes.get(k.pk, ()) else _dessus(k.pk, o, directs, arbre)))
        ligne = {"kpi": k, "nb_sans": sum(1 for _, d, h in cellules if not d and not h),
                 "html_cellules": mark_safe("".join(html_cellule_attr(k, o, d, textes, h) for o, d, h in cellules))}
        titre = plan.titres(k.code)[0]
        if themes and themes[-1][0] == titre:
            themes[-1][1].append(ligne)
        else:
            themes.append((titre, [ligne]))
    # filtre « Personne » : validateurs et administrateurs actifs, et quiconque a encore une attribution de validateur
    personnes = Utilisateur.objects.filter(is_active=True).filter(
        Q(pk__in=personnes_validatrices().values("pk")) | Q(attributions__role=V)).distinct().order_by("first_name", "last_name")
    return render(request, "collecte/administration/attributions.html", {
        "page": "administration", "rubrique": "attributions", "campagne": S.campagne_courante(), "onglets": onglets,
        "niveau": niveau, "orgs": orgs, "themes": themes, "groupes_colonnes": groupes_colonnes, "admin": True,
        "comptes_json": comptes_json(request, validateurs=True), "personnes": personnes, "personne": personne,
        "onglet": next((o for o in onglets if o["code"] == niveau), None), "calcules": False,
        "groupes_orgs": groupes_orgs, "groupe": groupe, "groupe_defaut": groupes_orgs[0]["cle"] if groupes_orgs else "",
        "nb_colonnes": nb_colonnes, "toutes_colonnes": TOUTES_COLONNES, "role_attr": V,
    })


def _groupe_affiche(request, niveau, orgs, arbre, personne="", role=Attribution.Role.CONTRIBUTEUR):
    """Groupe d'organisations montré dans la grille d'un niveau trop large (MAX_COLONNES_ATTRIBUTIONS).

    Choix : paramètre « groupe » de l'adresse (« tout » : toute la grille, lente sur un grand groupe) ; sinon, quand
    l'adresse désigne une personne (après « Remplacer une personne »), le premier groupe où elle a une attribution ;
    sinon le dernier choisi pour ce niveau (session ; « tout » n'y est pas gardé : jamais une page lente par surprise) ;
    sinon le premier groupe (les premières colonnes, comme avant). Rend (groupes, clé choisie, nombre total de colonnes) ;
    ([], "", n) quand la grille tient en entier."""
    groupes = groupes_colonnes_attr(orgs, arbre)
    if not groupes:
        return [], "", len(orgs)
    for g in groupes:
        noms = [o.nom for o in g["chemin"]] or [libelle("admin.attributions.groupe_sans_rattachement")]
        nom = " › ".join(noms[1:] if len(noms) > 1 else noms)  # la racine commune n'apprend rien
        if not g["entiere"] and g["ancre"] is not None:  # les seules organisations rattachées directement à l'ancre
            nom = libelle("admin.attributions.groupe_direct", nom=nom)
        if g["parties"] > 1:  # plusieurs parties : chacune nommée par sa première et sa dernière organisation
            premier, dernier = g["orgs"][0].nom, g["orgs"][-1].nom
            nom = libelle("admin.attributions.groupe_plage", nom=nom, premier=premier, dernier=dernier) if len(g["orgs"]) > 1 \
                else libelle("admin.attributions.groupe_plage_une", nom=nom, premier=premier)
        g["libelle"] = nom
        g["nb"] = len(g["orgs"])
    cles = {g["cle"] for g in groupes}
    memoire = request.session.get("groupe_attr") or {}
    choisi = request.GET.get("groupe", "")
    if choisi == TOUTES_COLONNES:
        return groupes, choisi, len(orgs)
    if choisi not in cles and _nombre_adresse(personne, 1, 2**31 - 1):
        siennes = set(Attribution.objects.filter(utilisateur_id=int(personne), role=role,
                                                 organisation_id__in=[o.pk for o in orgs]).values_list("organisation_id", flat=True))
        choisi = next((g["cle"] for g in groupes if any(o.pk in siennes for o in g["orgs"])), "")
    if choisi not in cles:
        choisi = memoire.get(niveau, "")
    if choisi not in cles:
        choisi = groupes[0]["cle"]
    if memoire.get(niveau) != choisi:
        request.session["groupe_attr"] = {**memoire, niveau: choisi}
    return groupes, choisi, len(orgs)


def _remplacer(request, de, par):
    """Attributions de ``de`` données à ``par`` et, sur demande, ``de`` désactivé : tout ou rien (refus
    ``DernierGestionnaire`` compris : désactiver le dernier gestionnaire capable d'agir). Renvoie le nombre transféré."""
    with ESP.atomic():
        n = 0
        for a in list(Attribution.objects.filter(utilisateur=de)):
            Attribution.objects.get_or_create(kpi_id=a.kpi_id, organisation_id=a.organisation_id, utilisateur=par, role=a.role)
            a.delete()
            n += 1
        Journal.ecrire(request.user, "remplacement_personne", par, "attributions", f"{de} ({de.email})", f"{par} ({par.email}) : {n}")
        if request.POST.get("desactiver") == "on" and de.pk != request.user.pk:
            de.is_active = False
            de.save(update_fields=["is_active"])
            Journal.ecrire(request.user, "reglage_compte", de, "is_active", True, False)
    return n


@login_required
def remplacer_personne(request):
    """Transférer toutes les attributions d'une personne à une autre (départ, changement de poste)."""
    exiger_admin(request)
    personnes = Utilisateur.ecrivains() \
        .annotate(n=Count("attributions")).order_by("first_name", "last_name")
    erreur = ""
    if request.method == "POST":
        de = get_object_or_404(Utilisateur, pk=identifiant(request.POST.get("de")))
        par = get_object_or_404(Utilisateur, pk=identifiant(request.POST.get("par")), is_active=True)
        if de == par:
            erreur = libelle("admin.remplacer.erreur.differentes")
        elif par.lecture_seule:
            erreur = libelle("admin.remplacer.erreur.lecture_seule")
        else:
            try:
                n = _remplacer(request, de, par)
            except EC.DernierGestionnaire as x:  # désactiver le dernier gestionnaire capable d'agir : rien n'est fait
                erreur = x.message
        if request.method == "POST" and not erreur:
            from django.contrib import messages
            texte = libelle("admin.remplacer.transferees", n=n, de=str(de), par=str(par))
            if request.POST.get("desactiver") == "on" and de.pk != request.user.pk:  # son propre compte n'est pas désactivé
                texte += " " + libelle("admin.remplacer.compte_desactive", nom=str(de))
            messages.success(request, texte)
            return redirect(reverse("collecte:admin_attributions") + f"?personne={par.pk}")
    # personnes dont on transfère les attributions : aussi un lecteur ou un auditeur qui en a encore (d'avant la mise à jour),
    # pour les donner à quelqu'un avant de les retirer (désormais, celles de validateur se donnent aussi dans la
    # grille, choix Validateurs)
    sources = Utilisateur.objects.annotate(n=Count("attributions")).filter(n__gt=0).order_by("first_name", "last_name")
    return _panneau(request, "collecte/administration/_remplacer.html", {"titre_page": libelle("admin.remplacer.titre"), "personnes": personnes,
                                                                         "sources": sources, "erreur": erreur})


# ---------------------------------------------------------------- journal
FAMILLES = [
    ("saisie", "admin.journal.famille.saisie", ['creation', 'modification', 'valeur_recalculee']),
    ("preuve", "admin.journal.famille.preuve", ['depot_preuve', 'retrait_preuve', 'purge_preuve']),
    ("spoc", "admin.journal.famille.spoc", ['attribution', 'retrait_attribution', 'attribution_validateur', 'retrait_validateur',
                                            'remplacement_personne', 'retrait_attributions_role']),
    ("referentiel", "admin.journal.famille.referentiel", ['reglage_kpi', 'reglage_referentiels']),
    ("campagne", "admin.journal.famille.campagne", ['creation_campagne', 'reglage_campagne', 'ouvrir', 'revue', 'cloturer', 'rouvrir', 'rouvrir_contributeurs',
                                                          'mode_reouverture', 'perimetre_periode']),
    ("organisation", "admin.journal.famille.organisation", ['creation_organisation', 'reglage_organisation', 'ajout_alias', 'retrait_alias']),
    ("forcage", "admin.journal.famille.forcage", ['forcage_demande', 'forcage_accepte', 'forcage_refuse', 'forcage_retire', 'forcage_leve',
                                                    'import_calcule_retire']),
    ("coherence", "admin.journal.famille.coherence", ['alerte_justifier', 'alerte_accepter', 'alerte_rejeter', 'alerte_ignorer', 'alerte_rouvrir']),
    ("regle", "admin.journal.famille.regle", ['regle_coherence']),
    ("import", "admin.journal.famille.import", ['import', 'import_valeurs', 'reprise', 'import_arriere_plan', 'import_arrete',
                                                  'import_interrompu', 'import_echec']),
    ("configuration", "admin.journal.famille.configuration", ['import_configuration', 'import_paquet', 'export_paquet', 'demo_chargee']),
    ("exports", "admin.journal.famille.exports", ['export_officiel']),
    ("visualisation", "admin.journal.famille.visualisation", ['vue_partagee']),
    ("corbeille", "admin.journal.famille.corbeille", ['suppression_corbeille', 'restauration_corbeille']),
    ("parametres", "admin.journal.famille.parametres", ['reglage_identite', 'reglage_niveaux', 'reglage_referentiel', 'reglage_seuils', 'reglage_visualisation',
                                                          'reglage_langues', 'traduction', 'reglage_connexion_entreprise']),
    ("ia", "admin.journal.famille.ia", ['reglage_ia', 'ia_appel']),
    ("hebergement", "admin.journal.famille.hebergement", ['sauvegarde', 'telechargement_sauvegarde', 'test_email', 'controle_donnees',
                                                            'reglage_sauvegarde', 'reglage_corbeille', 'reglage_connexions', 'reglage_conservation', 'reglage_exports_fond', 'restauration',
                                                            'reglage_emails', 'test_email_echec', 'reglage_alertes', 'test_alerte', 'test_alerte_echec', 'reglage_mise_a_jour_auto',
                                                            'depot_sauvegarde', 'reglage_copie_externe', 'essai_copie_externe']),
    ("relance", "admin.journal.famille.relance", ['relance', 'relance_manuelle', 'relance_auto', 'reglage_relances']),
    ("compte", "admin.journal.famille.compte", ['creation_compte', 'reglage_compte', 'mot_de_passe', 'changement_mdp', 'suppression_compte']),
    # assistants (serveur MCP, docs/mcp.md) : chaque appel d'outil (journal des données) ; jetons et réglages (administration)
    # (écritures : une ligne par appel ; lectures et appels refusés : une ligne par personne et par jour, serveur_mcp/journal.py)
    ("mcp", "admin.journal.famille.mcp", ['appel_mcp', 'appels_mcp', 'refus_mcp']),
    ("acces_mcp", "admin.journal.famille.acces_mcp", ['jeton_mcp', 'reglage_mcp']),
]


def _libelle_journal(cle, valeur):
    """Libellé d'un code du journal (action, champ) dans la langue de la personne ; le code lui-même s'il n'est pas connu."""
    texte = libelle(f"{cle}.{valeur}")
    return valeur if texte == f"{cle}.{valeur}" else texte


JOURNAL_MOTIF_MAX = 300  # les textes du journal faits d'un modèle sont courts ; au-delà, les motifs ne sont pas essayés
# (un commentaire très long d'une seule ligne les rendait très lents : la page Journal ne s'ouvrait plus)


def _motifs_journal():
    """[(expression, clé)] des textes du journal écrits à partir d'un modèle (« version 1.0 », « X (nouveau niveau) »…),
    reconnus dans leur forme française. Faits une fois par jeu de langues candidates (les libellés viennent des
    fichiers, lus une fois par processus) : avant, à chaque texte affiché (300 entrées : 1 200 lectures de tous les
    libellés)."""
    return _motifs_pour(tuple(LB.candidates("fr")))


@lru_cache(maxsize=16)
def _motifs_pour(candidates):
    import re

    from parametres.libelles import libelles as tous

    sortie = []
    for cle, fr in tous("admin.journal.motif.", "fr").items():
        if isinstance(fr, str):
            morceaux = re.split(r"\{(\w+)\}", fr)
            expr = "".join(re.escape(m) if i % 2 == 0 else f"(?P<{m}>.+?)" for i, m in enumerate(morceaux))
            sortie.append((re.compile(f"^{expr}$"), cle))
    return sortie


@lru_cache(maxsize=16)
def _textes_visu(candidates):
    """{texte français : première clé « visu.journal. » qui l'écrit}, une fois par jeu de langues candidates."""
    sortie = {}
    for k, fr in LB.libelles("visu.journal.", "fr").items():
        if isinstance(fr, str):
            sortie.setdefault(fr, k)
    return sortie


def traduire_texte_journal(v):
    """Texte français écrit dans le journal, affiché dans la langue de la personne qui lit :
    textes fixes (« texte fourni », « (retiré) »…), textes de la Visualisation et textes faits d'un modèle. Le journal
    lui-même ne change pas (aucune migration) ; un texte inconnu reste tel qu'écrit."""
    from parametres import libelles as LB

    if not v:
        return v
    cle = f"admin.journal.texte.{LB.cle_valeur(v)}"
    if LB.libelle(cle, "fr") == v:
        return libelle(cle)
    k = _textes_visu(tuple(LB.candidates("fr"))).get(v)
    if k is not None:
        return libelle(k)
    code = LB.CODE + "[" in v and len(v) <= LB.CODE_MAX + JOURNAL_MOTIF_MAX  # motif codé (refus d'un assistant)
    if (len(v) > JOURNAL_MOTIF_MAX and not code) or "\n" in v:  # texte libre (commentaire, réponse rédigée) : pas un modèle
        return v
    for expr, k in _motifs_journal():
        m = expr.match(v)
        if m:
            return libelle(k, **{c: traduire_texte_journal(x) if c in ("nom", "theme") else LB.recomposer(x) if c == "motif" else x
                                 for c, x in m.groupdict().items()})
    return v


def _lisible(v):
    if v in ("", "None"):
        return "—"
    cle = {"True": "oui", "False": "non", "valide": "valide", "brouillon": "brouillon", "a_saisir": "a_saisir", "ouverte": "ouverte",
           "revue": "revue", "cloturee": "cloturee", "preparation": "preparation",
           "gardes": "chiffres_gardes", "recalcules": "chiffres_recalcules"}.get(v)  # choix de la réouverture
    return libelle(f"admin.journal.valeur.{cle}") if cle else traduire_texte_journal(v)


def _statut_alerte_lisible(v):
    """État d'une alerte écrit au journal (« justifiee », ou « acceptee : texte » pour une décision avec commentaire),
    affiché par le libellé de l'état dans la langue de qui lit ; le texte ajouté reste tel qu'écrit. Le journal lui-même
    ne change pas."""
    from .models import Alerte

    code, sep, texte = (v or "").partition(" : ")
    if code not in Alerte.Statut.values:
        return _lisible(v)
    return LB.choix_valeur(Alerte, "statut", code) + (f" · {texte}" if sep else "")


def _valeur_journal(v):
    """Valeur numérique d'une réponse au journal, écrite comme à l'écran de saisie : « 45000 » → « 45 000 »,
    « 13378.0 » → « 13 378 », « 0.25 » → « 0,25 » (séparateurs de la langue). Autre texte : ``_lisible``."""
    if re.fullmatch(r"-?\d+(\.\d+)?", v or ""):
        d = Decimal(v).normalize()
        return nombre(d, max(0, -d.as_tuple().exponent))
    return _lisible(v)


class EntierDuTexte(Func):
    """Texte → entier (identifiant d'une réponse écrit dans ``Journal.objet_id``) ; sous PostgreSQL, None pour un texte qui
    n'est pas fait de chiffres (une conversion directe y échouerait) ; sous SQLite, un tel texte donne 0 ou son début
    chiffré, écarté ensuite par la comparaison exacte des textes."""

    output_field = BigIntegerField()

    def as_sql(self, compiler, connection, **extra):
        sql, params = compiler.compile(self.source_expressions[0])
        return f"CAST({sql} AS INTEGER)", params

    def as_postgresql(self, compiler, connection, **extra):
        sql, params = compiler.compile(self.source_expressions[0])
        return f"(CASE WHEN {sql} ~ '^[0-9]{{1,18}}$' THEN CAST({sql} AS bigint) END)", [*params, *params]


def journal_des_reponses(journal, exercices, orgs, permises):
    """Entrées du journal sur les réponses d'un exercice (année de début de la période), d'une organisation, ou des
    organisations consultées par l'auditeur (``permises``, None : toutes) : celles dont ``objet_id`` est exactement
    l'identifiant d'une telle réponse. Chaque entrée retrouve sa réponse par son identifiant (clé primaire), sans fabriquer
    la liste en texte de toutes les réponses d'un exercice (1,2 million à 680 organisations : 8 s par requête) ; l'index
    ``journal_objet_action_idx`` (migration 0036) couvre ce que la page lit pour compter et ranger les entrées."""
    return journal.filter(objet="Reponse").alias(_reponse=EntierDuTexte("objet_id")).filter(_meme_reponse(exercices, orgs, permises))


def _meme_reponse(exercices, orgs, permises):
    """Condition « l'entrée porte exactement l'identifiant d'une réponse de ces exercices, organisations, de ce périmètre »,
    sur un journal annoté de ``_reponse`` (``journal_des_reponses``)."""
    from .models import Periode

    reps = Reponse.objects.all() if permises is None else Reponse.objects.filter(organisation_id__in=permises)
    if exercices:
        reps = reps.filter(periode_id__in=list(Periode.objects.filter(debut__year__in=exercices).values_list("pk", flat=True)))
    if orgs:
        reps = reps.filter(organisation_id__in=orgs)
    return Exists(reps.annotate(_texte=Cast("pk", CharField())).filter(pk=OuterRef("_reponse"), _texte=OuterRef("objet_id")))


def journal_compteurs_restreints(journal, actions, personnes, exercices, orgs, permises):
    """Comptes de la page Journal d'un auditeur au périmètre restreint, vue « saisies », sans recherche libre : (entrées par
    type, entrées par personne, total lisible, entrées qui passent les filtres type, personne, exercice, organisation), en
    une seule lecture du journal groupée par (type, personne, dans les filtres exercice et organisation), au lieu de quatre
    lectures qui retrouvent chacune la réponse de chaque entrée (à 680 organisations : 0,6 s chacune). Mêmes nombres que
    ``total.values_list("action")…``, ``journal_par_personne(total, …, restreint=True)``, ``total.count()`` et
    ``qs.count()``. ``journal`` : entrées des types de la vue ; ``actions`` : types choisis (vide : tous) ; ``personnes`` :
    personnes choisies (vide : toutes)."""
    total = journal.filter(objet="Reponse").alias(_reponse=EntierDuTexte("objet_id")).filter(_meme_reponse([], [], permises))
    if exercices or orgs:
        total = total.annotate(_dans=_meme_reponse(exercices, orgs, permises))
    else:
        total = total.annotate(_dans=Value(True, output_field=BooleanField()))
    par_action, par_personne, nb_total, nb_filtre = {}, {}, 0, 0
    actions, personnes = set(actions), {int(p) for p in personnes}
    for action, personne, dans, n in total.values_list("action", "utilisateur_id", "_dans").annotate(n=Count("pk")).order_by():
        par_action[action] = par_action.get(action, 0) + n
        par_personne[personne] = par_personne.get(personne, 0) + n
        nb_total += n
        if dans and (not actions or action in actions) and (not personnes or personne in personnes):
            nb_filtre += n
    return par_action, par_personne, nb_total, nb_filtre


def journal_par_personne(total, actions_vue, restreint=False):
    """{personne : nombre d'entrées} du journal lu (panneau du filtre « Personne »). Sans restriction aux réponses du
    périmètre (``restreint``), compté sans lire les lignes de la table : toutes les entrées par personne (index des
    personnes) moins celles des types hors de la vue (index des types), quand elles sont les moins nombreuses ; sinon
    directement sur les types de la vue. Même résultat que le comptage direct."""
    direct = dict(total.values_list("utilisateur_id").annotate(n=Count("pk")).order_by()) if restreint else None
    if direct is not None:
        return direct
    par_type = dict(Journal.objects.values_list("action").annotate(n=Count("pk")).order_by())
    dans = set(actions_vue)
    hors = [a for a in par_type if a not in dans]
    if sum(par_type[a] for a in hors) >= sum(n for a, n in par_type.items() if a in dans):
        return dict(total.values_list("utilisateur_id").annotate(n=Count("pk")).order_by())
    tout = dict(Journal.objects.values_list("utilisateur_id").annotate(n=Count("pk")).order_by())
    moins = dict(Journal.objects.filter(action__in=hors).values_list("utilisateur_id").annotate(n=Count("pk")).order_by()) if hors else {}
    return {u: n - moins.get(u, 0) for u, n in tout.items() if n - moins.get(u, 0)}


FAMILLES_SAISIE = {"saisie", "preuve", "forcage", "coherence", "import", "mcp"}  # journal des données ; le reste = modifications d'administration


def _nombre_adresse(v, mini, maxi):
    """Nombre lu dans l'adresse, gardé tel quel (texte) s'il est entre ``mini`` et ``maxi`` ; sinon "" (filtre ignoré)."""
    return v if v.isascii() and v.isdigit() and mini <= int(v) <= maxi else ""


@login_required
def journal(request):
    """Historique non modifiable : qui a fait quoi, quand, avant → après. Administration › Historique pour l'administrateur ;
    « Historique » pour l'auditeur (limité aux saisies de ses organisations consultées s'il en a)."""
    from . import conservation as CV

    auditeur = request.user.est_auditeur
    if not auditeur:
        exiger_admin(request)
    permises = request.user.orgs_permises() if auditeur else None
    vue = "admin" if request.GET.get("vue") == "admin" and permises is None else "saisies"
    familles = [(c, libelle(cle), acts) for c, cle, acts in FAMILLES if (c in FAMILLES_SAISIE) == (vue == "saisies")]
    actions_vue = [a for _, _, acts in familles for a in acts]
    nb = {"saisies": Journal.objects.filter(action__in=[a for f, _, acts in FAMILLES if f in FAMILLES_SAISIE for a in acts]).count()}
    nb["admin"] = Journal.objects.count() - nb["saisies"]
    qs = Journal.objects.select_related("utilisateur").filter(action__in=actions_vue)
    q = request.GET.get("q", "").strip()

    # champs de filtre à cocher : plusieurs valeurs à la fois (?personne=3&personne=7). Un nombre hors plage
    # (identifiant démesuré, année au-delà de 9999) ou un type inconnu est ignoré.
    def nombres(nom, maxi):
        return list(dict.fromkeys(v for v in (_nombre_adresse(x, 1, maxi) for x in request.GET.getlist(nom)) if v))

    connues = {f for f, _, _ in familles}
    familles_choisies = [f for f in dict.fromkeys(request.GET.getlist("famille")) if f in connues]
    personnes_choisies, exercices_choisis, orgs_choisies = nombres("personne", 2**31 - 1), nombres("exercice", 9999), nombres("org", 2**31 - 1)

    def des_reponses(journal, exercices, orgs):  # entrées des réponses d'un exercice, d'une organisation, du périmètre de l'auditeur
        if vue != "saisies" or not (exercices or orgs or permises is not None):
            return journal
        return journal_des_reponses(journal, exercices, orgs, permises)

    total = des_reponses(qs, [], [])  # tout ce que la personne peut lire dans ce journal, avant filtre
    if familles_choisies:
        qs = qs.filter(action__in=[a for f, _, acts in familles if f in familles_choisies for a in acts])
    if personnes_choisies:
        qs = qs.filter(utilisateur_id__in=personnes_choisies)
    qs = des_reponses(qs, exercices_choisis, orgs_choisies)
    if q:
        ref = re.fullmatch(r"[Hh]-?0*(\d{1,15})", q)  # « H-1234 » : le numéro d'une ligne de l'export 
        qs = qs.filter(pk=int(ref.group(1))) if ref else qs.filter(
            Q(avant__icontains=q) | Q(apres__icontains=q) | Q(objet_id__icontains=q) | Q(champ__icontains=q))
    filtre = bool(familles_choisies or personnes_choisies or exercices_choisis or orgs_choisies or q)
    # tri par date (le plus récent d'abord, par défaut) ou par auteur (les modifications du système en dernier), fait avant
    # de couper aux 300 premières entrées ; en-têtes « Date » et « Auteur » (liens qui gardent les autres filtres)
    col, decroissant = TRI.demande(request, "journal", ("date", "auteur"))
    col, decroissant = (col, decroissant) if col else ("date", True)
    if col == "auteur":
        nom = [Lower(f"utilisateur__{c}") for c in ("first_name", "last_name", "email", "username")]
        qs = qs.order_by(*[(n.desc(nulls_last=True) if decroissant else n.asc(nulls_last=True)) for n in nom], "-date")
    else:
        qs = qs.order_by("-date" if decroissant else "date")
    tri = {}
    for c in ("date", "auteur"):
        params = request.GET.copy()
        params["tri-journal"] = "-" + c if c == col and not decroissant else c
        tri[c] = {"url": "?" + params.urlencode(), "sens": ("descending" if decroissant else "ascending") if c == col else ""}
    if request.GET.get("export") == "xlsx":  # export du journal filtré, lecture seule
        return _exporter_journal(qs, vue)
    if col == "date":
        # les 300 premières par date, choisies dans l'index seul (une réponse de l'exercice : 500 000 entrées à ranger
        # sans lire leurs lignes), puis lues ; même ordre
        premieres = list(qs.values_list("pk", flat=True)[:300])
        lues = Journal.objects.select_related("utilisateur").in_bulk(premieres)
        entrees = [lues[pk] for pk in premieres]
    else:
        entrees = list(qs[:300])
    libeller_journal(entrees)
    # nombre de lignes de chaque choix, dans le panneau des filtres « Type » et « Personne » (sur tout le journal lu)
    if vue == "saisies" and permises is not None and not q:  # auditeur restreint : une seule lecture pour tous les comptes
        par_action, par_personne, nb_total, nb_filtre = journal_compteurs_restreints(
            Journal.objects.filter(action__in=actions_vue),
            [a for f, _, acts in familles if f in familles_choisies for a in acts], personnes_choisies, exercices_choisis,
            orgs_choisies, permises)
        nb_filtre = nb_filtre if filtre else 0
    else:
        par_action = dict(total.values_list("action").annotate(n=Count("pk")))
        par_personne = journal_par_personne(total, actions_vue, restreint=vue == "saisies" and permises is not None)
        nb_filtre = qs.count() if filtre else 0
        nb_total = total.count() if filtre else 0
    organisations = sorted(S.arbre_organisations().values(), key=S.cle_arbre)
    if permises is not None:
        organisations = [o for o in organisations if o.id in permises]
    return render(request, "collecte/administration/journal.html", {
        "page": "historique" if auditeur else "administration", "rubrique": "journal", "entrees": _regrouper(entrees),
        "familles": [(f, l, sum(par_action.get(a, 0) for a in acts)) for f, l, acts in familles], "vue": vue, "nb": nb,
        "familles_choisies": familles_choisies, "personnes_choisies": personnes_choisies, "exercices_choisis": exercices_choisis,
        "orgs_choisies": orgs_choisies, "filtre": filtre,
        "compte": libelle("commun.filtres.compte", n=nb_filtre, nombre=entier(nb_filtre), total=entier(nb_total)) if filtre else "",
        "deux_vues": permises is None,
        "exercices": sorted(set(Campagne.objects.values_list("exercice", flat=True)), reverse=True),
        "organisations": organisations,
        "q": q, "campagne": S.campagne_courante(),
        "personnes": [(u, par_personne.get(u.pk, 0)) for u in Utilisateur.objects.filter(pk__in=[k for k in par_personne if k]).order_by("first_name")],
        "limite": len(entrees) == 300, "tri": tri,
        "url_export": "?" + _avec(request.GET, vue=vue, export="xlsx"),
        # lien « Récemment supprimés » de l'administrateur (corbeille.tous_supprimes), avec le nombre encore restaurable
        "nb_supprimes": None if auditeur else nb_supprimes(),
        # lien « Preuves à supprimer » (conservation.py), réservé à l'administrateur
        "nb_preuves": None if auditeur else CV.nombre(),
        # auditeur : son historique des connexions (lecture seule), même périmètre que la vue
        # « Modifications d'administration »
        "url_connexions": reverse("collecte:historique_connexions") if auditeur and permises is None else "",
        # auditeur : le certificat de clôture de chaque campagne clôturée (``certificat_cloture`` ; partiel s'il est limité
        # à des organisations)
        "certificats": [(c.nom_complet_affiche, reverse("collecte:certificat_cloture", args=[c.pk]))
                        for c in Campagne.objects.filter(statut=Campagne.Statut.CLOTUREE).select_related("referentiel", "periode")
                        .order_by("-periode__debut", "referentiel__ordre")] if auditeur else [],
    })


def _avec(params, **ajouts):
    """Paramètres de l'adresse avec quelques valeurs ajoutées ou remplacées (lien qui garde les filtres)."""
    q = params.copy()
    for k, v in ajouts.items():
        q[k] = v
    return q.urlencode()


def libeller_journal(entrees):
    """Libellés lisibles des entrées du journal : action, champ, objet (réponse → « KPI · organisation · période »),
    avant et après. Une ligne écrite par un appel d'outil d'un assistant (serveur MCP) porte « via MCP » après l'action
    (page et export). Aussi pour l'outil « historique d'une case » du serveur MCP."""
    from serveur_mcp.journal import via_mcp

    mcp = via_mcp([e.pk for e in entrees])
    from serveur_mcp.models import JetonMCP

    rep_ids = [e.objet_id for e in entrees if e.objet == "Reponse" and e.objet_id.isdecimal()]
    reponses = {str(r.pk): r for r in Reponse.objects.filter(pk__in=rep_ids).select_related("kpi__type_reponse", "organisation", "periode")}
    from .models import DemandeForcage

    dem_ids = [e.objet_id for e in entrees if e.objet == "DemandeForcage" and e.objet_id.isdecimal()]
    reponses.update({f"d{d.pk}": d for d in DemandeForcage.objects.filter(pk__in=dem_ids).select_related("kpi__type_reponse", "organisation", "periode")})
    noms = {
        "KPI": {k.pk: k.nom for k in KPI.objects.filter(pk__in=[e.objet_id for e in entrees if e.objet == "KPI"])},
        "Organisation": {str(k): v for k, v in Organisation.objects.values_list("pk", "nom")},
        "Utilisateur": {str(u.pk): str(u) for u in Utilisateur.objects.filter(pk__in=[e.objet_id for e in entrees if e.objet == "Utilisateur" and e.objet_id.isdecimal()])},
        "Campagne": {str(c.pk): c.nom_complet_affiche for c in Campagne.objects.select_related("referentiel", "periode")},
        "Instance": {"1": libelle("admin.journal.objet.instance")},
        "NiveauHierarchique": {n.code: libelle("admin.journal.objet.niveau", nom=n.nom) for n in N.tous()},
        "Unite": {u.code: libelle("admin.journal.objet.unite", nom=u.symbole) for u in Unite.objects.all()},
        "TypeSaisie": {t.code: libelle("admin.journal.objet.type_saisie", nom=t.libelle) for t in TypeSaisie.objects.all()},
        "TypeReponse": {t.code: libelle("admin.journal.objet.type_reponse", nom=t.libelle) for t in TypeReponse.objects.all()},
        "CategorieDescription": {c.code: libelle("admin.journal.objet.categorie", nom=c.libelle) for c in CategorieDescription.objects.all()},
        "ChampPersonnalise": {c.code: libelle("admin.journal.objet.champ", nom=c.libelle) for c in ChampPersonnalise.objects.all()},
        "Referentiel": {r.code: libelle("admin.journal.objet.referentiel", nom=str(r)) for r in Referentiel.objects.all()},
        "Theme": {str(t.pk): libelle("admin.journal.objet.theme", nom=str(t), referentiel=t.referentiel_id) for t in Theme.objects.filter(
            pk__in=[e.objet_id for e in entrees if e.objet == "Theme" and e.objet_id.isdecimal()])},
        # vues, listes et exports : aussi ceux qui sont dans la corbeille (« tous »)
        "VueVisu": {str(v.pk): libelle("admin.journal.objet.vue", nom=v.nom) for v in VueVisu.tous.filter(
            pk__in=[e.objet_id for e in entrees if e.objet == "VueVisu" and e.objet_id.isdecimal()])},
        "SelectionKPI": {str(x.pk): libelle("admin.journal.objet.liste", nom=x.nom) for x in SelectionKPI.tous.filter(
            pk__in=[e.objet_id for e in entrees if e.objet == "SelectionKPI" and e.objet_id.isdecimal()])},
        "ReglageExport": {str(x.pk): libelle("admin.journal.objet.export", nom=x.nom_affiche) for x in ReglageExport.tous.filter(
            pk__in=[e.objet_id for e in entrees if e.objet == "ReglageExport" and e.objet_id.isdecimal()])},
        "JetonMCP": {str(j.pk): libelle("admin.journal.objet.jeton_mcp", nom=j.nom, debut=j.debut) for j in JetonMCP.objects.filter(
            pk__in=[e.objet_id for e in entrees if e.objet == "JetonMCP" and e.objet_id.isdecimal()])},
        "ReglageMCP": {e.objet_id: libelle("admin.journal.objet.reglage_mcp") for e in entrees if e.objet == "ReglageMCP"},
    }
    codes_org = {str(k): v for k, v in Organisation.objects.values_list("pk", "code")}
    for e in entrees:
        # identifiants pour l'export : numéro de la ligne, codes du KPI et de l'organisation, période
        e.numero, e.code_kpi, e.code_org, e.periode_texte = f"H-{e.pk}", "", "", ""
        if e.objet == "KPI":
            e.code_kpi = e.objet_id
        elif e.objet == "Organisation":
            e.code_org = codes_org.get(e.objet_id, "")
        e.libelle_action = _libelle_journal("admin.journal.action", e.action)
        if e.pk in mcp:
            e.libelle_action = libelle("admin.journal.via_mcp", action=e.libelle_action)
        e.avant_lisible, e.apres_lisible = _lisible(e.avant), _lisible(e.apres)
        e.libelle_champ = _libelle_journal("admin.journal.champ", e.champ)
        if e.action in ("appel_mcp", "refus_mcp"):  # nom de l'outil, tel qu'il s'écrit (jamais « Save_value »)
            e.libelle_champ = libelle("admin.journal.champ.outil_mcp", outil=e.champ)
        elif e.libelle_champ == e.champ:
            e.libelle_champ = traduire_texte_journal(e.champ)
        if e.objet in ("Reponse", "DemandeForcage"):  # réponse ou demande de valeur forcée : « KPI · organisation · période »
            r = reponses.get(e.objet_id if e.objet == "Reponse" else f"d{e.objet_id}")
            if e.champ == "valeur":  # nombre saisi : séparateurs de la langue, sans « .0 » de Python
                e.avant_lisible, e.apres_lisible = _valeur_journal(e.avant), _valeur_journal(e.apres)
            e.libelle_objet = f"{r.kpi.nom} · {r.organisation.nom} · {r.periode}" if r else libelle("admin.journal.objet.reponse", id=e.objet_id)
            if r:
                e.code_kpi, e.code_org, e.periode_texte = r.kpi_id, r.organisation.code, str(r.periode)
            if r is not None and r.kpi.est_texte and e.champ in ("texte", "valeur"):  # réponse rédigée : extrait en texte brut
                from .markdown import extrait

                e.avant_court, e.apres_court = extrait(e.avant), extrait(e.apres)
        elif e.objet == "Alerte":  # « Alert 82 » dans la langue de qui lit ; l'état de l'alerte par son libellé
            e.libelle_objet = libelle("admin.journal.objet.alerte", id=e.objet_id)
            if e.champ == "statut":
                e.avant_lisible, e.apres_lisible = _statut_alerte_lisible(e.avant), _statut_alerte_lisible(e.apres)
        else:
            e.libelle_objet = noms.get(e.objet, {}).get(e.objet_id) or f"{e.objet} {e.objet_id}"
            if e.objet == "KPI":
                e.libelle_objet = f"[{e.objet_id}] {e.libelle_objet}"


# export du journal : toutes les entrées filtrées (pas seulement les 300 affichées), dans une limite qui garde les
# requêtes « pk__in » sous le plafond de paramètres de SQLite (32 766)
MAX_LIGNES_EXPORT_JOURNAL = 20000


def _exporter_journal(qs, vue):
    """Classeur Excel du journal filtré : une ligne par champ modifié (numéro, date, auteur, action, objet, code du KPI,
    code de l'organisation, période, champ, avant, après). Le numéro « H-… » ne change jamais : un auditeur le cite, et
    la recherche de la page retrouve la ligne."""
    from . import fichiers as F

    entrees = list(qs[:MAX_LIGNES_EXPORT_JOURNAL])
    libeller_journal(entrees)
    wb = F.classeur()
    ws = wb.create_sheet(libelle("admin.journal.export_onglet")[:31])
    systeme = libelle("admin.journal.systeme")
    F.ajouter(ws, [libelle(f"admin.journal.export_col.{c}") for c in (
        "numero", "date", "auteur", "action", "objet", "code_kpi", "code_org", "periode", "champ", "avant", "apres")])
    F.entetes(ws)
    def cellule(e, brut, lisible):
        if brut in (None, "", "None"):
            return ""
        if e.champ == "valeur" and e.objet in ("Reponse", "DemandeForcage"):  # nombre : un vrai nombre dans Excel
            try:
                d = Decimal(brut)
                if d.is_finite():
                    return float(d)
            except (ArithmeticError, ValueError):
                pass
        return lisible

    for e in entrees:
        champ = e.libelle_champ if e.champ else ""
        F.ajouter(ws, [e.numero, e.date, str(e.utilisateur) if e.utilisateur else systeme, e.libelle_action, e.libelle_objet,
                       e.code_kpi, e.code_org, e.periode_texte, champ[:1].upper() + champ[1:], cellule(e, e.avant, e.avant_lisible), cellule(e, e.apres, e.apres_lisible)])
    for ligne in ws.iter_rows(min_row=2, min_col=2, max_col=2):
        ligne[0].number_format = "DD/MM/YYYY HH:MM"
    F.largeurs(ws, [10, 17, 26, 26, 50, 14, 18, 12, 24, 40, 40])
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = ws.dimensions
    nom = libelle("admin.journal.onglet_saisies" if vue == "saisies" else "admin.journal.onglet_admin")
    return F.reponse_excel(wb, F.nom_fichier(libelle("admin.journal.export_fichier"), nom))


def nb_supprimes():
    from .models import MODELES_SUPPRIMABLES, limite_corbeille

    limite = limite_corbeille()
    return sum(m.tous.filter(supprime_le__gte=limite).count() for m in MODELES_SUPPRIMABLES)


def _regrouper(entrees):
    """Une ligne par geste : les champs modifiés ensemble (même personne, même objet, même minute) sont réunis."""
    groupes = []
    for e in entrees:
        cle = (e.utilisateur_id, e.action, e.objet, e.objet_id, e.date.replace(second=0, microsecond=0))
        if not (groupes and groupes[-1].cle == cle):
            e.cle, e.details = cle, []
            groupes.append(e)
        if e.champ and not (e.action.startswith("creation") and e.apres in ("", "None", "False")):
            groupes[-1].details.append(e)
    for g in groupes:
        g.details.reverse()  # dans l'ordre de saisie
    return groupes
