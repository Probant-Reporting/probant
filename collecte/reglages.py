"""Réglage du référentiel depuis l'outil : fiche KPI, place dans les référentiels, formule, ordre (cahier des charges,
section 4.1)."""
from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.utils.functional import lazy

from parametres import langues as L
from parametres import libelles as LB
from parametres.libelles import libelle
from parametres.models import CategorieDescription, ChampPersonnalise, TypeSaisie
from parametres.rapprochement_unites import (PREFIXES_CASSE, casse_seule, familles_catalogue,  # noqa: F401 (noms repris ici)
                                             symbole_normalise)
from referentiel import formule as F
from referentiel.composition import ordre_suivant
from referentiel.echange import enregistrer_descriptions
from referentiel.models import KPI, ElementReferentiel, KPIFormule, Referentiel, Theme, verifier_formule

from . import dates_courtes as DC
from .calcul import NA, Calculateur, ouverte, recalculer
from .models import Campagne, Journal, Reponse
from espaces import contexte as ESP

_l = lazy(libelle, str)  # libellé évalué à l'affichage (champs de formulaire définis à l'import)

# Champs dont le changement modifie les valeurs calculées : confirmation si la campagne ouverte a des réponses
CHAMPS_CALCUL = {"formule", "granularite", "methode_agregation", "agregation_temps", "actif", "type_saisie", "type_reponse",
                 "saisie_au_dessus", "na_compte_zero"}
CHAMPS_FICHE = [
    "equipe_responsable", "type_saisie", "type_reponse", "unite", "decimales",
    "granularite", "methode_agregation", "agregation_temps", "formule", "na_compte_zero", "saisie_au_dessus", "preuve_obligatoire",
    "confidentialite", "actif",
]


