"""Onglet Cohérence : alertes sur les données (contributeurs, validateurs, admin) et règles entre KPI (admin)."""
from collections import Counter
from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse

from parametres import ia as IA
from parametres import libelles as LB
from parametres import niveaux as N
from parametres.libelles import libelle
from referentiel import formule as F
from referentiel.models import KPI, verifier_formule
from referentiel.plans import Plan

from . import coherence as CO
from . import saisie as S
from . import tri as TRI
from .calcul import NA, Calculateur, ouverte
from .models import Alerte, Campagne, Journal, RegleCoherence, Reponse
from .templatetags.collecte import avec_pourcent, formater, nombre
from .views import groupes_campagnes
from .vues_communes import campagne_affichee, est_script, exiger_admin


def alertes_visibles(utilisateur, campagne):
    """Admin : toutes. Contributeur : ses cases. Validateur : son périmètre (et les calculs impossibles qu'il peut voir)."""
    return CO.alertes_visibles(utilisateur, campagne)


STATUTS_FILTRE = ["a_traiter", "justifiee", "acceptee", "corrigee", "ignoree", "toutes"]  # libellés : saisie.coherence.filtre.<code>


@login_required
def coherence(request):
    campagne = campagne_affichee(request)
    if campagne is None:
        return render(request, "collecte/aucune_campagne.html")
    if not request.user.lecture_seule and (campagne.statut != Campagne.Statut.CLOTUREE
                                           or not Alerte.objects.filter(campagne=campagne).exists()):
        # toujours à jour à l'ouverture de la page (un lecteur ou un auditeur n'écrit rien) ; verrou seulement s'il y a
        # quelque chose à écrire
        CO.controler_a_l_ouverture(campagne)
    plan = Plan(campagne.referentiel)
    toutes = alertes_visibles(request.user, campagne)
    statut = request.GET.get("statut", "a_traiter")
    # un ou plusieurs contrôles à la fois (champ de filtre à cocher) : ?controle=a&controle=b
    connus = {c for c, _ in Alerte.Controle.choices}
    controles = [c for c in dict.fromkeys(request.GET.getlist("controle")) if c in connus]
    controle = ",".join(controles)
    org = request.GET.get("org", "")

    def garde(a):
        if statut == "a_traiter" and (not a.a_traiter or (a.controle == Alerte.Controle.CALCUL and controles != [a.controle])):
            return False  # « À traiter » : les calculs impossibles sont à part (information, rien à justifier)
        if statut not in ("a_traiter", "toutes") and a.statut != statut:
            return False
        return (not controles or a.controle in controles) and (not org or str(a.organisation_id) == org)

    arbre = S.arbre_organisations()  # parents déjà reliés : le tri ne remonte pas l'arbre en base pour chaque alerte
    alertes = sorted([a for a in toutes if garde(a)],
                     key=lambda a: (a.gravite != "bloquante", a.gravite == "info", S.cle_arbre(arbre.get(a.organisation_id, a.organisation)),
                                    plan.position(a.kpi_id, a.kpi.ordre)))
    # colonnes triées par la personne (_app/13_tableaux.js) : aussi ici, avant de couper la liste à 500 lignes
    col, decroissant = TRI.demande(request, "alertes", ("statut", "kpi", "organisation", "date"))
    if col:
        alertes = TRI.trier(alertes, {"statut": lambda a: TRI.texte(LB.choix(a, "statut")), "kpi": lambda a: TRI.texte(a.kpi.nom),
                                      "organisation": lambda a: TRI.texte(a.organisation.nom),
                                      "date": lambda a: CO.date_etat(a)}[col], decroissant)
    a_traiter = [a for a in toutes if a.a_traiter]
    # « À traiter » : même nombre que le bandeau de Saisie, Pour moi et « Je réponds à » (CO.alertes_a_traiter)
    a_justifier = [a for a in toutes if CO.a_justifier(a)]
    par_controle = [(code, LB.choix_valeur(Alerte, "controle", code), sum(1 for a in a_justifier if a.controle == code))
                    for code, _ in Alerte.Controle.choices if code != Alerte.Controle.CALCUL]
    compte_statut = {
        "a_traiter": len(a_justifier), "toutes": len(toutes),
        **{s: sum(1 for a in toutes if a.statut == s) for s in ("justifiee", "acceptee", "corrigee", "ignoree")},
    }
    orgs = sorted({arbre[a.organisation_id] for a in toutes if a.organisation_id in arbre}, key=S.cle_arbre)

    def prof(o):  # profondeur dans l'arbre (retrait du sélecteur, comme celui de la Saisie)
        n, p = 0, o.parent
        while p is not None:
            n, p = n + 1, p.parent
        return n

    # sélecteur d'organisation : même composant et même place que sur la Saisie 
    par_org = Counter(a.organisation_id for a in a_justifier)  # un passage sur les alertes, pas un par organisation
    choix_orgs = [(o, prof(o), par_org[o.id]) for o in orgs]
    org_choisie = next((o for o in orgs if str(o.id) == org), None)
    return render(request, "collecte/coherence/liste.html", {
        "page": "coherence", "campagne": campagne, "groupes_campagnes": groupes_campagnes(request.user), "alertes": alertes[:500],
        "trop": len(alertes) > 500, "par_controle": par_controle, "nb_a_justifier": len(a_justifier), "statuts": [(c, libelle("saisie.coherence.filtre." + c), compte_statut[c]) for c in STATUTS_FILTRE],
        "statut": statut, "controle": controle, "controles": controles, "qs_controles": "".join(f"&controle={c}" for c in controles),
        "voit_calculs": controles == [Alerte.Controle.CALCUL], "url_sans_filtre": f"?campagne={campagne.pk}" + (f"&org={org_choisie.id}" if org_choisie else ""), "nb_statut": compte_statut.get(statut, len(toutes)), "org": org, "orgs": orgs, "choix_orgs": choix_orgs, "org_choisie": org_choisie,
        "nb_bloquantes": sum(1 for a in a_justifier if a.gravite == Alerte.Gravite.BLOQUANTE),
        "nb_calculs": len(a_traiter) - len(a_justifier),
        "nb_regles": RegleCoherence.objects.filter(actif=True).count(),
    })


