"""Administration › Paramètres : identité de l'installation (nom, logo, couleurs), niveaux de l'arbre, référentiel réglable."""

from functools import partial

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import FileResponse, Http404, JsonResponse
from django.db.models import Count, Exists, OuterRef
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.functional import lazy
from django.views.decorators.cache import cache_control

from collecte.garde_requetes import nombre_envoye, reponse_inerte
from collecte.models import Journal
from collecte.reponses_script import reponse_erreur
from collecte.saisie import campagne_courante
from collecte.vues_communes import exiger_admin

from . import couleurs as CO
from . import langues as LG
from . import libelles as LB
from . import niveaux as N
from . import referentiel as PR
from .libelles import libelle
from .models import (CategorieDescription, ChampPersonnalise, Instance, NiveauHierarchique, TypeReponse, TypeSaisie, Unite,
                     valider_couleur)
from espaces import contexte as ESP

_l = lazy(libelle, str)  # libellé évalué à l'affichage (champs de formulaire définis à l'import)

CHAMPS = ["nom", "titre", "sous_titre", "sigle", "contact", "palette",
          "couleur_principale", "couleur_accent", "couleur_fond", "couleur_texte"]


exiger_admin_reglages = partial(exiger_admin, message="admin.reserve_admin")  # refus avec le message des réglages


