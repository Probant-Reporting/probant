"""Administration › Paramètres › Assistant IA (docs/ai_socket.md) : allumer la prise, la clé du client, le fournisseur et
le modèle, les limites, chaque usage, et ce qui est envoyé ; propositions de traductions (page Traductions).

Chaque changement est noté au journal (``reglage_ia``) ; la clé jamais : seulement « enregistrée » ou « retirée ».
"""
from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.utils.functional import lazy
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_POST

from collecte.models import Journal
from collecte.reponses_script import reponse_erreur
from collecte.saisie import campagne_courante
from collecte.sensibles import caches_ia

from . import ia as IA
from . import ia_fournisseurs as F
from . import ia_invites as INV
from . import langues as L
from . import traductions as TR
from .libelles import libelle
from .models import Instance, Langue
from .views import exiger_admin_reglages
from espaces import contexte as ESP

_l = lazy(libelle, str)
CHAMPS = ["ia_active", "ia_fournisseur", "ia_modele", "ia_appels_jour", "ia_taille_max", "ia_delai",
          "ia_expliquer_alertes", "ia_reprise", "ia_traductions", "ia_kpi_sensibles"]
USAGES_CHAMPS = [("expliquer_alerte", "ia_expliquer_alertes"), ("reprise", "ia_reprise"), ("traduction", "ia_traductions")]