@login_required
def alerte(request, pk):
    """Détail d'une alerte : constat, historique de la case, justification, décision de l'admin."""
    a = get_object_or_404(Alerte.objects.select_related("campagne__referentiel", "campagne__periode", "kpi", "organisation", "regle"), pk=pk)
    if not CO.peut_voir(request.user, a):  # même règle que le panneau de saisie : une alerte traitée reste visible
        raise PermissionDenied(libelle("saisie.coherence.erreur.hors_perimetre"))
    succes, erreur = "", ""
    if request.method == "POST":
        try:
            CO.traiter(request.user, a, request.POST.get("action"), request.POST.get("texte", ""))
            succes = libelle("saisie.coherence.succes." + request.POST.get("action"))
        except ValidationError as e:
            erreur = " ".join(e.messages)
        if not est_script(request) and succes:
            return redirect("collecte:coherence")
    p = a.campagne.periode
    histo = (Reponse.objects.filter(kpi=a.kpi, organisation=a.organisation, periode__type=p.type, periode__debut__lte=p.debut)
             .select_related("periode").order_by("-periode__debut")[:7])
    ctx = {"a": a, "succes": succes, "erreur": erreur, "admin": request.user.est_admin,
           # calcul impossible, campagne clôturée : pas de formulaire, l'explication du panneau (une seule règle)
           "non_justifiable": CO.motif_justification_refusee(request.user, a),
           "historique": [(str(r.periode), formater(NA if r.non_applicable else r.valeur, a.kpi), r.commentaire, r.periode_id == p.pk)
                          for r in histo],
           "url_saisie": reverse("collecte:cellule", args=[a.campagne.pk, a.kpi_id, a.organisation_id]),
           "equation": equation(a) if a.regle else None,
           "ia_explication": (not request.user.lecture_seule and CO.explicable_par_ia(a, frozenset())
                              and IA.bouton_visible("expliquer_alerte") and CO.explicable_par_ia(a))}
    if est_script(request):
        return JsonResponse({"html": render_to_string("collecte/coherence/_alerte.html", ctx, request=request), "ok": bool(succes)})
    return render(request, "collecte/administration/page_panneau.html", {
        **ctx, "gabarit": "collecte/coherence/_alerte.html", "titre_page": libelle("saisie.coherence.alerte.titre_page", kpi=a.kpi.nom, organisation=a.organisation.nom),
        "retour": (reverse("collecte:coherence"), libelle("saisie.coherence.alerte.retour"))})