def champ_personnalise(c):
    """Champ de formulaire d'un champ personnalisé (Référentiels › Unités et formats)."""
    T = ChampPersonnalise.Type
    if c.type == T.CASE:
        return forms.BooleanField(label=c.libelle, required=False)
    if c.type == T.LISTE:
        return forms.ChoiceField(label=c.libelle, required=False, choices=[("", "—")] + c.valeurs_traduites())
    if c.type == T.DATE:
        return forms.DateField(label=c.libelle, required=False, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    return forms.CharField(label=c.libelle, required=False, max_length=500)


def valeur_champ(c, v):
    """Valeur stockée d'un champ personnalisé (None = rien à garder)."""
    if c.type == ChampPersonnalise.Type.CASE:
        return True if v else None
    if c.type == ChampPersonnalise.Type.DATE:
        return v.isoformat() if v else None
    return (v or "").strip() or None


# ---------------------------------------------------------------- format d'un KPI : figé par ses réponses et ses formules
# Mêmes contrôles dans la fiche KPI et aux imports (fichier du référentiel, classeur de configuration, fichier référentiel)
FORMATS_NUMERIQUES = ("nombre", "pourcentage")


def reponses_saisies():
    """Réponses saisies ou importées qui portent une valeur ou une réponse (ni calcul, ni agrégat, ni cumul ; un N/A n'en
    porte pas), validées ou en brouillon, de toutes les périodes."""
    return (Reponse.objects.exclude(origine__in=[Reponse.Origine.CALCUL, Reponse.Origine.AGREGATION, Reponse.Origine.CUMUL])
            .exclude(valeur__isnull=True, texte=""))


def nb_reponses_saisies(code):
    """Réponses saisies ou importées d'un KPI qui portent une valeur ou une réponse (ni calcul, ni agrégat, ni cumul)."""
    return reponses_saisies().filter(kpi_id=code).count()


def motif_format_fige(code, avant, apres):
    """Refus du changement de format (nombre, pourcentage, oui / non, liste) d'un KPI qui a des réponses saisies ou
    importées : les valeurs enregistrées changeraient de sens (300 kWh lus 30 000 %, 35 % lus 0,35). ``avant``,
    ``apres`` : types de réponse. Renvoie le motif, ou "" si le changement est possible."""
    if avant is None or apres is None or avant.format == apres.format:
        return ""
    n = nb_reponses_saisies(code)
    if not n:
        return ""
    return libelle("admin.kpi.format_fige", n=n, format=LB.choix_phrase(avant, "format"))


# ---------------------------------------------------------------- unité d'un KPI : figée par ses réponses
# Règle du projet (« N3 ») : comme le format. Mêmes contrôles dans la fiche KPI, le fichier du référentiel,
# le classeur de configuration et le fichier référentiel (paquet, mise à jour d'un modèle de la bibliothèque).
def motif_unite_figee(code, avant, apres):
    """Refus du changement d'unité d'un KPI qui a des réponses saisies ou importées : les valeurs enregistrées changeraient
    de sens (1 234 m³ lus 1 234 L à côté de l'année suivante). ``avant``, ``apres`` : unités (ou None, sans unité). Renvoie
    le motif, ou "" si le changement est possible. Retirer l'unité ou en donner une à un KPI qui n'en avait pas est un
    changement comme un autre (règle la plus prudente). ``avant`` peut aussi être un code d'unité (lu seulement s'il faut
    le motif)."""
    if (avant if isinstance(avant, str) else getattr(avant, "pk", None)) == getattr(apres, "pk", None):
        return ""
    n = nb_reponses_saisies(code)
    if not n:
        return ""
    if isinstance(avant, str):
        from parametres.models import Unite

        avant = Unite.objects.filter(pk=avant).first()
    if avant is None:
        return libelle("admin.kpi.unite_figee_sans", n=n)
    return libelle("admin.kpi.unite_figee", n=n, unite=avant.symbole)


def symboles_equivalents(a, b):
    """Deux écritures du même symbole (« m3 » et « m³ », « t CO2e » et « tCO₂e ») : corriger l'une en l'autre ne change pas
    le sens des valeurs (règle la plus prudente, à confirmer : une correction plus large reste refusée)."""
    return symbole_normalise(a) == symbole_normalise(b)


def _symboles(unite_ou_valeurs):
    """{langue ou "" (référence) : symbole affiché} d'une unité, ou de (symbole, traductions)."""
    if isinstance(unite_ou_valeurs, tuple):
        symbole, traductions = unite_ou_valeurs
    else:
        symbole, traductions = unite_ou_valeurs.symbole, unite_ou_valeurs.traductions
    sortie = {"": symbole or ""}
    for lg, textes in (traductions or {}).items():
        if isinstance(textes, dict) and textes.get("symbole"):
            sortie[lg] = textes["symbole"]
    return sortie


_familles_catalogue = familles_catalogue


def raisons_casse(code, avant, apres):
    """Raisons de confirmer un changement de casse seule du symbole ``avant`` en ``apres`` (unité ``code``), en texte :
    première lettre m/M, k/K, g/G, p/P, t/T changée ; autre unité de l'installation au même symbole à la casse près ;
    écriture du catalogue où la casse change le sens. Liste vide : rien à confirmer (règle à confirmer)."""
    from parametres.models import Unite

    na, nb = symbole_normalise(avant), symbole_normalise(apres)
    raisons = []
    if na[:1] != nb[:1] and na[:1].lower() in PREFIXES_CASSE:
        raisons.append(libelle("admin.referentiel.casse.prefixe", avant=na[:1], apres=nb[:1]))
    autres = set()
    for u in Unite.objects.exclude(pk=code):
        for s in _symboles(u).values():
            if symbole_normalise(s).casefold() == nb.casefold():
                autres.add(s)
    for s in sorted(autres):
        raisons.append(libelle("admin.referentiel.casse.autre_unite", symbole=s))
    ecritures = _familles_catalogue().get(nb.casefold(), set()) - {nb} - {symbole_normalise(s) for s in autres}
    if ecritures:
        raisons.append(libelle("admin.referentiel.casse.catalogue", symboles=" / ".join(sorted(ecritures))))
    return raisons


def motif_symbole_unite(code, avant, apres):
    """Refus d'un changement du symbole d'une unité (code ``code``) dont un KPI a des réponses saisies ou importées, sauf une
    correction d'écriture (``symboles_equivalents``) ou un changement de casse seule (``casse_seule``) ;
\1``avertissement_symbole_unite`` dit quand le confirmer) ; dans la langue de référence et dans chaque
    traduction (une langue sans traduction affiche le symbole de référence). ``avant``, ``apres`` : (symbole,
    traductions). Renvoie le motif ou ""."""
    paires = _paires_symboles(avant, apres)
    if all(symboles_equivalents(a, b) or casse_seule(a, b) for a, b in paires):
        return ""
    n = _nb_kpis_avec_valeurs(code)
    if not n:
        return ""
    return libelle("admin.referentiel.erreur.symbole_fige", n=n)


def avertissement_symbole_unite(code, avant, apres):
    """Texte à faire confirmer avant un changement de casse seule du symbole d'une unité dont un KPI a des valeurs, quand la
    casse peut en changer le sens (``raisons_casse``) ; "" sinon (rien à confirmer, ou changement refusé par
    ``motif_symbole_unite``, à appeler d'abord)."""
    paires = [(a, b) for a, b in _paires_symboles(avant, apres) if casse_seule(a, b)]
    textes = []
    for a, b in dict.fromkeys(paires):
        raisons = raisons_casse(code, a, b)
        if raisons:
            textes.append(libelle("admin.referentiel.casse.change", avant=a, apres=b, raisons=" ".join(raisons)))
    if not textes:
        return ""
    n = _nb_kpis_avec_valeurs(code)
    if not n:
        return ""
    return " ".join(textes) + " " + libelle("admin.referentiel.casse.verifier", n=n)


def _paires_symboles(avant, apres):
    s_avant, s_apres = _symboles(avant), _symboles(apres)
    return [(s_avant.get(lg, s_avant[""]), s_apres.get(lg, s_apres[""])) for lg in sorted(set(s_avant) | set(s_apres))]


def _nb_kpis_avec_valeurs(code):
    return reponses_saisies().filter(kpi__unite_id=code).values("kpi_id").distinct().count()


def citations(nouvelles=None):
    """{code d'un KPI : codes des KPI calculés dont la formule le cite}, d'après la base ; ``nouvelles`` : {code d'un KPI :
    sa formule après un import ("" s'il n'est pas calculé)}, qui remplace la sienne."""
    nouvelles = nouvelles or {}
    cites = {}
    for c, s in KPIFormule.objects.values_list("kpi_calcule_id", "kpi_source_id"):
        if c not in nouvelles:
            cites.setdefault(s, set()).add(c)
    for c, texte in nouvelles.items():
        for s in F.codes_cites(texte):
            cites.setdefault(s, set()).add(c)
    return cites


def motif_cite_en_formule(format_apres, citants):
    """Refus du passage en oui / non ou liste d'un KPI cité dans une formule : la formule ne se calculerait plus.
    ``citants`` : codes des KPI calculés qui le citent. Renvoie le motif, ou "" si le changement est possible."""
    if format_apres in (None, *FORMATS_NUMERIQUES) or not citants:
        return ""
    liste = sorted(citants)
    return libelle("admin.kpi.cite_en_formule", n=len(liste), codes=", ".join(liste))


def nb_valeurs_decimales(codes):
    """Réponses saisies ou importées non entières des KPI ``codes`` : une unité « nombre entier » les refuserait."""
    from .models import Reponse

    valeurs = Reponse.objects.filter(kpi_id__in=codes, origine__in=(Reponse.Origine.SAISIE, Reponse.Origine.IMPORT),
                                     valeur__isnull=False).values_list("valeur", flat=True)
    return sum(1 for v in valeurs.iterator() if v != v.to_integral_value())


def proposer_code():
    """Code proposé pour un nouveau KPI : « KPI » suivi du premier numéro libre (KPI0001, KPI0002…), à la casse près.
    Les codes existants ne changent jamais ; l'administrateur peut écrire le sien (option « Modifier le code »)."""
    pris = {c.upper() for c in KPI.objects.filter(code__istartswith=PREFIXE_CODE).values_list("code", flat=True)}
    n = 1
    while f"{PREFIXE_CODE}{n:04d}" in pris:
        n += 1
    return f"{PREFIXE_CODE}{n:04d}"


PREFIXE_CODE = "KPI"


@ESP.atomic
def inserer_pres(utilisateur, kpi, voisin, position):
    """Place un KPI tout juste créé juste avant (« avant ») ou juste après son voisin (élément d'un référentiel), s'il a
    bien été créé dans le même thème du même référentiel ; sinon il reste à la fin du thème choisi. Renvoie vrai si placé."""
    from referentiel.models import ElementReferentiel

    e = ElementReferentiel.objects.filter(kpi=kpi, referentiel_id=voisin.referentiel_id).first()
    if e is None or e.theme_id != voisin.theme_id:
        return False
    ids = [i for i in ElementReferentiel.objects.filter(referentiel_id=voisin.referentiel_id, theme_id=voisin.theme_id)
           .order_by("ordre", "kpi_id").values_list("kpi_id", flat=True) if i != kpi.pk]
    if voisin.kpi_id not in ids:
        return False
    ids.insert(ids.index(voisin.kpi_id) + (0 if position == "avant" else 1), kpi.pk)
    ranger(utilisateur, voisin.referentiel_id, voisin.theme_id, ids)
    return True


class KPIForm(forms.ModelForm):
    confirmer = forms.BooleanField(required=False, label=_l("admin.kpi.confirmer"))

    class Meta:
        model = KPI
        fields = ["code"] + CHAMPS_FICHE
        widgets = {
            "formule": forms.Textarea(attrs={"rows": 2, "class": "code", "placeholder": "[ACC-01] / [HEU-01] * 1000000"}),
        }

    def __init__(self, *args, referentiel_defaut=None, place=None, **kwargs):
        super().__init__(*args, **kwargs)
        LB.traduire_choix(self)
        if self.instance.pk:
            del self.fields["code"]  # le code est figé après création
        else:  # code proposé tout seul ; le modifier est une option (vide : le code proposé est repris)
            self.fields["code"].help_text = libelle("admin.kpi.code_aide")
            self.fields["code"].required = False
            self.code_propose = proposer_code()
            self.initial["code"] = self.code_propose
        # défaut appelable sur le modèle : Django comparerait à une valeur initiale cachée absente du gabarit (faux changement)
        self.fields["type_reponse"].show_hidden_initial = False
        self.fields["granularite"].label = libelle("admin.kpi.niveau_saisie")
        self.fields["granularite"].help_text = libelle("admin.kpi.niveau_saisie_aide")
        self.fields["unite"].empty_label = libelle("admin.kpi.sans_unite")
        self.fields["unite"].required = False
        self.categories = list(CategorieDescription.objects.all())
        self.champs_perso = list(ChampPersonnalise.objects.all())
        self._places(referentiel_defaut)
        if place and not self.instance.pk and place in dict(self.fields["ajout_place"].choices):  # « + KPI » d'un thème (composition)
            self.initial["ajout_place"] = place
        # textes traduisibles : un champ par langue active (nom, descriptions)
        self.ref = L.reference()
        self.langues = L.actives()
        k = self.instance
        textes = {(d.categorie_id, d.langue): d.texte for d in k.descriptions.all()} if k.pk else {}
        for lg in self.langues:
            self.fields[f"nom__{lg.code}"] = forms.CharField(label=libelle("admin.kpi.nom_langue", nom_langue=L.suffixe(lg.code)), required=False, max_length=300)
            self.initial.setdefault(f"nom__{lg.code}", L.texte(k, "libelle", lg.code) if k.pk else "")
            if k.pk and not self.initial[f"nom__{lg.code}"] and k.nom:  # nom absent dans cette langue : montrer celui affiché
                self.fields[f"nom__{lg.code}"].widget.attrs["placeholder"] = libelle("admin.kpi.a_traduire", nom=k.nom)
            for c in self.categories:
                nom = f"desc_{c.code}__{lg.code}"
                self.fields[nom] = forms.CharField(label=libelle("admin.kpi.description_langue", categorie=c.libelle, nom_langue=L.suffixe(lg.code)), required=c.obligatoire and lg.code == self.ref,
                                                   widget=forms.Textarea(attrs={"rows": 3}))
                self.initial.setdefault(nom, textes.get((c.code, lg.code), ""))
        for c in self.champs_perso:
            self.fields[f"champ_{c.code}"] = champ_personnalise(c)
            self.initial.setdefault(f"champ_{c.code}", self.instance.champs.get(c.code, False if c.type == "case" else ""))
        if self.unite_entiere:  # comptage : toujours 0 décimale (le champ est verrouillé, et suit le choix de l'unité)
            self.fields["decimales"].widget.attrs.update({"readonly": True, "aria-describedby": "aide-decimales-entier"})

    @property
    def unite_entiere(self):
        """L'unité choisie (ou celle du KPI) est un nombre entier (comptage) : 0 décimale."""
        from parametres.models import Unite

        code = self["unite"].value()
        return bool(code) and Unite.objects.filter(pk=code, entier=True).exists()

    def noms(self):
        return [(lg, self[f"nom__{lg.code}"]) for lg in self.langues]

    def _places(self, referentiel_defaut):
        """Place du KPI dans chaque référentiel : thème, obligatoire, retirer ; et « ajouter à un référentiel »."""
        refs = list(Referentiel.objects.all())
        themes = {}
        for t in Theme.objects.filter(referentiel__in=refs):
            themes.setdefault(t.referentiel_id, []).append(t)
        self.options_themes = {r.code: options_themes(themes.get(r.code, [])) for r in refs}
        k = self.instance
        self.elements = sorted(k.elements.select_related("referentiel"), key=lambda e: (e.referentiel.ordre, e.referentiel_id)) if k.pk else []
        for e in self.elements:
            c = e.referentiel_id
            self.fields[f"place_theme__{c}"] = forms.ChoiceField(required=False, choices=[("", libelle("admin.kpi.sans_theme"))] + self.options_themes[c])
            self.fields[f"place_obligatoire__{c}"] = forms.BooleanField(required=False)
            self.fields[f"place_retirer__{c}"] = forms.BooleanField(required=False)
            self.initial.update({f"place_theme__{c}": str(e.theme_id or ""), f"place_obligatoire__{c}": e.obligatoire, f"place_retirer__{c}": False})
        dans = {e.referentiel_id for e in self.elements}
        choix = [(f"{r.code}|", libelle("admin.kpi.ref_sans_theme", referentiel=str(r))) for r in refs if r.actif and r.code not in dans]
        for r in refs:
            if r.actif and r.code not in dans:
                choix += [(f"{r.code}|{v}", f"{r} › {l}") for v, l in self.options_themes[r.code]]
        self.fields["ajout_place"] = forms.ChoiceField(required=False, choices=[("", "—")] + sorted(choix, key=lambda c: c[1]))
        if not k.pk and referentiel_defaut is not None and referentiel_defaut.code not in dans:
            premier = next((v for v, _ in self.options_themes[referentiel_defaut.code]), "")
            self.initial.setdefault("ajout_place", f"{referentiel_defaut.code}|{premier}")

    def places(self):
        """[(élément, champ thème, champ obligatoire, champ retirer)]."""
        return [(e, self[f"place_theme__{e.referentiel_id}"],
                 self[f"place_obligatoire__{e.referentiel_id}"], self[f"place_retirer__{e.referentiel_id}"]) for e in self.elements]

    def descriptions(self):
        return [(c, [(lg, self[f"desc_{c.code}__{lg.code}"]) for lg in self.langues]) for c in self.categories]

    def completude(self):
        """[(langue, textes présents, textes attendus)] : nom et descriptions écrites dans une langue."""
        def v(nom):
            return (self.initial.get(nom) or "").strip()
        k = self.instance
        attendus = []
        if any(v(f"nom__{lg.code}") for lg in self.langues) or (k.pk and k.nom):
            attendus.append("nom__{}")
        attendus += [f"desc_{c.code}__{{}}" for c in self.categories if any(v(f"desc_{c.code}__{lg.code}") for lg in self.langues)]
        sortie = []
        for lg in self.langues:
            faits = sum(1 for a in attendus if v(a.format(lg.code)))
            sortie.append((lg, faits, len(attendus)))
        return sortie

    def champs_personnalises(self):
        return [(c, self[f"champ_{c.code}"]) for c in self.champs_perso]

    def clean_code(self):
        code = (self.cleaned_data.get("code") or "").strip() or proposer_code()
        autre = KPI.objects.filter(code__iexact=code).first()
        if autre:  # même code à la casse près : conflit (les formules et les fichiers ne les distingueraient pas)
            raise forms.ValidationError(libelle("admin.kpi.code_existe", code=autre.code, nom=autre.nom))
        return code

    def clean(self):
        donnees = super().clean()
        if donnees.get("unite") is not None and donnees["unite"].entier:
            donnees["decimales"] = 0  # unité « nombre entier » (comptage) : pas de décimales
            n = nb_valeurs_decimales([self.instance.pk]) if self.instance.pk and "unite" in self.changed_data else 0
            if n:  # ses valeurs décimales deviendraient refusées : une unité non entière 
                self.add_error("unite", libelle("admin.kpi.erreur.unite_entiere", n=n, unite=donnees["unite"].symbole))
        self._format_fige(donnees.get("type_reponse"))
        self._unite_figee(donnees.get("unite"))
        if self.instance.pk and ("type_reponse" in self._errors or "unite" in self._errors):
            # format refusé : le KPI garde le sien ; l'agrégation choisie pour le nouveau format (« Décompte » pour un oui /
            # non) n'est pas contrôlée contre l'ancien, ni la confirmation demandée (pas de message en cascade)
            donnees["methode_agregation"] = self.instance.methode_agregation
            return donnees
        changes = CHAMPS_CALCUL & set(self.changed_data)
        if self.instance.pk and changes and not donnees.get("confirmer"):
            n = reponses_ouvertes(self.instance)
            if n:
                raise forms.ValidationError(libelle("admin.kpi.confirmer_requis", n=n))
        return donnees


    def _format_fige(self, nouveau):
        """Le format (nombre, pourcentage, oui / non, liste) d'un KPI qui a des réponses saisies ou importées ne change plus :
        les valeurs déjà enregistrées changeraient de sens (300 kWh lus 30 000 %, 35 % lus 0,35). Un KPI cité dans une
        formule reste un nombre ou un pourcentage (« Ce KPI est utilisé dans la formule de … »)."""
        k = self.instance
        if not k.pk or nouveau is None or "type_reponse" not in self.changed_data:
            return
        avant = KPI.objects.select_related("type_reponse").get(pk=k.pk).type_reponse
        for motif in (motif_format_fige(k.pk, avant, nouveau),
                      motif_cite_en_formule(nouveau.format, KPIFormule.objects.filter(kpi_source_id=k.pk)
                                            .values_list("kpi_calcule_id", flat=True).distinct())):
            if motif:
                self.add_error("type_reponse", motif)

    def _unite_figee(self, nouvelle):
        """L'unité d'un KPI qui a des réponses saisies ou importées ne change plus, comme son format.
        Relue en base : la fiche a pu être ouverte avant un autre enregistrement."""
        k = self.instance
        if not k.pk or "unite" not in self.changed_data:
            return
        avant = KPI.objects.select_related("unite").get(pk=k.pk).unite
        motif = motif_unite_figee(k.pk, avant, nouvelle)
        if motif:
            self.add_error("unite", motif)


def options_themes(themes):
    """[(id, « Thème › Sous-thème »)] d'un référentiel, dans l'ordre de l'arbre."""
    par_parent, sortie = {}, []
    for t in themes:
        par_parent.setdefault(t.parent_id, []).append(t)

    def parcourir(parent, chemin):
        for t in sorted(par_parent.get(parent, []), key=lambda t: (t.ordre, t.id)):
            sortie.append((str(t.id), " › ".join(chemin + [t.tr("nom")])))
            parcourir(t.id, chemin + [t.tr("nom")])
    parcourir(None, [])
    return sortie


def enregistrer_places(utilisateur, form, kpi):
    """Place du KPI dans les référentiels : thème, obligatoire, retrait, ajout (journalisés)."""
    d = form.cleaned_data
    for e in form.elements:
        c = e.referentiel_id
        if d.get(f"place_retirer__{c}"):
            Journal.ecrire(utilisateur, "reglage_kpi", kpi, "Référentiel", e.referentiel, "(retiré)")
            e.delete()
            continue
        theme_id = int(d.get(f"place_theme__{c}") or 0) or None
        changes = []
        if theme_id != e.theme_id:
            avant = e.theme or "Sans thème"
            e.theme = Theme.objects.filter(pk=theme_id, referentiel_id=c).first()
            e.ordre = ordre_suivant(c, e.theme)
            changes.append((f"Thème ({c})", avant, e.theme or "Sans thème"))
        if bool(d.get(f"place_obligatoire__{c}")) != e.obligatoire:
            e.obligatoire = not e.obligatoire
            changes.append((f"Obligatoire ({c})", "non" if e.obligatoire else "oui", "oui" if e.obligatoire else "non"))
        if changes:
            e.save()
            for champ, avant, apres in changes:
                Journal.ecrire(utilisateur, "reglage_kpi", kpi, champ, avant, apres)
    ajout = d.get("ajout_place") or ""
    if "|" in ajout:
        code, theme_id = ajout.split("|", 1)
        ref = Referentiel.objects.filter(pk=code).first()
        theme = Theme.objects.filter(pk=theme_id, referentiel=ref).first() if theme_id.isdecimal() else None
        if ref is not None and not ElementReferentiel.objects.filter(referentiel=ref, kpi=kpi).exists():
            ElementReferentiel.objects.create(referentiel=ref, kpi=kpi, theme=theme, ordre=ordre_suivant(ref, theme))
            Journal.ecrire(utilisateur, "reglage_kpi", kpi, "Référentiel", "", f"{ref}" + (f" › {theme}" if theme else ""))
            from .demande_depuis import poser_a_la_creation

            # « L'ajouter aussi aux exercices précédents ? » : vide = l'exercice en cours
            poser_a_la_creation(utilisateur, ElementReferentiel.objects.get(referentiel=ref, kpi=kpi),
                                form.data.get(f"ajout_depuis__{ref.code}", ""))


def reponses_ouvertes(kpi):
    en_cours = Campagne.objects.filter(statut__in=[Campagne.Statut.OUVERTE, Campagne.Statut.REVUE]).values("periode_id")
    return Reponse.objects.filter(kpi=kpi, periode__in=en_cours).exclude(
        origine__in=[Reponse.Origine.CALCUL, Reponse.Origine.AGREGATION, Reponse.Origine.CUMUL]).count()


def _lisible(form, champ, valeur):
    """Valeur d'un champ pour le journal : une référence s'écrit par son nom (niveau, type, unité)."""
    f = form.fields.get(champ)
    if isinstance(f, forms.ModelChoiceField) and valeur not in (None, ""):
        valeur = getattr(valeur, "pk", valeur)
        return str(f.queryset.filter(pk=valeur).first() or valeur)
    return "" if valeur is None else valeur


def version_kpi(kpi):
    """Repère de la fiche telle qu'elle a été ouverte (date de dernière mise à jour du KPI)."""
    return kpi.date_maj.isoformat() if kpi.pk and kpi.date_maj else ""


def message_conflit_kpi(kpi):
    """Fiche modifiée par une autre personne depuis son ouverture : qui et quand (d'après le journal)."""
    from django.utils import timezone

    j = Journal.objects.filter(objet="KPI", objet_id=kpi.pk).select_related("utilisateur").order_by("-date").first()
    qui = (j.utilisateur if j and j.utilisateur else None) or libelle("admin.kpi.conflit_autre")
    quand = timezone.localtime(kpi.date_maj)
    return libelle("admin.kpi.conflit", qui=str(qui), date=DC.date_courte(quand), heure=f"{quand:%H:%M}")


@ESP.atomic
def enregistrer_kpi(utilisateur, form):
    """Enregistre la fiche (descriptions et champs personnalisés compris), journalise les champs modifiés,
    recalcule la campagne ouverte si besoin."""
    if form.instance.pk:  # deux enregistrements simultanés de la même fiche passent l'un après l'autre
        list(KPI.objects.select_for_update().filter(pk=form.instance.pk).values_list("pk", flat=True))
        enregistre = KPI.objects.select_related("unite").filter(pk=form.instance.pk).first()  # absent : nouveau KPI
        if enregistre is not None and "unite" in form.changed_data:  # relu sous verrou : une valeur a pu arriver depuis
            motif = motif_unite_figee(enregistre.pk, enregistre.unite, form.cleaned_data.get("unite"))  # la validation
            if motif:
                raise ValidationError({"unite": motif})
    modifies = [c for c in form.changed_data if c != "confirmer"]
    if form.instance.pk and "decimales" not in modifies and form.cleaned_data.get("decimales") != form.initial.get("decimales"):
        modifies.append("decimales")  # unité passée en « nombre entier » : 0 décimale, journalisé comme un changement de la fiche
    avant = {c: _lisible(form, c, form.initial.get(c)) for c in modifies}
    kpi = form.save(commit=False)
    kpi.na_compte_zero_choisi = True  # case de la fiche : le choix de l'admin est gardé, même décochée
    for lg in form.langues:
        L.definir(kpi, "libelle", lg.code, form.cleaned_data.get(f"nom__{lg.code}", ""))
    champs = dict(kpi.champs)
    for c in form.champs_perso:
        v = valeur_champ(c, form.cleaned_data.get(f"champ_{c.code}"))
        if v is None:
            champs.pop(c.code, None)
        else:
            champs[c.code] = v
    kpi.champs = champs
    kpi.save()
    libelles = {f"champ_{c.code}": c.libelle for c in form.champs_perso}
    for lg in form.langues:
        enregistrer_descriptions(kpi, {c.code: form.cleaned_data.get(f"desc_{c.code}__{lg.code}", "") for c in form.categories}, lg.code)
        suffixe = L.suffixe(lg.code)
        libelles |= {f"desc_{c.code}__{lg.code}": f"{c.libelle} {suffixe}" for c in form.categories}
        libelles |= {f"nom__{lg.code}": f"Nom {suffixe}"}
    enregistrer_places(utilisateur, form, kpi)
    for champ in modifies:
        if champ.startswith(("place_", "ajout_place")):
            continue  # journalisés par enregistrer_places
        apres = form.cleaned_data.get(champ) if "__" in champ or champ.startswith(("desc_", "champ_")) else getattr(kpi, champ, "")
        Journal.ecrire(utilisateur, "reglage_kpi", kpi, libelles.get(champ, champ), avant[champ], _lisible(form, champ, apres))
    return kpi, apres_reglage(kpi, set(form.changed_data) if form.initial else CHAMPS_CALCUL)


def apres_reglage(kpi, champs_modifies):
    """Recalcule les périodes des campagnes en cours si un champ de calcul a changé. Renvoie les campagnes recalculées."""
    if not CHAMPS_CALCUL & set(champs_modifies):
        return []
    faites, noms = set(), []
    for c in Campagne.objects.filter(statut__in=[Campagne.Statut.OUVERTE, Campagne.Statut.REVUE]).select_related("referentiel", "periode"):
        if c.periode_id not in faites:
            recalculer(c, [kpi.code])
            faites.add(c.periode_id)
        noms.append(c.nom_complet)
    return noms


def sources_et_utilisations(kpi):
    """(sources de la formule, KPI qui utilisent celui-ci), avec le décalage d'exercice."""
    sources = KPIFormule.objects.filter(kpi_calcule=kpi).select_related("kpi_source").order_by("kpi_source_id")
    utilisations = KPIFormule.objects.filter(kpi_source=kpi).select_related("kpi_calcule").order_by("kpi_calcule_id")
    return [(l.kpi_source, l.decalage) for l in sources], [(l.kpi_calcule, l.decalage) for l in utilisations]


def tester_formule(kpi, formule, campagne):
    """Évalue une formule (non enregistrée) sur une campagne, pour chaque organisation du niveau du KPI ouverte pendant la période.

    Lève ValidationError si la formule est invalide. Renvoie, par organisation, le résultat et les étapes :
    valeur de chaque KPI source, puis le calcul avec les valeurs à la place des ID."""
    verifier_formule(kpi.code, formule)
    from .templatetags.collecte import formater

    calc = Calculateur(campagne)
    essai = KPI(**{f.attname: getattr(kpi, f.attname) for f in KPI._meta.concrete_fields})
    essai.type_saisie = TypeSaisie.objects.filter(comportement="calcul").first() or TypeSaisie(code="calcul", comportement="calcul")
    essai.formule = formule
    calc.kpis[essai.code] = essai
    refs = F.references(formule)
    resultats = []
    arbre = calc.orgs_de(calc.periode)  # arbre de la période (celui de sa clôture si elle est close ou gardée)
    for org in sorted(arbre.values(), key=lambda o: (o.rang, o.nom)):
        if org.niveau_id != essai.granularite_id or not ouverte(org, calc.periode, arbre):  # comme le calcul
            continue
        v = calc._formule(essai, org, calc.periode)
        na_zero = essai.na_compte_zero and v is not NA  # sources N/A comptées comme 0 dans ce résultat
        etapes, valeurs = [], {}
        for r in refs:
            q = calc.calendrier.resoudre(calc.periode, r.decalage)
            source = calc.kpis.get(r.kpi)
            vs = calc.valeur(r.kpi, org.id, q) if q is not None else None
            texte = formater(vs, source) if source else libelle("admin.kpi.inconnu")
            etapes.append({"ref": r, "kpi": source, "periode": q or r.decalage, "valeur": vs,
                           "texte": libelle("admin.kpi.na_zero") if vs is NA and na_zero else texte})
            valeurs[r] = vs

        def chiffre(r):
            vs = valeurs.get(r)
            if vs is None:
                return "?"
            if vs is NA:
                return "0" if na_zero else "N/A"
            if not isinstance(vs, Decimal):  # oui / non, liste : la réponse telle quelle
                return str(vs)
            from .templatetags.collecte import separateurs

            return format(vs.normalize(), "f").replace(".", separateurs()[1])

        def operateurs(t):
            return t.replace("*", "×").replace("/", "÷").replace(" - ", " − ")
        morceaux, pos = [], 0  # opérateurs remplacés hors des valeurs (« N/A » reste « N/A »)
        for m in F.TOKEN_REF.finditer(formule):
            morceaux += [operateurs(formule[pos:m.start()]), chiffre(F.Ref(*_ref_de(m.group(0))))]
            pos = m.end()
        expression = "".join(morceaux + [operateurs(formule[pos:])])
        resultats.append({"org": org, "valeur": v, "texte": formater(v, essai), "etapes": etapes, "expression": expression,
                          "message": calc.message(essai.code, org.id)})
    return resultats


def _ref_de(texte):
    m = F.REF.match(texte.strip())
    return m.group("id").strip(), (m.group("dec") or "N")


def references_lisibles(formule):
    """Liste (Ref, KPI ou None) des références d'une formule, pour l'afficher avec les noms."""
    try:
        refs = F.references(formule)
    except F.FormuleInvalide:
        return []
    kpis = KPI.objects.in_bulk([r.kpi for r in refs])
    return [(r, kpis.get(r.kpi)) for r in refs]


@ESP.atomic
def ranger(utilisateur, ref_code, theme_id, ids):
    """Range les KPI ``ids`` dans un thème d'un référentiel, dans cet ordre (1, 2, 3…) ; ceux qui venaient d'un autre
    thème y sont déplacés (journal). Renvoie (nombre de KPI rangés, nombre déplacés)."""
    from referentiel.models import ElementReferentiel, Referentiel, Theme

    ref = Referentiel.objects.filter(pk=ref_code).first()
    if ref is None:
        raise ValidationError(libelle("admin.kpi.referentiel_inconnu"))
    theme = Theme.objects.filter(pk=theme_id, referentiel=ref).first() if theme_id else None
    if theme_id and theme is None:
        raise ValidationError(libelle("admin.kpi.theme_inconnu"))
    elements = {e.kpi_id: e for e in ElementReferentiel.objects.filter(referentiel=ref, kpi_id__in=ids).select_related("theme")}
    deplaces = 0
    for n, kid in enumerate([i for i in ids if i in elements], start=1):
        e = elements[kid]
        champs = []
        if e.theme_id != (theme.pk if theme else None):
            Journal.ecrire(utilisateur, "reglage_kpi", e.kpi, f"Thème ({ref.code})", e.theme or "Sans thème", theme or "Sans thème")
            e.theme, deplaces = theme, deplaces + 1
            champs.append("theme")
        if e.ordre != n:
            e.ordre = n
            champs.append("ordre")
        if champs:
            e.save(update_fields=champs)
    return len(elements), deplaces