class IdentiteForm(forms.ModelForm):
    supprimer_logo = forms.BooleanField(required=False, label=_l("admin.identite.retirer_logo"))

    class Meta:
        model = Instance
        fields = CHAMPS + ["logo"]
        widgets = {c: forms.TextInput(attrs={"class": "code", "maxlength": 7, "pattern": "#[0-9A-Fa-f]{6}"})
                   for c in ("couleur_principale", "couleur_accent", "couleur_fond", "couleur_texte")}
        labels = {c: _l(f"admin.identite.form.{c}") for c in (
            "nom", "titre", "sous_titre", "sigle", "contact", "couleur_principale", "couleur_accent", "couleur_fond", "couleur_texte")}
        # pas de phrase d'aide sous ces champs (ni celle du modèle) : le simulateur de la page montre où va chaque texte
        help_texts = {c: "" for c in ("titre", "sous_titre", "sigle", "contact")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # aucune palette cochée (palette inconnue de cet espace) : pas d'erreur cachée, clean() la ramène à « perso »
        self.fields["palette"].required = False

    def clean(self):
        d = super().clean()
        for c in ("couleur_principale", "couleur_accent", "couleur_fond", "couleur_texte"):
            if d.get(c):
                d[c] = d[c].upper()
        p = palettes_disponibles().get(d.get("palette"))
        cles = ("principale", "accent", "fond", "texte")
        if not p or any(d.get(f"couleur_{c}") != p[c].upper() for c in cles):
            d["palette"] = "perso"  # couleurs retouchées : ce n'est plus la palette d'origine
        return d


class IdentitePageForm(IdentiteForm):
    """Page Paramètres › Identité : l'identité, et le texte de l'entreprise de la page « Données et confidentialité »
    (absent de l'assistant « Mise en place », qui ne l'efface donc jamais)."""

    class Meta(IdentiteForm.Meta):
        fields = IdentiteForm.Meta.fields + ["texte_confidentialite"]
        labels = {**IdentiteForm.Meta.labels, "texte_confidentialite": _l("admin.identite.form.texte_confidentialite")}
        widgets = {**IdentiteForm.Meta.widgets, "texte_confidentialite": forms.Textarea(
            attrs={"rows": 6, "aria-describedby": "aide-texte-confidentialite", "maxlength": 20000,
                   # « Markdown accepté » dans la zone ; la même phrase reste lue par les lecteurs d'écran (aria-describedby)
                   "placeholder": _l("admin.identite.confidentialite.markdown")})}
        help_texts = {**IdentiteForm.Meta.help_texts, "texte_confidentialite": ""}


class SeuilsForm(forms.ModelForm):
    """Seuils de suivi : tolérance du retard (points), contrôle « hors historique » (années, valeurs nécessaires) et
    écarts tolérés, saisis en % et stockés en fraction comme tous les pourcentages de l'outil."""
    tolerance_fe_pct = forms.DecimalField(label=_l("admin.seuils.form.tolerance_fe"), min_value=0, max_value=100,
                                          max_digits=6, decimal_places=2, localize=True,
                                          help_text=_l("admin.seuils.form.tolerance_fe_aide"))
    tolerance_detail_pct = forms.DecimalField(label=_l("admin.seuils.form.tolerance_detail"), min_value=0, max_value=100,
                                              max_digits=6, decimal_places=2, localize=True,
                                              help_text=_l("admin.seuils.form.tolerance_detail_aide"))
    # rôles qui peuvent répondre N/A (l'administrateur toujours, case cochée et grisée dans le gabarit)
    na_roles_choix = forms.MultipleChoiceField(label=_l("admin.seuils.form.na_roles"), required=False,
                                               widget=forms.CheckboxSelectMultiple,
                                               choices=[("validateur", "validateur"), ("contributeur", "contributeur")])

    class Meta:
        model = Instance
        fields = ["tolerance_retard", "historique_annees", "historique_minimum"]
        labels = {"tolerance_retard": _l("admin.seuils.form.tolerance_retard"),
                  "historique_annees": _l("admin.seuils.form.historique_annees"),
                  "historique_minimum": _l("admin.seuils.form.historique_minimum")}
        help_texts = {"tolerance_retard": _l("admin.seuils.form.tolerance_retard_aide"),
                      "historique_annees": _l("admin.seuils.form.historique_annees_aide"),
                      "historique_minimum": _l("admin.seuils.form.historique_minimum_aide")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        i = self.instance
        self.fields["tolerance_fe_pct"].initial = (i.tolerance_fe * 100).normalize()
        self.fields["tolerance_detail_pct"].initial = (i.tolerance_detail * 100).normalize()
        from referentiel.models import Utilisateur

        self.fields["na_roles_choix"].choices = [(r, LB.choix_valeur(Utilisateur, "role", r)) for r in ("validateur", "contributeur")]
        self.fields["na_roles_choix"].initial = [r for r in (i.na_roles or "").split(",") if r in ("validateur", "contributeur")]

    def clean(self):
        d = super().clean()
        if d.get("historique_minimum") and d.get("historique_annees") and d["historique_minimum"] > d["historique_annees"]:
            self.add_error("historique_minimum", libelle("admin.seuils.erreur.minimum"))
        return d

    def save(self, commit=True):
        self.instance.tolerance_fe = self.cleaned_data["tolerance_fe_pct"] / 100
        self.instance.tolerance_detail = self.cleaned_data["tolerance_detail_pct"] / 100
        self.instance.na_roles = ",".join(["admin"] + [r for r in ("validateur", "contributeur") if r in self.cleaned_data["na_roles_choix"]])
        return super().save(commit)


@login_required
def seuils(request):
    """Paramètres › Seuils de suivi : quand signaler un retard, et seuils des contrôles automatiques de cohérence."""
    exiger_admin_reglages(request)
    instance = Instance.courante()
    champs = ["tolerance_retard", "historique_annees", "historique_minimum", "tolerance_fe", "tolerance_detail", "na_roles"]
    form = SeuilsForm(instance=instance)
    if request.method == "POST":
        avant = {c: getattr(instance, c) for c in champs}
        form = SeuilsForm(request.POST, instance=instance)
        if form.is_valid():
            form.save()
            for c, v in avant.items():
                if getattr(instance, c) != v:
                    Journal.ecrire(request.user, "reglage_seuils", instance, c, v, getattr(instance, c))
            messages.success(request, libelle("admin.seuils.enregistres"))
            return redirect("parametres:seuils")
    return render(request, "parametres/seuils.html", {
        "page": "administration", "rubrique": "parametres", "sous_rubrique": "seuils", "form": form,
        "campagne": campagne_courante(),
    })


class VisualisationForm(forms.ModelForm):
    """Paramètres › Visualisation : nombre de vues personnelles par personne (libellés : fichiers de langue)."""

    class Meta:
        model = Instance
        fields = ["vues_personnelles_max"]
        widgets = {"vues_personnelles_max": forms.NumberInput(attrs={"min": 1, "max": 500, "aria-describedby": "aide-vues-max"})}


@login_required
def visualisation(request):
    """Paramètres › Visualisation : vue d'accueil de chaque rôle, parmi les vues partagées (une seule par rôle ; celle
    qui s'ouvre sur /visualisation/ pour qui n'a pas choisi sa vue par défaut), et nombre de vues personnelles par
    personne. Chaque changement est noté dans le Journal."""
    from collecte import vues_visu as VV
    from collecte.models import AccueilVisu, VueVisu

    exiger_admin_reglages(request)
    instance = Instance.courante()
    partagees = list(VueVisu.objects.filter(partage=True).order_by("ordre", "nom", "pk"))
    par_id = {str(v.pk): v for v in partagees}
    erreurs = []
    form = VisualisationForm(instance=instance)
    if request.method == "POST":
        demandes = {r: request.POST.get(f"accueil_{r}", "") for r in AccueilVisu.ROLES}
        avant = instance.vues_personnelles_max
        form = VisualisationForm(request.POST, instance=instance)
        if any(x and x not in par_id for x in demandes.values()):
            erreurs.append(libelle("visu.parametres.vue_inconnue"))
        elif form.is_valid():
            with ESP.atomic():
                for role, x in demandes.items():
                    VV.definir_accueil(request.user, role, par_id.get(x))
                form.save()
                if instance.vues_personnelles_max != avant:
                    Journal.ecrire(request.user, "reglage_visualisation", instance, "vues_personnelles_max", avant,
                                   instance.vues_personnelles_max)
            messages.success(request, libelle("visu.parametres.enregistre"))
            return redirect("parametres:visualisation")
    actuelles = dict(AccueilVisu.objects.filter(vue__supprime_le__isnull=True).values_list("role", "vue_id"))  # vue dans la corbeille : aucune
    roles = [{"code": r, "nom": VV.nom_role(r), "vue": actuelles.get(r)} for r in AccueilVisu.ROLES]
    return render(request, "parametres/visualisation.html", {
        "page": "administration", "rubrique": "parametres", "sous_rubrique": "visualisation", "roles": roles,
        "partagees": partagees, "erreurs": erreurs, "form": form, "campagne": campagne_courante(),
    })


def palettes_disponibles():
    """{code: {nom, principale, accent, fond, texte}} : palettes fournies (neutres) puis celles de l'installation."""
    from .models import PaletteEnregistree

    sortie = {code: {**p, "nom": libelle(f"admin.identite.palette.{code}")} for code, p in CO.PALETTES.items()}
    for p in PaletteEnregistree.objects.all():
        sortie[p.code] = {"nom": p.nom, "principale": p.principale, "accent": p.accent, "fond": p.fond, "texte": p.texte,
                          "gamme": p.gamme, "enregistree": p}
    return sortie


class CouleursGraphiquesForm(forms.Form):
    """Paramètres › Identité › « Couleurs des graphiques » : les 8 couleurs des séries de la Visualisation, dans
    l'ordre, et celle de « Autres ». Les couleurs fournies enregistrent un réglage vide (la palette fournie)."""

    def __init__(self, *args, instance=None, **kwargs):
        super().__init__(*args, **kwargs)
        series, autres, _ = (instance or Instance.courante()).palette_graphiques()
        attrs = {"class": "code", "maxlength": 7, "pattern": "#[0-9A-Fa-f]{6}", "data-viz": ""}
        for i, c in enumerate(series, start=1):
            self.fields[f"viz_{i}"] = forms.CharField(max_length=7, initial=c, validators=[valider_couleur],
                                                      widget=forms.TextInput(attrs=attrs))
        self.fields["viz_autres"] = forms.CharField(max_length=7, initial=autres, validators=[valider_couleur],
                                                    widget=forms.TextInput(attrs=attrs))

    def clean(self):
        return {k: v.upper() for k, v in super().clean().items() if isinstance(v, str)}

    def champs_series(self):
        return [self[f"viz_{i}"] for i in range(1, len(CO.VIZ) + 1)]

    def reglage(self):
        d = self.cleaned_data
        return CO.reglage_graphiques([d[f"viz_{i}"] for i in range(1, len(CO.VIZ) + 1)], d["viz_autres"])


def texte_couleurs_graphiques(reglage):
    """Pour le Journal : « palette fournie » ou les couleurs réglées."""
    series, autres, regle = CO.palette_graphiques(reglage)
    return ", ".join(series + [autres]) if regle else "palette fournie"  # noté dans le journal (donnée)


def enregistrer_couleurs_graphiques(utilisateur, reglage):
    i = Instance.courante()
    if i.couleurs_graphiques != reglage:
        avant = texte_couleurs_graphiques(i.couleurs_graphiques)
        i.couleurs_graphiques = reglage
        i.save(update_fields=["couleurs_graphiques", "date_maj"])
        Journal.ecrire(utilisateur, "reglage_identite", i, "couleurs_graphiques", avant, texte_couleurs_graphiques(reglage))


def _message_enregistree(request):
    """« Identité enregistrée » ; en avertissement (sans rien refuser) si une paire texte / fond que l'outil affiche
    passe sous son seuil WCAG, en clair ou en sombre."""
    g = Instance.courante().gamme()
    controles = CO.controles(g) + CO.controles(CO.gamme_sombre(g))
    sous_seuil = sum(1 for c in controles if not c["ok"])
    if sous_seuil:
        messages.warning(request, libelle("admin.identite.avertissement_contraste", n=sous_seuil, total=len(controles)))
    else:
        messages.success(request, libelle("admin.identite.enregistree"))


@login_required
def identite(request):
    from .models import PaletteEnregistree

    exiger_admin_reglages(request)
    form = IdentitePageForm(instance=Instance.courante())
    form_viz = CouleursGraphiquesForm()
    if request.method == "POST":
        action = request.POST.get("action", "")
        if action == "couleurs_graphiques_defaut":  # « Revenir aux couleurs par défaut » : la palette fournie
            enregistrer_couleurs_graphiques(request.user, {})
            messages.success(request, libelle("visu.couleurs.defaut_ok"))
            return redirect(reverse("parametres:identite") + "#couleurs-graphiques")
        if "viz_1" in request.POST:
            form_viz = CouleursGraphiquesForm(request.POST)
        if action.startswith("supprimer_palette:"):
            p = PaletteEnregistree.depuis_code(action.split(":", 1)[1])
            if p:
                i = Instance.courante()
                if i.palette == p.code:
                    i.palette = "perso"
                    i.save(update_fields=["palette"])
                Journal.ecrire(request.user, "reglage_identite", i, "palette supprimée", p.nom, "")
                p.delete()
                messages.success(request, libelle("admin.identite.palette_supprimee", nom=p.nom))
            return redirect("parametres:identite")
        form = IdentitePageForm(request.POST, request.FILES, instance=Instance.courante())
        avec_viz = "viz_1" in request.POST  # section « Couleurs des graphiques » (absente de l'assistant)
        if form.is_valid() and (not avec_viz or form_viz.is_valid()):
            if action == "enregistrer_palette":
                nom = request.POST.get("nom_palette", "").strip()[:40]
                if not nom:
                    form.add_error(None, libelle("admin.identite.erreur.nom_palette"))
                else:
                    d = form.cleaned_data
                    p = PaletteEnregistree.objects.create(nom=nom, principale=d["couleur_principale"], accent=d["couleur_accent"],
                                                          fond=d["couleur_fond"], texte=d["couleur_texte"])
                    form.instance.palette = p.code
                    enregistrer_identite(request.user, form)
                    if avec_viz:  # après l'identité, qui réécrit toute la ligne
                        enregistrer_couleurs_graphiques(request.user, form_viz.reglage())
                    Journal.ecrire(request.user, "reglage_identite", form.instance, "palette enregistrée", "", nom)
                    messages.success(request, libelle("admin.identite.palette_enregistree", nom=nom))
                    return redirect("parametres:identite")
            else:
                enregistrer_identite(request.user, form)
                if avec_viz:
                    enregistrer_couleurs_graphiques(request.user, form_viz.reglage())
                _message_enregistree(request)
                return redirect("parametres:identite")
    return render(request, "parametres/identite.html", {
        "page": "administration", "rubrique": "parametres", "campagne": campagne_courante(), **contexte_identite(form),
        **contexte_couleurs_graphiques(form_viz)})


def contexte_couleurs_graphiques(form_viz):
    """Section « Couleurs des graphiques » de la page Identité : champs, et contraste de chaque couleur enregistrée sur
    le fond des cartes (3:1 au moins pour une barre ou un trait)."""
    i = Instance.courante()
    series, autres, regle = i.palette_graphiques()
    controles = CO.controles_graphiques(series, autres, i.gamme()["surface"])
    return {"form_viz": form_viz, "controles_viz": controles, "viz_regle": regle, "seuil_viz": CO.SEUIL_MARQUES,
            "viz_defaut": ",".join(CO.VIZ + [CO.VIZ_AUTRES]),
            "viz_claires": sum(1 for c in controles if c["claire"]),
            "champs_viz": list(zip(form_viz.champs_series(), controles)), "champ_viz_autres": (form_viz["viz_autres"], controles[-1])}


def enregistrer_identite(utilisateur, form):
    """Enregistre un IdentiteForm valide (logo déposé ou retiré) et journalise chaque champ changé. Sert aussi à
    l'assistant « Mise en place »."""
    instance = Instance.objects.get(pk=form.instance.pk)
    champs = CHAMPS + [c for c in ("texte_confidentialite",) if c in form.fields]  # page Identité, pas l'assistant
    avant, logo_avant = {c: getattr(instance, c) for c in champs}, instance.logo.name
    i = form.save(commit=False)
    if form.cleaned_data.get("supprimer_logo") and not form.files.get("logo"):
        i.logo.delete(save=False)
        i.logo = ""
    i.save()
    for c in champs:
        if avant[c] != getattr(i, c):
            Journal.ecrire(utilisateur, "reglage_identite", i, c, avant[c], getattr(i, c))
    if logo_avant != i.logo.name:
        Journal.ecrire(utilisateur, "reglage_identite", i, "logo", "déposé" if logo_avant else "", "déposé" if i.logo else "retiré")
    return i


def contexte_identite(form):
    """Formulaire, palettes, gamme et contrastes de la page Identité (et de l'étape « Votre structure » de l'assistant)."""
    g = Instance.courante().gamme()  # valeurs enregistrées : un formulaire refusé ne fausse pas l'aperçu
    palettes = []
    for code, p in palettes_disponibles().items():
        gp = CO.gamme(p["principale"], p["accent"], p["fond"], p["texte"], code, p.get("gamme"))
        palettes.append((code, p["nom"], [gp["fond"], gp["principale"], gp["accent"], gp["principale-teinte"], gp["texte"]], p))
    controles = CO.controles(g)
    sombres = CO.controles(CO.gamme_sombre(g))
    return {"form": form, "palettes": palettes, "controles": controles, "contraste_ok": all(c["ok"] for c in controles),
            "controles_sombres": sombres, "contraste_sombre_ok": all(c["ok"] for c in sombres), "css_sombre": CO.css(CO.gamme_sombre(g)),
            "bilan_clair": sum(1 for c in controles if c["ok"]), "bilan_sombre": sum(1 for c in sombres if c["ok"]),
            "adaptations": CO.adaptations(g), "seuil": CO.SEUIL_AA,
            "type_saisie": TypeSaisie.objects.filter(comportement=TypeSaisie.Comportement.SAISIE).order_by("pk").first()}


@login_required
def apercu(request):
    """Gamme et contrastes pour 4 couleurs (aperçu en direct de la page Identité)."""
    exiger_admin_reglages(request)
    valeurs = [request.GET.get(c, "").upper() for c in ("principale", "accent", "fond", "texte")]
    if not all(CO.valide(v) for v in valeurs):
        return reponse_erreur(libelle("admin.config.erreur.couleur"), status=200)  # aperçu en direct : l'aperçu reste tel quel
    from .models import gamme_fixe_de

    g = CO.gamme(*valeurs, request.GET.get("palette"), gamme_fixe_de(request.GET.get("palette"), tuple(valeurs)))
    gs = CO.gamme_sombre(g)
    return JsonResponse({"ok": True, "css": CO.css(g), "controles": CO.controles(g), "adaptations": CO.adaptations(g),
                         "css_sombre": CO.css(gs), "controles_sombres": CO.controles(gs)})


TYPES_LOGO = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}


@cache_control(public=True, max_age=86400)
def logo(request):
    """Logo de l'installation, visible sans connexion (page de connexion)."""
    i = Instance.courante()
    if not i.logo_disponible:
        raise Http404
    # type par liste : un logo venu d'une archive restaurée (SVG, HTML) n'est jamais servi comme contenu actif
    type_ = TYPES_LOGO.get(i.logo.name.rsplit(".", 1)[-1].lower())
    if type_ is None:
        raise Http404
    return reponse_inerte(FileResponse(i.logo.open("rb"), content_type=type_))


# ---------------------------------------------------------------- niveaux de l'arbre
def _usages():
    """{code: {"orgs", "kpis", "regles"}} : ce qui porte chaque niveau (un niveau utilisé ne se supprime pas)."""
    from collecte.models import RegleCoherence
    from referentiel.models import KPI, Organisation

    u = {n.code: {"orgs": 0, "kpis": 0, "regles": 0} for n in N.tous()}
    for cle, qs, champ in (("orgs", Organisation.objects, "niveau"), ("kpis", KPI.objects, "granularite"),
                           ("regles", RegleCoherence.objects, "niveau")):
        for code, n in qs.values_list(champ).annotate(n=Count("pk")):
            if code in u:
                u[code][cle] = n
    return u


def ordre_casse(rangs):
    """Organisations qui seraient au niveau de leur rattachement ou au-dessus avec ces rangs (liste vide sinon)."""
    from referentiel.models import Organisation

    return [o for o in Organisation.objects.filter(parent__isnull=False).select_related("niveau", "parent__niveau")
            .order_by("nom") if rangs[o.parent.niveau_id] >= rangs[o.niveau_id]]


def _renumeroter(niveaux, utilisateur):
    """Rangs 1, 2, 3… dans l'ordre donné ; journalise les changements de position."""
    for rang, n in enumerate(niveaux, start=1):
        if n.rang != rang:
            Journal.ecrire(utilisateur, "reglage_niveaux", n, "rang", n.rang, rang)
            n.rang = rang
            n.save(update_fields=["rang"])


def _apercu_arbre(limite=40):
    """Organisations dans l'ordre de l'arbre, avec leur profondeur (aperçu à droite de la page)."""
    from collecte import saisie as S

    orgs = sorted(S.arbre_organisations().values(), key=S.cle_arbre)
    return orgs[:limite], max(len(orgs) - limite, 0)


@login_required
def niveaux(request):
    """Les niveaux de l'arbre (Groupe, Pays, Entité, Site… de 1 à 8) : nom, pluriel, couleur, ordre."""
    exiger_admin_reglages(request)
    tous = N.tous()
    erreur = ""
    if request.method == "POST":
        action = request.POST.get("action", "")
        for cle in ("monter", "descendre", "supprimer"):  # boutons de ligne : name = action, value = code du niveau
            if cle in request.POST:
                action, request.POST = cle, request.POST.copy()
                request.POST["code"] = request.POST[cle]
        with ESP.atomic():
            if action == "enregistrer":
                erreur = _enregistrer_niveaux(request, tous)
                if not erreur:
                    messages.success(request, libelle("admin.niveaux.enregistres"))
            elif action == "ajouter":
                erreur = _ajouter_niveau(request, tous)
            elif action in ("monter", "descendre"):
                erreur = _deplacer_niveau(request, tous, action)
            elif action == "supprimer":
                erreur = _supprimer_niveau(request, tous)
        if not erreur:
            return redirect("parametres:niveaux")
        tous = N.tous()
    usages = _usages()
    for n in tous:
        n.usage = usages.get(n.code, {})
        n.utilise = any(n.usage.values())
    orgs, autres = _apercu_arbre()
    return render(request, "parametres/niveaux.html", {
        "page": "administration", "rubrique": "parametres", "sous_rubrique": "niveaux", "niveaux": tous, "erreur": erreur,
        "campagne": campagne_courante(),
        "maximum": NiveauHierarchique.MAXIMUM, "apercu_orgs": orgs, "apercu_autres": autres, "langues_champs": LG.champs_reference(),
        "couleur_suivante": CO.COULEURS_NIVEAUX[len(tous) % len(CO.COULEURS_NIVEAUX)], "post": request.POST if erreur else {},
    })


def _noms_valides(paires):
    """Erreur si un nom manque ou si deux niveaux portent le même nom (les imports reconnaissent un niveau par son nom)."""
    vus = set()
    for nom, pluriel in paires:
        if not nom or not pluriel:
            return libelle("admin.niveaux.erreur.nom_requis")
        for t in {nom.lower(), pluriel.lower()}:
            if t in vus:
                return libelle("admin.niveaux.erreur.noms_distincts", nom=t)
            vus.add(t)
    return ""


def _enregistrer_niveaux(request, tous):
    valeurs = {}
    for n in tous:
        nom = request.POST.get(f"nom_{n.code}", "").strip()[:60]
        pluriel = request.POST.get(f"pluriel_{n.code}", "").strip()[:60] or nom
        couleur = request.POST.get(f"couleur_{n.code}", "").strip().upper()
        if not CO.valide(couleur):
            return libelle("admin.niveaux.erreur.couleur_de", nom=nom or n.tr("nom"))
        valeurs[n.code] = (nom, pluriel, couleur)
    erreur = _noms_valides([(v[0], v[1]) for v in valeurs.values()])
    if erreur:
        return erreur
    for n in tous:
        nom, pluriel, couleur = valeurs[n.code]
        for champ, v in (("nom", nom), ("nom_pluriel", pluriel), ("couleur", couleur)):
            if getattr(n, champ) != v:
                Journal.ecrire(request.user, "reglage_niveaux", n, champ, getattr(n, champ), v)
                setattr(n, champ, v)
                if champ == "couleur":
                    n.deriver_couleurs()
        n.save()
    return ""


def _ajouter_niveau(request, tous):
    if len(tous) >= NiveauHierarchique.MAXIMUM:
        return libelle("admin.niveaux.erreur.maximum", maximum=NiveauHierarchique.MAXIMUM)
    nom = request.POST.get("nom", "").strip()[:60]
    pluriel = request.POST.get("nom_pluriel", "").strip()[:60] or nom
    couleur = request.POST.get("couleur", "").strip().upper()
    if not CO.valide(couleur):
        return libelle("admin.niveaux.erreur.couleur")
    erreur = _noms_valides([(n.nom, n.nom_pluriel) for n in tous] + [(nom, pluriel)])
    if erreur:
        return erreur
    position = request.POST.get("position", "")
    apres = next((i for i, n in enumerate(tous) if n.code == position), None)
    index = 0 if position == "haut" else len(tous) if apres is None else apres + 1
    n = NiveauHierarchique(code=N.nouveau_code(nom), rang=index + 1, nom=nom, nom_pluriel=pluriel, couleur=couleur)
    n.deriver_couleurs()
    n.save()
    Journal.ecrire(request.user, "reglage_niveaux", n, "nom", "", f"{nom} (nouveau niveau)")  # noté dans le journal (donnée)
    _renumeroter(tous[:index] + [n] + tous[index:], request.user)  # insérer ne casse pas l'arbre : l'ordre des autres est gardé
    messages.success(request, libelle("admin.niveaux.ajoute", nom=nom))
    return ""


def _deplacer_niveau(request, tous, action):
    i = next((i for i, n in enumerate(tous) if n.code == request.POST.get("code")), None)
    j = None if i is None else i - 1 if action == "monter" else i + 1
    if i is None or not 0 <= j < len(tous):
        return ""
    ordre = list(tous)
    ordre[i], ordre[j] = ordre[j], ordre[i]
    casses = ordre_casse({n.code: r for r, n in enumerate(ordre, start=1)})
    if casses:
        haut, bas = (tous[i], tous[j]) if action == "monter" else (tous[j], tous[i])
        n = len(casses)
        exemples = ", ".join(libelle("admin.niveaux.erreur.exemple", nom=o.nom, parent=o.parent.nom) for o in casses[:5])
        if n > 5:
            exemples = libelle("admin.niveaux.erreur.et_autres", exemples=exemples, n=n - 5)
        return libelle("admin.niveaux.erreur.ordre", n=n, haut=haut.tr("nom"), bas=bas.tr("nom"), exemples=exemples)
    _renumeroter(ordre, request.user)
    _recalculer()  # « au-dessus » / « en dessous » de la granularité d'un KPI peut changer : agrégats à refaire
    messages.success(request, libelle("admin.niveaux.ordre_enregistre"))
    return ""


def _recalculer():
    from collecte.calcul import recalculer
    from collecte.coherence import controler
    from collecte.models import Campagne

    faites = set()
    for c in Campagne.objects.exclude(statut=Campagne.Statut.CLOTUREE).select_related("referentiel", "periode"):
        if c.periode_id not in faites:
            recalculer(c)
            faites.add(c.periode_id)
        controler(c)


def _supprimer_niveau(request, tous):
    n = next((n for n in tous if n.code == request.POST.get("code")), None)
    if n is None:
        return ""
    if len(tous) == 1:
        return libelle("admin.niveaux.erreur.au_moins_un")
    u = _usages().get(n.code, {})
    if any(u.values()):
        return libelle("admin.niveaux.erreur.utilise", nom=n.tr("nom"), orgs=u["orgs"], kpis=u["kpis"], regles=u["regles"])
    Journal.ecrire(request.user, "reglage_niveaux", n, "nom", n.nom, "(niveau supprimé)")
    n.delete()
    _renumeroter([x for x in tous if x.code != n.code], request.user)
    messages.success(request, libelle("admin.niveaux.supprime", nom=n.tr("nom")))
    return ""


# ---------------------------------------------------------------- référentiel réglable
SECTIONS = {
    # titre, modèle, aide, champs [(nom, libellé, genre)], champs figés quand l'élément est utilisé, mot pour l'usage ;
    # titre, aide, libellés et mot sont des clés de libellé (admin.referentiel.*), résolues à l'affichage (``_textes``)
    "unites": ("admin.referentiel.unites.titre", Unite, "admin.referentiel.unites.aide",
               [("symbole", "admin.referentiel.champ.symbole", "texte"), ("libelle", "admin.referentiel.champ.libelle", "texte"),
                ("famille", "admin.referentiel.champ.thematique", "famille"), ("entier", "admin.referentiel.champ.entier", "case"),
                ("decimales", "admin.referentiel.champ.decimales", "nombre")], set(), "admin.referentiel.mot.kpi"),
    "types-saisie": ("admin.referentiel.types_saisie.titre", TypeSaisie, "admin.referentiel.types_saisie.aide",
                     [("libelle", "admin.referentiel.champ.libelle", "texte"), ("abrege", "admin.referentiel.champ.etiquette", "texte"),
                      ("couleur", "admin.referentiel.champ.couleur", "couleur"),
                      ("comportement", "admin.referentiel.champ.comportement", "choix")], {"comportement"}, "admin.referentiel.mot.kpi"),
    "types-reponse": ("admin.referentiel.types_reponse.titre", TypeReponse, "admin.referentiel.types_reponse.aide",
                      [("libelle", "admin.referentiel.champ.libelle", "texte"), ("format", "admin.referentiel.champ.format", "choix"),
                       ("valeurs", "admin.referentiel.champ.valeurs", "lignes"),
                       ("colonnes", "admin.referentiel.champ.colonnes", "colonnes")], {"format"}, "admin.referentiel.mot.kpi"),
    "categories": ("admin.referentiel.categories.titre", CategorieDescription, "admin.referentiel.categories.aide",
                   [("libelle", "admin.referentiel.champ.libelle", "texte"), ("affichee", "admin.referentiel.champ.affichee", "case"),
                    ("obligatoire", "admin.referentiel.champ.obligatoire", "case")],
                   set(), "admin.referentiel.mot.texte"),
    "champs": ("admin.referentiel.champs.titre", ChampPersonnalise, "admin.referentiel.champs.aide",
               [("libelle", "admin.referentiel.champ.libelle", "texte"), ("type", "admin.referentiel.champ.type", "choix"),
                ("valeurs", "admin.referentiel.champ.valeurs", "lignes")], {"type"}, "admin.referentiel.mot.kpi"),
}

# une ligne sous le nom de chaque liste, dans la navigation de la page (clés de libellé)
RESUMES = {"unites": "admin.referentiel.unites.resume", "types-saisie": "admin.referentiel.types_saisie.resume",
           "types-reponse": "admin.referentiel.types_reponse.resume", "categories": "admin.referentiel.categories.resume",
           "champs": "admin.referentiel.champs.resume"}


def _lire(genre, brut):
    """Valeur d'un champ posté, ou ValueError avec un message lisible."""
    brut = (brut or "").strip()
    if genre == "case":
        return brut in ("on", "1", "true")
    if genre == "nombre":
        try:
            n = int(brut or 0)
        except ValueError:
            raise ValueError(libelle("admin.referentiel.erreur.entier"))
        if not 0 <= n <= 10:
            raise ValueError(libelle("admin.referentiel.erreur.entre_0_10"))
        return n
    if genre == "couleur":
        if not CO.valide(brut.upper()):
            raise ValueError(libelle("admin.referentiel.erreur.couleur"))
        return brut.upper()
    if genre == "lignes":
        return [v.strip() for v in brut.replace(";", "\n").splitlines() if v.strip()]
    if genre == "colonnes":  # tableau : « code ; libellé ; type ; liste ou unité », une colonne par ligne
        from . import langues as L

        colonnes = []
        for ligne in brut.splitlines():
            morceaux = [m.strip() for m in ligne.split(";")]
            if not any(morceaux):
                continue
            morceaux += [""] * (4 - len(morceaux))
            code, lib, type_, autre = morceaux[:4]
            # les mots anglais de l'exemple affiché en anglais sont acceptés comme les mots de référence
            type_ = {"number": "nombre", "text": "texte", "list": "liste"}.get(type_.lower(), type_.lower())
            c = {"code": code, "libelle": {L.reference(): lib or code}, "type": type_}
            if autre:
                c["liste" if c["type"] == "liste" else "unite"] = autre
            colonnes.append(c)
        return colonnes
    return brut[:100]


class AConfirmer(str):
    """Motif d'un enregistrement de la page qui attend une confirmation (case « confirmer_casse ») : changement de casse
    seule du symbole d'une unité utilisée, quand la casse peut en changer le sens."""


def _controle(section, obj, avant, nb_usages, confirme=False):
    """Motif de refus d'un élément modifié ou créé, sinon "" ; ``AConfirmer`` : à confirmer (``confirme`` le lève)."""
    from collecte.models import Reponse

    if section == "unites" and not obj.symbole:
        return libelle("admin.referentiel.erreur.symbole")
    if section == "unites" and avant and obj.pk and avant.get("symbole") != obj.symbole:
        from collecte.reglages import avertissement_symbole_unite, motif_symbole_unite

        # symbole figé par les valeurs de ses KPI, sauf une correction d'écriture ou de casse seule,
        # confirmée quand la casse peut changer le sens ; les traductions du symbole ne changent pas ici
        motif = motif_symbole_unite(obj.pk, (avant["symbole"], obj.traductions), (obj.symbole, obj.traductions))
        if motif:
            return motif
        if not confirme:
            avert = avertissement_symbole_unite(obj.pk, (avant["symbole"], obj.traductions), (obj.symbole, obj.traductions))
            if avert:
                return AConfirmer(avert)
    if section == "unites" and obj.entier and avant and not avant.get("entier") and obj.pk:
        from collecte.reglages import nb_valeurs_decimales
        from referentiel.models import KPI

        codes = list(KPI.objects.filter(unite=obj.pk).values_list("code", flat=True))
        n = sum(1 for c in codes if nb_valeurs_decimales([c]))
        if n:  # ses KPI ont des valeurs décimales : elles deviendraient refusées 
            return libelle("admin.referentiel.erreur.entier_decimales", n=n)
    if section == "unites" and obj.entier:
        obj.decimales = 0  # un nombre entier n'a pas de décimales
    if section != "unites" and not obj.libelle:
        return libelle("admin.referentiel.erreur.libelle")
    if section == "types-saisie":
        obj.abrege = obj.abrege or obj.libelle[:20]
        if obj.couleur != avant.get("couleur") or not obj.couleur_fond:
            obj.deriver_couleurs()
    if section == "types-reponse":
        if obj.format == TypeReponse.Format.LISTE and not obj.valeurs:
            return libelle("admin.referentiel.erreur.liste_valeurs")
        if obj.format != TypeReponse.Format.TABLEAU:
            obj.colonnes = list(avant.get("colonnes") or []) if avant else []  # sans objet hors d'un tableau : gardées telles quelles
        else:
            from collecte import tableaux

            anciennes = {c.get("code"): c for c in (avant.get("colonnes") or []) if isinstance(c, dict)} if avant else {}
            for c in obj.colonnes or []:  # libellés des autres langues gardés pour une colonne au même code
                lib = (anciennes.get(c.get("code")) or {}).get("libelle")
                if isinstance(lib, dict):
                    c["libelle"] = {**lib, **c["libelle"]}
            listes = set(TypeReponse.objects.filter(format=TypeReponse.Format.LISTE).values_list("code", flat=True))
            erreurs = tableaux.erreurs_colonnes(obj.colonnes, listes)
            if erreurs:
                return " ".join(erreurs)
            forme = [(c.get("code"), c.get("type")) for c in obj.colonnes]
            if avant and forme != [(c.get("code"), c.get("type")) for c in avant.get("colonnes") or []] and \
                    Reponse.objects.filter(kpi__type_reponse=obj.pk).exclude(texte="").exists():
                return libelle("admin.referentiel.erreur.colonnes_reponses")
        from collecte.tableaux import valeurs_utilisees

        retirees = set(avant.get("valeurs") or []) - set(obj.valeurs or [])
        if retirees and (Reponse.objects.filter(kpi__type_reponse=obj.pk, texte__in=retirees).exists()
                         or valeurs_utilisees(obj.pk, retirees)):
            return libelle("admin.referentiel.erreur.valeurs_reponses", n=len(retirees), valeurs=", ".join(sorted(retirees)))
    if section == "champs":
        if obj.type == ChampPersonnalise.Type.LISTE and not obj.valeurs:
            return libelle("admin.referentiel.erreur.liste_valeurs")
        retirees = set(avant.get("valeurs") or []) - set(obj.valeurs or [])
        from referentiel.models import KPI

        if retirees and any(k.get(obj.pk) in retirees for k in KPI.objects.exclude(champs={}).values_list("champs", flat=True)):
            return libelle("admin.referentiel.erreur.valeurs_kpi", n=len(retirees), valeurs=", ".join(sorted(retirees)))
    return ""


@login_required
def referentiel(request):
    """Unités, types de saisie et de réponse, catégories de description, champs personnalisés des KPI."""
    exiger_admin_reglages(request)
    section = request.GET.get("section") if request.GET.get("section") in SECTIONS else "unites"
    titre, modele, aide, champs, figes, mot_usage = _textes(SECTIONS[section])
    langues_champs = LG.champs_reference()
    if langues_champs["different"]:  # les champs de texte portent la langue de référence : le libellé le dit
        champs = [(nom, libelle("admin.reference.etiquette", champ=lib, nom_langue=langues_champs["reference"])
                   if nom in CHAMPS_LANGUE_REFERENCE else lib, genre) for nom, lib, genre in champs]
    erreur = ""
    if request.method == "POST":
        action = request.POST.get("action", "")
        for cle in ("monter", "descendre", "supprimer"):  # boutons de ligne : name = action, value = code
            if cle in request.POST:
                action = cle
        with ESP.atomic():
            if action == "enregistrer":
                erreur = _enregistrer_liste(request, section)
            elif action == "ajouter":
                erreur = _ajouter_element(request, section)
            elif action == "ajouter_catalogue" and section == "unites":
                _ajouter_catalogue(request)
            elif action == "ranger" and section == "unites":
                _ranger_unites(request)
            elif action == "monnaie" and section == "unites":
                erreur = _enregistrer_monnaie(request)
            elif action in ("monter", "descendre", "supprimer"):
                erreur = _ligne_liste(request, section, action, request.POST.get(action, ""))
        if not erreur:
            return redirect(f"{request.path}?section={section}")
    usages = PR.usages()
    elements = list(modele.objects.all())
    for e in elements:
        e.nb_usages = usages.get(section, {}).get(e.pk, 0)
    confirmer_casse = isinstance(erreur, AConfirmer)
    if confirmer_casse:  # la saisie reste à l'écran pour être confirmée telle quelle
        _reprendre_saisie(request.POST, elements, champs)
    nombres = {s: modele_s.objects.count() for s, (_, modele_s, *_rest) in SECTIONS.items()}
    themes_unites = _themes_unites(elements) if section == "unites" else []
    exemple = kpis_decrits().prefetch_related("descriptions").first()
    return render(request, "parametres/referentiel.html", {
        "page": "administration", "rubrique": "referentiels", "sous_rubrique": "referentiel", "campagne": campagne_courante(),
        "section": section, "titre": titre, "aide": aide, "champs": champs, "figes": figes, "mot_usage": mot_usage,
        "langues_champs": langues_champs, "elements": elements, "erreur": erreur, "confirmer_casse": confirmer_casse,
        "sections": [(s, libelle(t[0]), nombres[s], libelle(RESUMES[s])) for s, t in SECTIONS.items()],
        "choix": {nom: modele._meta.get_field(nom).choices for nom, _, genre in champs if genre == "choix"},
        "familles": _familles(),
        "post": request.POST if erreur else {}, "exemple": exemple,
        "types_saisie": TypeSaisie.objects.all() if section == "types-saisie" else [],
        "couleur_suivante": CO.COULEURS_NIVEAUX[len(elements) % len(CO.COULEURS_NIVEAUX)],
        "themes_unites": themes_unites,
        "catalogue_autres": [t for t in themes_unites if not t["unites"] and t["suggestions"]],
        "precisions": {f: libelle(cle) for f, cle in PRECISIONS_FORMAT.items()} if section == "types-reponse" else {},
        "a_ranger": section == "unites" and any(not e.famille and PR.famille(e.symbole) for e in elements),
        **(_contexte_monnaie(elements, usages) if section == "unites" else {}),
    })


def _reprendre_saisie(post, elements, champs):
    """Valeurs envoyées remises sur les éléments affichés (sans rien enregistrer), pour une page à confirmer."""
    par_code = {str(e.pk): e for e in elements}
    for i in range(nombre_envoye(post, "nb")):
        e = par_code.get(post.get(f"code__{i}", ""))
        if e is None:
            continue
        for nom, _, genre in champs:
            if genre == "case":
                setattr(e, nom, f"{nom}__{i}" in post)
            elif f"{nom}__{i}" in post:
                try:
                    setattr(e, nom, _lire(genre, post.get(f"{nom}__{i}")))
                except ValueError:
                    pass


CHAMPS_LANGUE_REFERENCE = ("symbole", "libelle", "abrege")  # textes saisis dans la langue de référence (traduits à part)

PRECISIONS_FORMAT = {  # clés du complément affiché dans la liste « Format » (Paramètres › Types de réponse)
    "nombre": "admin.referentiel.precision.nombre", "pourcentage": "admin.referentiel.precision.pourcentage",
    "oui_non": "admin.referentiel.precision.oui_non", "liste": "admin.referentiel.precision.liste",
    "texte": "admin.referentiel.precision.texte",
}


def _textes(section):
    """Une section de SECTIONS avec ses textes dans la langue de la personne : (titre, modèle, aide, champs, figés, mot)."""
    titre, modele, aide, champs, figes, mot = section
    return libelle(titre), modele, libelle(aide), [(nom, libelle(cle), genre) for nom, cle, genre in champs], figes, libelle(mot)


def _familles():
    """Thématiques proposées : celles du catalogue puis celles de l'installation."""
    from .catalogue_unites import NOMS, THEMES_HISTORIQUES

    autres = sorted(f for f in set(Unite.objects.exclude(famille="").values_list("famille", flat=True)) - set(NOMS)
                    if f.strip().lower() not in THEMES_HISTORIQUES)
    return NOMS + autres


def _themes_unites(unites):
    """[{nom, aide, unites [(rang dans le formulaire, unité)], suggestions}] : thématiques du catalogue d'abord (même vides,
    pour leurs suggestions), puis celles de l'installation, puis les unités sans thématique."""
    from . import catalogue_unites as CU

    presents = {u.symbole.lower() for u in unites}
    themes, index = [], {}
    for nom, aide, catalogue in CU.THEMES:  # « nom » : valeur enregistrée ; « affiche » : nom dans la langue de l'interface
        index[nom.lower()] = len(themes)
        themes.append({"nom": nom, "affiche": CU.nom_theme(nom), "aide": CU.aide_theme(nom, aide), "unites": [], "suggestions": [
            {"symbole": sy, "affiche": CU.nom_symbole(sy), "libelle": CU.nom_unite(l), "entier": e, "decimales": d}
            for sy, l, e, d in catalogue if sy.lower() not in presents]})
    for i, u in enumerate(unites):
        cle = (CU.theme_du_catalogue(u.famille) or u.famille or "").strip().lower()  # une thématique historique rejoint celle du catalogue
        if cle not in index:
            index[cle] = len(themes)
            nom = u.famille.strip() or libelle("admin.referentiel.sans_thematique")
            themes.append({"nom": nom, "affiche": nom, "aide": "" if cle else
                           libelle("admin.referentiel.sans_thematique_aide"),
                           "unites": [], "suggestions": []})
        themes[index[cle]]["unites"].append((i, u))
    sans = themes.pop(index[""]) if "" in index else None
    themes = [t for t in themes if t["unites"]] + [t for t in themes if not t["unites"]]  # thématiques utilisées d'abord
    return themes + ([sans] if sans else [])


def _ajouter_catalogue(request):
    """Ajoute les unités cochées du catalogue (valeur « thématique|symbole »), sans doublon de symbole. Le symbole et le
    libellé enregistrés sont ceux du catalogue ; leurs traductions dans les autres langues de l'interface les suivent."""
    from . import catalogue_unites as CU
    from .catalogue_unites import THEMES

    voulues = set(request.POST.getlist("catalogue"))
    presents = {s.lower() for s in Unite.objects.values_list("symbole", flat=True)}
    ordre = Unite.objects.order_by("-ordre").values_list("ordre", flat=True).first() or 0
    ajoutees = []
    for theme, _, unites in THEMES:
        for symbole, nom_unite, entier, decimales in unites:
            if f"{theme}|{symbole}" in voulues and symbole.lower() not in presents:
                ordre += 1
                u = Unite.objects.create(code=PR.code_unite(symbole), symbole=symbole, libelle=nom_unite, entier=entier,
                                         decimales=decimales, famille=theme, ordre=ordre,
                                         traductions=CU.traductions_installation(symbole, nom_unite, LG.reference()))
                _journal(request, u, "symbole", "", f"{symbole} (créé depuis le catalogue)")
                presents.add(symbole.lower())
                ajoutees.append(symbole)
    if ajoutees:
        messages.success(request, libelle("admin.referentiel.unites_ajoutees", n=len(ajoutees), liste=", ".join(ajoutees)))
    else:
        messages.info(request, libelle("admin.referentiel.aucune_unite_cochee"))


def _enregistrer_monnaie(request):
    """Monnaie de référence de l'espace (liste fermée de ``monnaies.MONNAIES``) : elle ne vaut que pour les modèles de la
    bibliothèque installés ou mis à jour ensuite ; aucun KPI existant ne change. Une ligne d'historique."""
    from . import monnaies as MO

    code = request.POST.get("monnaie", "")
    if not MO.valide(code):
        return libelle("admin.monnaies.inconnue")
    Instance.courante()  # la ligne existe : elle se relit sous verrou avant d'écrire
    i = Instance.objects.select_for_update().get(pk=1)
    if i.monnaie != code:
        Journal.ecrire(request.user, "reglage_referentiel", i, "Monnaie de référence", i.monnaie, code)
        i.monnaie = code
        i.save(update_fields=["monnaie", "date_maj"])
        messages.success(request, libelle("admin.monnaies.enregistree", monnaie=MO.affichee(code)))
    return ""


def _contexte_monnaie(elements, usages):
    """Réglage de la monnaie de référence (page Unités) : choix, monnaie actuelle, et unités monétaires utilisées par des
    KPI dans une autre monnaie (simple signalement : rien n'est changé)."""
    from . import monnaies as MO

    code = MO.reference()
    nb = usages.get("unites", {})
    autres = [e for e in elements if nb.get(e.pk) and MO.monnaie_du_symbole(e.symbole) not in (None, code)]
    return {"monnaie": code, "monnaies": MO.choix(), "monnaie_affichee": MO.affichee(code),
            "unites_autre_monnaie": autres, "kpi_autre_monnaie": sum(nb[e.pk] for e in autres)}


def _ranger_unites(request):
    """Donne une thématique devinée aux unités qui n'en ont pas (celles qui en ont une ne changent pas)."""
    n = 0
    for u in Unite.objects.filter(famille=""):
        f = PR.famille(u.symbole)
        if f:
            u.famille = f
            u.save(update_fields=["famille"])
            _journal(request, u, "famille", "", f)
            n += 1
    messages.success(request, libelle("admin.referentiel.unites_rangees", n=n))


def _journal(request, obj, champ, avant, apres):
    Journal.ecrire(request.user, "reglage_referentiel", obj, champ, avant, apres)


def _valeur_affichee(v):
    if isinstance(v, list) and any(isinstance(x, dict) for x in v):  # colonnes d'un tableau : « code ; nom ; type ; liste ou unité »
        from .models import TypeReponse

        return TypeReponse(colonnes=v).colonnes_texte
    return "\n".join(v) if isinstance(v, list) else v


def _enregistrer_liste(request, section):
    _, modele, _, champs, figes, _ = _textes(SECTIONS[section])
    usages = PR.usages().get(section, {})
    elements = {str(e.pk): e for e in modele.objects.all()}
    confirme, a_confirmer = request.POST.get("confirmer_casse") == "1", []
    for i in range(nombre_envoye(request.POST, "nb")):
        obj = elements.get(request.POST.get(f"code__{i}", ""))
        if obj is None:
            continue
        avant = {nom: getattr(obj, nom) for nom, _, _ in champs}
        for nom, nom_champ, genre in champs:
            if nom in figes and usages.get(obj.pk):
                continue  # figé : l'élément est utilisé
            if genre != "case" and f"{nom}__{i}" not in request.POST:
                continue
            try:
                v = _lire(genre, request.POST.get(f"{nom}__{i}"))
                longueur = getattr(modele._meta.get_field(nom), "max_length", None)
                setattr(obj, nom, v[:longueur] if isinstance(v, str) and longueur else v)  # PostgreSQL refuse un texte trop long
            except ValueError as e:
                transaction.set_rollback(True, using=ESP.alias_courant())  # tout ou rien : les lignes déjà enregistrées ne restent pas
                return libelle("admin.referentiel.erreur.champ", element=avant.get("libelle") or avant.get("symbole") or obj.pk, champ=nom_champ, erreur=e)
        motif = _controle(section, obj, avant, usages.get(obj.pk, 0), confirme)
        if isinstance(motif, AConfirmer):  # les autres lignes sont lues aussi : une seule confirmation pour toutes
            a_confirmer.append(motif)
            continue
        if motif:
            transaction.set_rollback(True, using=ESP.alias_courant())
            return libelle("admin.referentiel.erreur.element", element=avant.get("libelle") or avant.get("symbole") or obj.pk, motif=motif)
        changes = [(nom, avant[nom], getattr(obj, nom)) for nom, _, _ in champs if avant[nom] != getattr(obj, nom)]
        if changes:
            obj.save()
            for nom, a, b in changes:
                _journal(request, obj, nom, _valeur_affichee(a), _valeur_affichee(b))
            if section == "unites" and obj.entier and not avant["entier"]:
                _kpi_entiers(request, obj)
    if a_confirmer:  # rien n'est enregistré avant la confirmation (tout ou rien)
        transaction.set_rollback(True, using=ESP.alias_courant())
        return AConfirmer(" ".join(a_confirmer))
    messages.success(request, libelle("admin.referentiel.enregistre"))
    return ""


def _kpi_entiers(request, unite):
    """Unité passée en « Nombre entier » : les KPI qui l'utilisent s'affichent sans décimales (Saisie, exports)."""
    from referentiel.models import KPI

    for k in KPI.objects.filter(unite=unite).exclude(decimales=0):
        Journal.ecrire(request.user, "reglage_kpi", k, "decimales", k.decimales, 0)
        k.decimales = 0
        k.save(update_fields=["decimales"])


def _ajouter_element(request, section):
    titre, modele, _, champs, _, _ = _textes(SECTIONS[section])
    obj = modele()
    for nom, nom_champ, genre in champs:
        try:
            setattr(obj, nom, _lire(genre, request.POST.get(nom)))
        except ValueError as e:
            return libelle("admin.referentiel.erreur.champ_seul", champ=nom_champ, erreur=e)
    if section == "unites":
        obj.code = PR.code_unite(obj.symbole or "u")
    else:
        obj.code = PR.nouveau_code(modele, obj.libelle or "x", modele._meta.get_field("code").max_length)
    obj.ordre = (modele.objects.order_by("-ordre").values_list("ordre", flat=True).first() or 0) + 1
    motif = _controle(section, obj, {}, 0)
    if motif:
        return libelle("admin.referentiel.erreur.ajout", motif=motif)
    obj.save()
    _journal(request, obj, "libelle" if section != "unites" else "symbole", "", f"{getattr(obj, 'libelle', '') or obj.symbole} (créé)")
    messages.success(request, libelle("admin.referentiel.ajoute", nom=str(obj)))
    return ""


def _ligne_liste(request, section, action, code):
    _, modele, _, _, _, mot_usage = _textes(SECTIONS[section])
    elements = list(modele.objects.all())
    i = next((i for i, e in enumerate(elements) if str(e.pk) == code), None)
    if i is None:
        return ""
    if action == "supprimer":
        n = PR.usages().get(section, {}).get(elements[i].pk, 0)
        if n:
            return libelle("admin.referentiel.erreur.utilise", nom=str(elements[i]), n=n, mot=mot_usage)
        _journal(request, elements[i], "libelle", str(elements[i]), "(supprimé)")
        elements[i].delete()
        messages.success(request, libelle("admin.referentiel.supprime", nom=str(elements[i])))
        return ""
    pas = -1 if action == "monter" else 1
    j = i + pas
    if section == "unites":  # les unités s'affichent par thématique : échange avec la voisine de la même thématique
        while 0 <= j < len(elements) and elements[j].famille.strip().lower() != elements[i].famille.strip().lower():
            j += pas
    if not 0 <= j < len(elements):
        return ""
    elements[i], elements[j] = elements[j], elements[i]
    for rang, e in enumerate(elements, start=1):
        if e.ordre != rang:
            modele.objects.filter(pk=e.pk).update(ordre=rang)
    return ""


def kpis_decrits():
    """KPI actifs qui ont au moins un texte de description (l'exemple affiché par Paramètres › Unités et formats).

    Sous-requête ``EXISTS`` sur l'index de la clé du KPI, et non ``exclude(descriptions=None)`` : cette forme joignait deux
    fois la table des descriptions et, sous PostgreSQL avec des statistiques pas encore relevées (juste après un gros
    chargement fait en une transaction), a tourné 541 s. Test : ``parametres/test_kpis_decrits_exists.py``."""
    from referentiel.models import KPI, Description

    return KPI.objects.filter(Exists(Description.objects.filter(kpi=OuterRef("pk"))), actif=True)