def equation(a):
    """Constat d'une règle sous forme lisible : chaque côté avec ses KPI, leurs valeurs, le total, puis l'écart."""
    r, calc = a.regle, Calculateur(a.campagne)
    p = calc.periode
    try:
        refs = {cote: F.references(getattr(r, cote)) for cote in ("gauche", "droite")}
    except F.FormuleInvalide:
        return None
    kpis = KPI.objects.in_bulk({x.kpi for v in refs.values() for x in v})

    def cote(nom):
        lignes = []
        for ref in dict.fromkeys(refs[nom]):
            k = kpis.get(ref.kpi)
            q = calc.calendrier.resoudre(p, ref.decalage)
            v = calc.valeur(ref.kpi, a.organisation_id, q) if q is not None else None
            lignes.append({"kpi": k, "id": ref.kpi, "annee": None if q is p else (str(q) if q else ref.decalage),
                           "valeur": "–" if v is None else formater(v, k) if k else str(v),
                           "url": reverse("collecte:cellule", args=[a.campagne.pk, ref.kpi, a.organisation_id]) if q is p else ""})
        total = CO.evaluer(calc, getattr(r, nom), a.organisation)
        simple = len(lignes) == 1 and getattr(r, nom).strip().startswith("[") and getattr(r, nom).strip().endswith("]")
        k = CO.kpi_d_affichage(calc.kpis, getattr(r, nom), getattr(r, "droite" if nom == "gauche" else "gauche"))
        return {"lignes": lignes, "formule": libelle("saisie.coherence.equation.total",
                                           formule=getattr(r, nom).replace("[", "").replace("]", "").replace("*", "×").replace("/", "÷")),
                "simple": simple,
                "total": None if total is None or total is NA else CO.afficher(total, k)}

    g, d = cote("gauche"), cote("droite")
    gv, dv = CO.evaluer(calc, r.gauche, a.organisation), CO.evaluer(calc, r.droite, a.organisation)
    ecart = None
    if gv not in (None, NA) and dv not in (None, NA):
        diff = gv - dv
        ecart = {"diff": ("+" if diff > 0 else "") + CO.afficher(diff, CO.kpi_d_affichage(calc.kpis, r.gauche, r.droite)),
                 "pct": avec_pourcent(("+" if diff > 0 else "") + nombre(diff / dv * 100, 1)) if dv else "",
                 "ok": CO.respecte(r, gv, dv)}
    return {"gauche": g, "droite": d, "operateur": r.operateur.replace("<=", "≤").replace(">=", "≥"),
            "operateur_texte": LB.choix(r, "operateur").split(" ", 1)[1], "ecart": ecart,
            "tolerance": nombre(r.tolerance * 100, 2).rstrip("0").rstrip(",") if r.tolerance else ""}


# ---------------------------------------------------------------- règles (admin)
class RegleForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["operateur"].choices = [(v, LB.choix_valeur(RegleCoherence, "operateur", v)) for v, _ in self.fields["operateur"].choices]
        self.fields["tolerance"].widget.attrs.update(min="0", max="1")  # écart relatif : de 0 à 1 (= 100 %)

    class Meta:
        model = RegleCoherence
        fields = ["nom", "description", "gauche", "operateur", "droite", "tolerance", "niveau", "bloquante", "actif"]
        widgets = {"gauche": forms.Textarea(attrs={"rows": 2, "class": "code"}), "droite": forms.Textarea(attrs={"rows": 2, "class": "code"}),
                   "description": forms.Textarea(attrs={"rows": 2})}

    def clean_tolerance(self):
        t = self.cleaned_data["tolerance"]
        if t is not None and not 0 <= t <= 1:
            raise ValidationError(libelle("saisie.coherence.regle.tolerance_bornes"))
        return t

    def clean(self):
        d = super().clean()
        for champ in ("gauche", "droite"):
            if d.get(champ):
                try:
                    verifier_formule("__regle__", d[champ])
                except ValidationError as e:
                    self.add_error(champ, e)
        if not self.errors:  # « [TXF] <= 30 » : un pourcentage est rangé en fraction, la règle ne se déclencherait jamais
            for champ, autre in (("gauche", "droite"), ("droite", "gauche")):
                texte = (d.get(champ) or "").strip()
                try:
                    nombre = Decimal(texte)
                except (InvalidOperation, ValueError):
                    continue
                refs = F.references(d.get(autre) or "")
                k = KPI.objects.filter(pk=refs[0].kpi).first() if len(refs) == 1 else None
                if k is not None and k.est_pourcentage and abs(nombre) > 1:
                    self.add_error(champ, libelle("saisie.coherence.regle.pourcentage_fraction", kpi=k.nom,
                                                  fraction=format((nombre / 100).normalize(), "f"), texte=texte))
        return d