class ReglagesIAForm(forms.ModelForm):
    api_key = forms.CharField(required=False, strip=True, max_length=400, label=_l("admin.ia.form.cle"),
                              widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "off", "spellcheck": "false",
                                                                                   "aria-describedby": "aide-cle"}))

    class Meta:
        model = Instance
        fields = CHAMPS
        labels = {c: _l(f"admin.ia.form.{c}") for c in CHAMPS}
        help_texts = {c: "" for c in CHAMPS}
        widgets = {"ia_appels_jour": forms.NumberInput(attrs={"min": 1, "max": 5000}),
                   "ia_taille_max": forms.NumberInput(attrs={"min": 2000, "max": 400000, "step": 1000}),
                   "ia_delai": forms.NumberInput(attrs={"min": 10, "max": 110})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        fournisseurs = F.disponibles()
        self.fields["ia_fournisseur"] = forms.ChoiceField(label=_l("admin.ia.form.ia_fournisseur"),
                                                          choices=[(c, f.nom) for c, f in fournisseurs.items()])
        self.fields["ia_modele"] = forms.ChoiceField(label=_l("admin.ia.form.ia_modele"), choices=[
            (m, nom) for f in fournisseurs.values() for m, nom, _ in f.modeles])

    def clean_api_key(self):
        cle = self.cleaned_data.get("api_key") or ""
        if cle:
            try:
                return IA.valider_cle(cle)
            except ValueError as e:
                raise forms.ValidationError(str(e)) from None
        return ""

    def clean(self):
        d = super().clean()
        f = F.disponibles().get(d.get("ia_fournisseur"))
        if f is not None and d.get("ia_modele") and not f().connait(d["ia_modele"]):
            d["ia_modele"] = f.modele_par_defaut  # modèle d'un autre fournisseur : celui par défaut du fournisseur choisi
        if d.get("ia_active") and not d.get("api_key") and not IA.cle_presente():
            self.add_error("api_key", libelle("admin.ia.cle_requise"))
        return d


def _contexte(request, form):
    i = Instance.courante()
    f = IA.fournisseur(i)
    return {
        "page": "administration", "rubrique": "parametres", "sous_rubrique": "ia", "campagne": campagne_courante(),
        "form": form, "instance": i, "permise": settings.IA_PRISE_PERMISE, "cle_presente": IA.cle_presente(), "date_cle": IA.date_cle(),
        "disponible": IA.disponible(i=i), "appels": IA.appels_aujourdhui(), "fournisseur": f,
        "modeles": [(m, nom, libelle(note)) for fo in F.disponibles().values() for m, nom, note in fo.modeles],
        "usages": [(u, form[c], [libelle(f"admin.ia.envoye.{u}.{x}") for x in INV.ENVOYE[u][0]],
                    [libelle(f"admin.ia.jamais.{u}.{x}") for x in INV.ENVOYE[u][1]]) for u, c in USAGES_CHAMPS],
        "hotes": sorted({fo.hote for c, fo in F.disponibles().items() if c != "factice"}),
    }


@login_required
@sensitive_post_parameters("api_key")
def reglages(request):
    exiger_admin_reglages(request)
    i = Instance.courante()
    form = ReglagesIAForm(instance=i)
    if request.method == "POST":
        if request.POST.get("action") == "retirer_cle":
            if IA.retirer_cle():
                Journal.ecrire(request.user, "reglage_ia", i, "cle", libelle("admin.ia.journal.cle_enregistree", langue="fr"),
                               libelle("admin.ia.journal.cle_retiree", langue="fr"))
                messages.success(request, libelle("admin.ia.cle_retiree"))
            return redirect("parametres:ia")
        avant = {c: getattr(i, c) for c in CHAMPS}
        form = ReglagesIAForm(request.POST, instance=i)
        if form.is_valid():
            with ESP.atomic():
                cle = form.cleaned_data.get("api_key")
                if cle:
                    remplacee = IA.cle_presente()
                    IA.enregistrer_cle(cle)
                    Journal.ecrire(request.user, "reglage_ia", i, "cle",
                                   libelle("admin.ia.journal.cle_enregistree", langue="fr") if remplacee else "",
                                   libelle("admin.ia.journal.cle_remplacee" if remplacee else "admin.ia.journal.cle_enregistree", langue="fr"))
                form.save()
                for c, v in avant.items():
                    if getattr(i, c) != v:
                        Journal.ecrire(request.user, "reglage_ia", i, c, v, getattr(i, c))
            messages.success(request, libelle("admin.ia.enregistres"))
            return redirect("parametres:ia")
    return render(request, "parametres/ia.html", _contexte(request, form))


# ---------------------------------------------------------------- traductions proposées
GENRES = {"kpi": "KPI name", "descriptions": "KPI description", "themes": "theme name", "libelles": "label of a setting"}


@login_required
@require_POST
def traductions_ia(request, code):
    """Traductions proposées par l'IA pour les textes encore vides de la section affichée (60 au plus) : JSON
    {propositions: [{cle, texte}]}. Rien n'est enregistré ici : la personne reprend les propositions puis enregistre."""
    exiger_admin_reglages(request)
    lg = Langue.objects.filter(code=code).first()
    if lg is None or code == L.reference():
        raise Http404
    if not IA.disponible("traduction"):
        return reponse_erreur(libelle("admin.ia.refus.eteinte"))
    section = request.POST.get("section") if request.POST.get("section") in dict(TR.SECTIONS) else TR.SECTIONS[0][0]
    from .vues_langues import LIMITE

    vides = [e for e in TR.elements(code, section)[:LIMITE] if not e.actuel and not e.facultatif]
    caches = caches_ia()  # KPI sensibles et dérivés, réglage éteint : ni leur nom ni leurs descriptions ne partent
    envoyables = [e for e in vides if TR.kpi_element(e) not in caches] if caches else vides
    if not envoyables:
        return JsonResponse({"propositions": [], "message": libelle(
            "admin.ia.traductions.sensibles" if vides else "admin.ia.traductions.rien")})
    vides = envoyables[:INV.MAX_TEXTES_TRADUCTION]
    invite = INV.traduction([(n, GENRES[section], e.source) for n, e in enumerate(vides, start=1)], L.reference(), code)
    try:
        reponse = IA.appeler(request.user, invite, lg)
    except (IA.Refus, F.ErreurIA) as e:
        return reponse_erreur(IA.message_erreur(e), status=400 if isinstance(e, IA.Refus) else 502)
    return JsonResponse({"propositions": [{"cle": e.cle, "texte": reponse[n]} for n, e in enumerate(vides, start=1) if n in reponse],
                         "fournisseur": getattr(IA.fournisseur(), "nom", "")})