@login_required
def regles(request):
    exiger_admin(request)
    liste = RegleCoherence.objects.annotate(nb=Count("alertes", filter=Q(alertes__statut__in=Alerte.A_TRAITER)))
    kpis = KPI.objects.in_bulk({k for r in liste for k in CO.kpis_de(r)})
    doubles = CO.doublons([r for r in liste if r.actif])  # même condition qu'une autre règle active : non contrôlée
    for r in liste:
        r.lecture_gauche, r.lecture_droite = lecture(r.gauche, kpis), lecture(r.droite, kpis)
        r.doublon_de = doubles[r.pk].nom_affiche if r.pk in doubles else ""
        r.tolerance_pct = nombre(r.tolerance * 100, 2).rstrip("0").rstrip(",")
    return render(request, "collecte/coherence/regles.html", {"page": "coherence", "regles": liste, "campagne": S.campagne_courante()})


def lecture(texte, kpis):
    """Formule avec les noms des KPI, pour la liste des règles."""
    def nom(m):
        r = m.group(0)[1:-1].split("@")
        k = kpis.get(r[0].strip())
        return libelle("saisie.guillemets", texte=k.nom if k else r[0]) + (f" ({r[1]})" if len(r) > 1 else "")
    morceaux, debut = [], 0
    for m in F.TOKEN_REF.finditer(texte):  # opérateurs remplacés hors des noms (« 31/12 » reste intact)
        morceaux += [texte[debut:m.start()].replace("*", "×").replace("/", "÷"), nom(m)]
        debut = m.end()
    return "".join(morceaux + [texte[debut:].replace("*", "×").replace("/", "÷")])


@login_required
def regle(request, pk=None):
    exiger_admin(request)
    r = get_object_or_404(RegleCoherence, pk=pk) if pk else RegleCoherence()
    if not pk:  # niveau proposé : celui où se saisissent le plus de KPI
        r.niveau_id = KPI.objects.values_list("granularite").annotate(n=Count("pk")).order_by("-n").values_list("granularite", flat=True).first()
    form, succes, test = RegleForm(instance=r), "", None
    campagne = S.campagne_courante()
    if request.method == "POST":
        form = RegleForm(request.POST, instance=r)
        if form.is_valid():
            if request.POST.get("action") == "tester":
                test = tester_regle(form.save(commit=False), campagne)
            else:
                nouvelle = not r.pk
                r = form.save()
                Journal.ecrire(request.user, "regle_coherence", r, "règle", "" if nouvelle else "(modifiée)", r.nom)
                for c in Campagne.objects.exclude(statut=Campagne.Statut.CLOTUREE):
                    CO.controler(c)
                succes = libelle("saisie.coherence.regle.creee" if nouvelle else "saisie.coherence.regle.enregistree")
                form = RegleForm(instance=r)
                if not est_script(request):
                    return redirect("collecte:regles")
    ctx = {"r": r, "form": form, "succes": succes, "test": test, "campagne": campagne, "niveaux": N.tous()}
    if est_script(request):
        return JsonResponse({"html": render_to_string("collecte/coherence/_regle.html", ctx, request=request), "ok": bool(succes)})
    return render(request, "collecte/administration/page_panneau.html", {
        **ctx, "gabarit": "collecte/coherence/_regle.html", "titre_page": (libelle("saisie.coherence.regle.titre_page", regle=r.nom) if r.pk
                       else libelle("saisie.coherence.regle.titre_page_nouvelle")),
        "retour": (reverse("collecte:regles"), libelle("saisie.coherence.regle.retour"))})


@login_required
def regle_basculer(request, pk):
    """Active ou met en pause une règle depuis la liste."""
    exiger_admin(request)
    r = get_object_or_404(RegleCoherence, pk=pk)
    if request.method == "POST":
        r.actif = not r.actif
        r.save(update_fields=["actif"])
        Journal.ecrire(request.user, "regle_coherence", r, "statut", "inactive" if r.actif else "active", "active" if r.actif else "inactive")
        for c in Campagne.objects.exclude(statut=Campagne.Statut.CLOTUREE):
            CO.controler(c)
    return redirect("collecte:regles")


def tester_regle(r, campagne):
    """Résultat de la règle pour chaque organisation du niveau, sur la campagne courante."""
    calc = Calculateur(campagne)
    res = []
    arbre = calc.orgs_de(calc.periode)  # arbre de la période (celui de sa clôture si elle est close ou gardée)
    for org in sorted(arbre.values(), key=S.cle_arbre):
        if org.niveau_id != r.niveau_id or not ouverte(org, calc.periode, arbre):  # comme le contrôle 
            continue
        g, d = CO.evaluer(calc, r.gauche, org), CO.evaluer(calc, r.droite, org)
        ok = None if g is None or d is None or g is NA or d is NA else CO.respecte(r, g, d)
        res.append({"org": org, "gauche": "–" if g is None else "N/A" if g is NA else nombre(g, 2),
                    "droite": "–" if d is None else "N/A" if d is NA else nombre(d, 2), "ok": ok})
    return res
