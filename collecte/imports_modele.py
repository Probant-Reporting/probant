"""Fichier à remplir (modèle d'import pré-rempli) : onglets, validations, onglet « À lire » (cahier des charges, section 4.6).

Sorti de ``collecte/imports.py`` (rangement sans changement de comportement) : ``imports`` ré-exporte tous ces noms, un
appelant peut donc continuer d'écrire ``imports.modele(...)``. Ce module ne dépend pas de ``imports`` (pas de cycle) ;
l'analyse, l'application et le rapport des rejets restent dans ``imports.py``.
"""
from django.utils import timezone
from openpyxl.formatting.rule import FormulaRule
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.cell_range import CellRange, MultiCellRange
from openpyxl.worksheet.datavalidation import DataValidation

from referentiel.models import Organisation
from referentiel.plans import Plan

from . import dates_courtes as DC
from . import fichiers as X
from . import saisie as S
from .exports import langue_export, nom_kpi, traduire, valeur_fichier
from .models import Campagne, Reponse
from .styles_excel import Alignment, Font, PatternFill

LARGEUR_VALEUR_TEXTE = 30  # colonne Valeur du fichier à remplir quand il contient des réponses rédigées

# ---------------------------------------------------------------- fichier à remplir
# Un fichier lisible pour les contributeurs : bandeau d'explication et légende en haut de l'onglet de saisie, cellules
# jaunes à remplir (le reste est protégé, sans mot de passe), définition du KPI en bulle sur son nom, colonnes « État » et
# « À vérifier » calculées dans Excel (écart avec la période de comparaison au-delà du seuil, preuve obligatoire), lignes
# regroupées par organisation ou un onglet par organisation. Il se réimporte tel quel ; les anciens fichiers aussi.
def colonnes_a_remplir(comparaison="N-1"):
    C = X.Colonne
    k = "suivi.remplir.colonne."
    return [
        C("organisation", k + "organisation", 24, "cle"),
        C("kpi", k + "kpi", 11, "cle"),
        C("indicateur", k + "indicateur", 50, retour=True),
        C("unite", k + "unite", 11),
        C("n1", k + ("n1" if comparaison == "N-1" else "n1_autre"), 13, valeurs={"comparaison": comparaison}),
        C("valeur", k + "valeur", 14, "remplir"),
        C("na", k + "na", 7, "remplir"),
        C("commentaire", k + "commentaire", 40, "remplir", retour=True),
        C("etat", k + "etat", 11),
        C("verifier", k + "verifier", 36, retour=True),
        C("theme", k + "theme", 26),
        C("periode", k + "periode", 12, "cle"),
        C("exercice", k + "exercice", 9, "cle"),
        C("statut", k + "statut", 14),
        C("referentiel", k + "referentiel", 22),
        # clé stable de l'organisation : reconnue avant le nom à l'import (un nom qui change ne casse rien)
        C("code_org", "suivi.export.colonne.code_org", 16, "cle"),
    ]


# Onglet « À lire » du fichier à remplir : « # » = titre de section, sinon un paragraphe (titre + texte) ; les textes sont dans
# libelles/suivi.*.json (suivi.remplir.lire.<clé>, <clé>_titre, <clé>_texte)
LIRE = ["#comment_remplir", "remplir", "verifier", "deposer", "#regles", "nombres", "pourcentages", "oui_non", "redige", "na",
        "cellule_vide", "definitions", "preuves", "ajouter", "#colonnes", "obligatoires", "periode", "facultatives"]


def a_lire(langue, depuis=0, redige=False):
    """Paragraphes de l'onglet « À lire » (``depuis`` : rang du premier ; 4 = à partir des règles, pour le rapport des rejets ;
    ``redige`` : le fichier contient des réponses rédigées, leur règle d'écriture est donnée)."""
    sortie = []
    for cle in LIRE[depuis:]:
        if cle == "redige" and not redige:
            continue
        if cle.startswith("#"):
            sortie.append("# " + X.t(langue, f"suivi.remplir.lire.{cle[1:]}"))
        else:
            sortie.append((X.t(langue, f"suivi.remplir.lire.{cle}_titre"), X.t(langue, f"suivi.remplir.lire.{cle}_texte")))
    return sortie


def _definitions(kpis, langue):
    """{code du KPI: [(catégorie, texte)]} pour les catégories affichées au contributeur, dans la langue du fichier."""
    from parametres.models import CategorieDescription
    from referentiel.models import Description

    from parametres import langues as L

    categories = list(CategorieDescription.objects.filter(affichee=True))
    textes = {}
    for kid, cat, lg, t in Description.objects.filter(kpi_id__in=kpis).values_list("kpi_id", "categorie_id", "langue", "texte"):
        textes.setdefault((kid, cat), {})[lg] = t
    candidates = L.langues_candidates(langue)
    sortie = {}
    for kid in kpis:
        for c in categories:
            par_langue = textes.get((kid, c.code), {})
            t = next((par_langue[lg] for lg in candidates if par_langue.get(lg)), next(iter(par_langue.values()), ""))
            if t:
                sortie.setdefault(kid, []).append((c.tr("libelle", langue), t))
    return categories, sortie


def _nom_onglet(nom, pris):
    base = "".join(ch for ch in nom if ch not in '[]:*?/\\')[:31] or "Organisation"
    n, i = base, 2
    while n.lower() in pris:
        suffixe = f" ({i})"
        n, i = base[:31 - len(suffixe)] + suffixe, i + 1
    pris.add(n.lower())
    return n


def lignes_modele(utilisateur, campagne, org_id=None, seulement_a_faire=False, plan=None, selection=None, codes=None):
    """Cases saisissables de l'utilisateur pour la campagne (toutes pour l'admin), dans l'ordre de la page Saisie ;
    seulement celles du référentiel du ``plan`` s'il y en a un, des KPI ``codes`` cochés un à un s'il y en a, sinon de
    la liste sauvegardée ``selection`` (SelectionKPI) s'il y en a une."""
    org = Organisation.objects.filter(pk=org_id).first() if org_id else None
    ls = S.lignes(utilisateur, campagne, org=org, plan=plan)
    if codes:
        ls = [l for l in ls if l.kpi.code in codes]
    elif selection is not None:
        codes = set(selection.kpis.values_list("code", flat=True))
        ls = [l for l in ls if l.kpi.code in codes]
    for l in ls:
        l.plan = plan
    if seulement_a_faire:  # ce qui reste à faire : sans les KPI facultatifs (ils restent dans le fichier complet)
        ls = [l for l in ls if l.statut != Reponse.Statut.VALIDE and not l.facultatif]
    return ls


def campagnes_en_cours_de(utilisateur):
    """Campagnes en saisie ouverte (en revue aussi pour l'administrateur) des référentiels de la personne."""
    refs = S.referentiels_de(utilisateur)
    statuts = {Campagne.Statut.OUVERTE} | ({Campagne.Statut.REVUE} if utilisateur.est_admin else set())
    return [c for c in S.campagnes_en_cours() if c.referentiel in refs and c.statut in statuts]


def lignes_modele_en_cours(utilisateur, org_id=None, seulement_a_faire=False, selection=None, codes=None):
    """« Tous mes référentiels » : les cases des campagnes en saisie ouverte (en revue aussi pour l'administrateur) des
    référentiels de la personne, chaque ligne avec sa campagne (``l.campagne``). Un KPI commun à deux référentiels de
    même période n'y figure qu'une fois (dans le premier)."""
    sortie, vues = [], set()
    for c in campagnes_en_cours_de(utilisateur):
        for l in lignes_modele(utilisateur, c, org_id, seulement_a_faire, Plan(c.referentiel), selection, codes):
            cle = (c.periode_id, l.kpi.code, l.organisation.id)
            if cle not in vues:
                vues.add(cle)
                l.campagne = c
                sortie.append(l)
    return sortie


def modele(utilisateur, campagne, lignes, format="xlsx", style="fr", par_organisation=False, langue=None):
    """Fichier à remplir : une ligne par case (KPI × organisation), valeur actuelle et valeur de comparaison pré-remplies.
    ``par_organisation`` : un onglet par organisation (sinon une liste regroupée par organisation). ``langue`` : langue
    des en-têtes et des contenus (par défaut celle de la personne)."""
    from parametres import langues as L

    langue = langue or langue_export("")  # langue de l'interface (espagnol…) même sans traduction des contenus
    with L.activer(langue):
        return _modele(utilisateur, campagne, lignes, format, style, par_organisation, langue)


def _modele(utilisateur, campagne, lignes, format, style, par_organisation, langue):
    """Plusieurs campagnes (lignes portant ``l.campagne``, « tous mes référentiels ») : un onglet par campagne, chacun
    avec sa période, sa comparaison et son seuil d'écart."""
    tt = lambda cle, n=None, **kw: X.t(langue, cle, n, **kw)  # noqa: E731
    camp = lambda l: getattr(l, "campagne", None) or campagne  # noqa: E731
    campagnes = list(dict.fromkeys(camp(l) for l in lignes if camp(l) is not None))
    multiple = len(campagnes) > 1
    rangs_campagnes = {c.pk: i for i, c in enumerate(campagnes)}
    comparaison = S.libelle_comparaison(campagne) if campagne else "N-1"
    if multiple and len({S.libelle_comparaison(c) for c in campagnes}) > 1:
        comparaison = tt("suivi.remplir.de_comparaison")
    colonnes = colonnes_a_remplir(comparaison)
    rang = {c.cle: i for i, c in enumerate(colonnes)}
    lettre = {c.cle: get_column_letter(i + 1) for i, c in enumerate(colonnes)}
    plan = next((l.plan for l in lignes if getattr(l, "plan", None)), None) or Plan()
    plan_de = lambda l: getattr(l, "plan", None) or plan  # noqa: E731
    lignes = sorted(lignes, key=lambda l: (rangs_campagnes.get(camp(l).pk, 0) if camp(l) else 0, S.cle_arbre(l.organisation),
                                           plan_de(l).position(l.kpi.code, l.kpi.ordre)))
    orgs = list(dict.fromkeys(l.organisation for l in lignes))
    textes = {c: tt(f"suivi.remplir.etat_{c}") for c in ("a_remplir", "rempli", "facultatif")}
    textes["preuve"] = tt("suivi.remplir.preuve")
    textes["na_commentaire"] = tt("suivi.remplir.na_commentaire")
    fx = lambda texte: texte.replace('"', '""')  # noqa: E731 - dans une formule Excel, un guillemet du texte est doublé
    oui_langue = traduire("Oui", langue)  # « Oui » / « Yes » / « Sí » (colonne N/A et liste déroulante)

    def texte_ecart(seuil, comparaison):
        if seuil is None:
            return ""
        return tt("suivi.remplir.ecart", seuil=f"{seuil * 100:.0f}", comparaison=comparaison) + " "
    morceaux = [tt("suivi.remplir.nom_fichier"), tt("suivi.remplir.nom_tous") if multiple
                else campagne.nom_complet if campagne else tt("suivi.remplir.nom_vierge")]
    if len(orgs) == 1:
        morceaux.append(orgs[0].nom)
    nom = X.nom_fichier(*morceaux)

    # nom, unité et texte du statut écrits une fois par KPI et par statut : les mêmes pour chacune de leurs lignes
    # (fichier de 100 000 lignes)
    par_kpi, par_statut = {}, {}

    def du_kpi(k):
        if k.pk not in par_kpi:
            par_kpi[k.pk] = (nom_kpi(k, langue), k.symbole)
        return par_kpi[k.pk]

    def statut_texte(statut):
        if statut not in par_statut:
            par_statut[statut] = traduire(Reponse.Statut(statut).label, langue) if statut else ""
        return par_statut[statut]

    def donnees(l):
        k, r, c = l.kpi, l.reponse, camp(l)
        place = plan_de(l).decrire(k.code)
        indicateur, unite = du_kpi(k)
        na = oui_langue if r and r.non_applicable else ""
        valeur = valeur_fichier(r, k)
        d = {"organisation": l.organisation.nom, "kpi": k.code, "indicateur": indicateur, "unite": unite,
             "n1": "N/A" if l.n1 and l.n1.non_applicable else valeur_fichier(l.n1, k), "valeur": valeur, "na": na,
             "commentaire": r.commentaire if r else "", "theme": " › ".join(t for t in (place["theme"], place["sous_theme"]) if t),
             "periode": str(c.periode) if c else "", "exercice": c.exercice if c else None,
             "statut": statut_texte(l.statut), "referentiel": place["referentiel"], "code_org": l.organisation.code}
        # CSV : état et alertes figés au moment de l'export (dans Excel, ce sont des formules) ; un KPI facultatif vide
        # n'est pas « à remplir »
        vide = textes["facultatif"] if getattr(l, "facultatif", False) else textes["a_remplir"]
        d["etat"] = "N/A" if na else (textes["rempli"] if valeur not in (None, "") else vide)
        # mêmes contrôles que « Valider » (saisie.controles_validation) : N/A sans commentaire, preuve pas encore jointe
        d["verifier"] = " ".join(t for t, oui in (
            (textes["na_commentaire"], na and not d["commentaire"]),
            (textes["preuve"], k.preuve_obligatoire and not na and not getattr(l, "nb_preuves", 0))) if oui)
        return d

    if format == "csv":
        return X.reponse_csv([[c.titre(langue) for c in colonnes]] + [[d[c.cle] for c in colonnes] for d in map(donnees, lignes)],
                             nom, style)

    categories, definitions = _definitions({l.kpi.code for l in lignes}, langue)
    wb = X.classeur()
    if multiple:  # un onglet par campagne (référentiel et période)
        groupes = [(None, c, [l for l in lignes if camp(l) == c]) for c in campagnes]
    elif par_organisation and len(orgs) > 1:
        groupes = [(o, campagne, [l for l in lignes if l.organisation == o]) for o in orgs]
    else:
        groupes = [(None, campagne, lignes)]
    pris = {tt("suivi.fichier.a_lire").lower(), tt("suivi.remplir.onglet_definitions").lower()}
    vierge = not lignes
    for org, cg, ls in groupes:
        comparaison = S.libelle_comparaison(cg) if cg else "N-1"
        colonnes = colonnes_a_remplir(comparaison)
        seuil = cg.seuil_ecart if cg is not None else None
        textes["ecart"] = texte_ecart(seuil, comparaison)
        titre_onglet = (_nom_onglet(org.nom, pris) if org is not None else _nom_onglet(cg.nom_complet, pris) if multiple
                        else tt("suivi.remplir.onglet_saisie"))
        ws = wb.create_sheet(titre_onglet)
        ws.sheet_view.showGridLines = False
        ws.sheet_view.zoomScale = 90
        resume = [tt("suivi.remplir.bandeau_lignes", len(ls))] + ([org.nom] if org else []) + [
            tt("suivi.remplir.bandeau_comparaison", comparaison=comparaison)]
        if seuil is not None:
            resume.append(tt("suivi.remplir.bandeau_ecart", seuil=f"{seuil * 100:.0f}"))
        resume.append(tt("suivi.remplir.bandeau_definitions"))
        entete = X.bandeau(ws, tt("suivi.remplir.titre") + (f" – {cg.nom_complet}" if cg else ""), [
            tt("suivi.remplir.bandeau1"),
            tt("suivi.remplir.bandeau2"),
            " · ".join(resume),
        ], langue)
        lignes_ws = [[d[c.cle] for c in colonnes] for d in map(donnees, ls)]  # chaque ligne préparée une fois
        if vierge:  # fichier vierge : des lignes libres à compléter (clés comprises), sans protection
            lignes_ws = [[None] * len(colonnes) for _ in range(200)]
        # volet figé jusqu'à « Indicateur » : on garde le nom du KPI en allant vers Commentaire ou À vérifier
        fin = X.ecrire_tableau(ws, colonnes, lignes_ws, langue, debut=entete, figer="unite")
        premiere = entete + 1
        precedente = None
        # styles communs à toutes les lignes, créés une fois (chaque appel des fabriques recalculait l'empreinte des
        # bordures : 1,3 million de fois pour 100 000 lignes)
        cadre = X.Border(*(X.Side(style="thin", color=X.JAUNE_BORD),) * 4)
        trait_org = X.Border(top=X.Side(style="medium", color="9E9E9E"))
        police_org = Font(bold=True, color=X.GRIS_ENTETE_TEXTE)
        for i, l in enumerate(ls):
            n = premiere + i
            k = l.kpi
            d = format_nombre_kpi(k)
            for cle in ("n1", "valeur"):
                ws.cell(n, rang[cle] + 1).number_format = d
                if k.est_texte:  # réponse rédigée : retours à la ligne gardés, cellule renvoyée à la ligne
                    ws.cell(n, rang[cle] + 1).alignment = Alignment(wrap_text=True, vertical="top")
            if k.est_texte and l.n1 and l.n1.texte and not l.n1.non_applicable:
                # N-1 rédigé : un extrait (le texte entier dans la colonne étroite rendait la ligne très haute), le
                # texte complet en bulle ; cette colonne ne se réimporte pas, la valeur garde son Markdown
                from .markdown import extrait, texte_lisible

                c_n1 = X.ecrire_cellule(ws, n, rang["n1"] + 1, extrait(l.n1.texte, 60))
                c_n1.alignment = Alignment(wrap_text=True, vertical="top")  # deux lignes au plus, sans déborder à droite
                X.bulle(c_n1, texte_lisible(l.n1.texte), largeur=420, hauteur=220)
            for cle in ("valeur", "na", "commentaire"):  # zone à remplir : un fin cadre, la grille Excel étant masquée
                ws.cell(n, rang[cle] + 1).border = cadre
            if l.organisation != precedente:  # début d'une organisation : repère visuel
                precedente = l.organisation
                c = ws.cell(n, rang["organisation"] + 1)
                c.font = police_org
                for j in range(1, len(colonnes) + 1):
                    ws.cell(n, j).border = trait_org
            V, NA, COM, N1 = (f"{lettre[c]}{n}" for c in ("valeur", "na", "commentaire", "n1"))
            oui_na = f'OR(UPPER({NA})="OUI",UPPER({NA})="YES",UPPER({NA})="SI",UPPER({NA})="SÍ",UPPER({NA})="X")'
            vide = textes["facultatif"] if getattr(l, "facultatif", False) else textes["a_remplir"]
            ws.cell(n, rang["etat"] + 1).value = f'=IF({oui_na},"N/A",IF({V}="","{fx(vide)}","{fx(textes["rempli"])}"))'
            parts = []
            if seuil is not None and k.est_numerique:
                parts.append(f'IF(AND(ISNUMBER({V}),ISNUMBER({N1}),{COM}=""),IF({N1}=0,"",IF(ABS({V}-{N1})/ABS({N1})>{seuil},'
                             f'"{fx(textes["ecart"])}","")),"")')
            # N/A sans commentaire : « Valider » le refuserait (saisie.controles_validation) ; le dire avant l'import
            parts.append(f'IF(AND({oui_na},{COM}=""),"{fx(textes["na_commentaire"])} ","")')
            if k.preuve_obligatoire and not getattr(l, "nb_preuves", 0):  # une preuve déjà jointe dans l'outil suffit
                parts.append(f'IF({oui_na},"","{fx(textes["preuve"])}")')
            ws.cell(n, rang["verifier"] + 1).value = f"=TRIM({'&'.join(parts)})" if parts else None
            defs = definitions.get(k.code)
            if defs:
                X.bulle(ws.cell(n, rang["indicateur"] + 1), "\n\n".join(f"{c} : {t}" for c, t in defs), k.code)
        if any(l.kpi.est_texte for l in ls):  # réponses rédigées : colonnes Valeur et N-1 un peu plus larges
            ws.column_dimensions[lettre["valeur"]].width = LARGEUR_VALEUR_TEXTE
            ws.column_dimensions[lettre["n1"]].width = LARGEUR_VALEUR_TEXTE
        if lignes:
            _validations(ws, ls, premiere, colonnes, rang, lettre, langue)
            if seuil is not None:
                V, N1, COM = (f"${lettre[c]}{premiere}" for c in ("valeur", "n1", "commentaire"))
                regle = FormulaRule(formula=[f"AND(ISNUMBER({V}),ISNUMBER({N1}),{N1}<>0,{COM}=\"\",ABS({V}-{N1})/ABS({N1})>{seuil})"],
                                    fill=PatternFill("solid", fgColor=X.ORANGE_ALERTE), font=Font(bold=True, color=X.ORANGE_TEXTE))
                ws.conditional_formatting.add(f"{lettre['valeur']}{premiere}:{lettre['valeur']}{fin}", regle)
            ws.conditional_formatting.add(
                f"{lettre['verifier']}{premiere}:{lettre['verifier']}{fin}",
                FormulaRule(formula=[f'LEN(${lettre["verifier"]}{premiere})>0'], font=Font(bold=True, color=X.ORANGE_TEXTE)))
            ws.conditional_formatting.add(
                f"{lettre['etat']}{premiere}:{lettre['etat']}{fin}",
                FormulaRule(formula=[f'${lettre["etat"]}{premiere}="{fx(textes["a_remplir"])}"'], font=Font(bold=True, color=X.MAGENTA)))
            X.proteger(ws)
        else:
            for row in ws.iter_rows(min_row=premiere, max_row=fin):
                for c in row:
                    c.protection = X.Protection(locked=False)
    # Définitions : un KPI par ligne, une colonne par catégorie affichée au contributeur
    wd = wb.create_sheet(tt("suivi.remplir.onglet_definitions"))
    wd.sheet_view.showGridLines = False
    cols_def = ([X.Colonne("kpi", "suivi.remplir.colonne.kpi", 11, "cle"), X.Colonne("indicateur", "suivi.remplir.colonne.indicateur", 44, retour=True),
                 X.Colonne("unite", "suivi.remplir.colonne.unite", 11)]
                + [X.Colonne(f"cat_{c.code}", "", 50, retour=True, texte=c.tr("libelle", langue)) for c in categories]
                + [X.Colonne("preuve", "suivi.remplir.colonne.preuve_obligatoire", 12)])
    vus, lignes_def = set(), []
    for l in lignes:
        k = l.kpi
        if k.code in vus:
            continue
        vus.add(k.code)
        par_cat = dict(definitions.get(k.code, []))
        lignes_def.append([k.code, nom_kpi(k, langue), k.symbole] + [par_cat.get(c.tr("libelle", langue), "") for c in categories]
                          + [oui_langue if k.preuve_obligatoire else ""])
    debut_def = X.bandeau(wd, tt("suivi.remplir.definitions_titre"), [tt("suivi.remplir.definitions_aide")], langue,
                          roles=False)  # onglet à lire : rien ne s'y remplit, pas de légende des rôles
    X.ecrire_tableau(wd, cols_def, lignes_def, langue, debut=debut_def, figer="unite")
    X.proteger(wd)
    X.feuille_a_lire(wb, tt("suivi.remplir.titre"), [
        (tt("suivi.remplir.lire.campagne"), ", ".join(c.nom_complet for c in campagnes) if multiple else campagne.nom_complet if campagne
         else tt("suivi.remplir.lire.campagne_a_indiquer")),
        (tt("suivi.remplir.lire.genere_le"), DC.date_heure_courte(timezone.localtime()) + f" · {utilisateur}"),
        (tt("suivi.remplir.lire.lignes"), tt("suivi.remplir.lire.cases_a_remplir", len(lignes))),
    ] + a_lire(langue, redige=any(l.kpi.est_texte for l in lignes)), langue)
    wb.active = 1 if len(wb.sheetnames) > 1 else 0
    return X.reponse_excel(wb, nom)


def nombre_affiche(v, decimales):
    from .templatetags.collecte import nombre

    return nombre(v, decimales)


def format_nombre_kpi(k):
    return X.format_nombre_du_kpi(k) if k.est_numerique else "@"


def _validations(ws, lignes, premiere, colonnes, rang, lettre, langue):
    """Contrôles de saisie d'Excel : N/A (Oui / Non) ; valeur numérique (avec son unité dans l'aide), pourcentage de 0 à
    100, liste des réponses d'un oui / non ou d'une liste, texte rédigé. Une aide s'affiche quand la cellule est choisie,
    et une alerte quand la valeur tapée ne convient pas (les alertes ne s'affichaient jamais).
    Alerte « avertissement » et non « arrêt » : la personne peut garder sa valeur (un pourcentage au-delà de 100 existe),
    l'outil la contrôle de toute façon au dépôt du fichier."""
    fin = premiere + len(lignes) - 1
    titre = X.t(langue, "suivi.remplir.validation.titre")

    def regle(**kw):
        aide = kw.pop("aide", None)
        dv = DataValidation(allow_blank=True, showErrorMessage=True, errorStyle="warning", errorTitle=titre, **kw)
        if aide:
            dv.showInputMessage, dv.promptTitle, dv.prompt = True, titre, aide[:250]
        return dv

    oui_non = '"' + traduire("Oui", langue) + "," + traduire("Non", langue) + '"'
    na = regle(type="list", formula1=oui_non, error=X.t(langue, "suivi.remplir.validation.na"),
               aide=X.t(langue, "suivi.remplir.aide.na"))
    na.add(f"{lettre['na']}{premiere}:{lettre['na']}{fin}")
    ws.add_data_validation(na)
    listes = {}
    for i, l in enumerate(lignes, start=premiere):
        k = l.kpi
        if k.est_numerique:
            cle = ("%",) if k.est_pourcentage else ("nombre", k.symbole or "")
        elif k.est_texte:
            cle = ("texte",)
        else:
            cle = ("liste",) + tuple(t for _, t in k.choix_traduits(langue))
        listes.setdefault(cle, []).append(i)
    for cle, rangs in listes.items():
        if cle[0] == "texte":  # réponse rédigée : texte libre, longueur limitée comme à l'écran
            from .markdown import TEXTE_MAX

            dv = regle(type="textLength", operator="lessThanOrEqual", formula1=str(TEXTE_MAX),
                       error=X.t(langue, "suivi.remplir.validation.texte", max=TEXTE_MAX),
                       aide=X.t(langue, "suivi.remplir.aide.texte", max=TEXTE_MAX))
        elif cle[0] == "%":  # de 0 à 100 (35 pour 35 % ; une cellule mise au format % d'Excel est relue aussi, sur 100)
            dv = regle(type="decimal", operator="between", formula1="0", formula2="100",
                       error=X.t(langue, "suivi.remplir.validation.pourcentage"), aide=X.t(langue, "suivi.remplir.aide.pourcentage"))
        elif cle[0] == "nombre":
            dv = regle(type="decimal", operator="between", formula1="-1E+15", formula2="1E+15",
                       error=X.t(langue, "suivi.remplir.validation.nombre"),
                       aide=X.t(langue, "suivi.remplir.aide.nombre_unite", unite=cle[1]) if cle[1]
                       else X.t(langue, "suivi.remplir.aide.nombre"))
        else:
            dv = regle(type="list", formula1='"' + ",".join(c.replace('"', "'").replace(",", " ") for c in cle[1:]) + '"',
                       error=X.t(langue, "suivi.remplir.validation.liste"), aide=X.t(langue, "suivi.remplir.aide.liste"))
        # plages disjointes (lignes consécutives d'une même colonne) : posées d'un coup, sans que chaque ajout les compare
        # à toutes les précédentes (DataValidation.add : 13 s pour 10 000 plages) ; même contenu
        dv.sqref = MultiCellRange([CellRange(f"{lettre['valeur']}{debut}:{lettre['valeur']}{fin_}") for debut, fin_ in _plages(rangs)])
        ws.add_data_validation(dv)


def _plages(numeros):
    """[3, 4, 5, 9] → [(3, 5), (9, 9)] : lignes consécutives regroupées."""
    plages = []
    for n in numeros:
        if plages and plages[-1][1] == n - 1:
            plages[-1][1] = n
        else:
            plages.append([n, n])
    return plages


def modele_vierge(utilisateur, campagne, format="xlsx", style="fr", langue=None):
    return modele(utilisateur, campagne, [], format, style, langue=langue)


# ---------------------------------------------------------------- fichier demandé par la page (Import / Export › Importer)
TOUS = "tous"  # « Référentiel : tous mes référentiels en cours » du fichier à remplir


def choix_depuis(donnees):
    """Choix de la page enregistrés dans une tâche (``{nom: [valeurs]}``) relus comme ceux d'une requête (get, getlist)."""
    from django.utils.datastructures import MultiValueDict

    return MultiValueDict({k: list(v) for k, v in donnees.items()})


def choix_modele(utilisateur, q):
    """(format, organisation choisie, liste sauvegardée, KPI cochés un à un) des choix ``q`` de la page."""
    from .models import SelectionKPI

    fmt = "csv" if q.get("format") == "csv" else "xlsx"
    org = q.get("org", "")
    choix = q.get("choix_kpi", "liste")  # « Tous mes KPI », « Une liste sauvegardée » ou « Choisir les KPI »
    selection = SelectionKPI.visibles(utilisateur).filter(pk=q.get("selection") or 0).first() \
        if choix == "liste" and str(q.get("selection", "")).isdecimal() else None
    codes = set(q.getlist("kpis")) if choix == "choix" else None
    return fmt, int(org) if org.isdecimal() else None, selection, codes


def estimer_cellules(utilisateur, q, campagne):
    """Cellules du fichier à remplir (cases × colonnes), comptées sur les cases de la personne (``saisie.cellules``,
    sans lire les réponses) : décide s'il se fabrique en arrière-plan. Le fichier vierge : 0."""
    if q.get("vierge") or (campagne is None and q.get("ref") != TOUS):
        return 0
    _, org, selection, codes = choix_modele(utilisateur, q)
    if codes is None and selection is not None:
        codes = set(selection.kpis.values_list("code", flat=True))
    campagnes = campagnes_en_cours_de(utilisateur) if q.get("ref") == TOUS else [campagne]
    cases = sum(1 for c in campagnes for k, o in S.cellules(utilisateur, campagne=c)
                if (org is None or o.id == org) and (not codes or k.code in codes))
    return cases * len(colonnes_a_remplir())


def fichier_a_remplir(utilisateur, q, campagne):
    """Réponse HTTP du fichier à remplir pour les choix ``q`` de la page et la ``campagne`` affichée (ignorée pour
    « tous mes référentiels ») ; None : rien à remplir (tout est validé). Même fonction pour le téléchargement immédiat et
    pour l'arrière-plan (``exports_arriere_plan``). Lève ``exports.ExportTropGros`` au-delà des lignes d'une feuille."""
    from .exports import LIGNES_ENTETE_EXCEL, MAX_LIGNES_EXCEL, ExportTropGros

    fmt, org, selection, codes = choix_modele(utilisateur, q)
    a_faire = q.get("a_faire") == "on"
    if q.get("ref") == TOUS and not q.get("vierge"):  # tous mes référentiels en cours : un onglet chacun
        lignes = lignes_modele_en_cours(utilisateur, org, a_faire, selection, codes)
        campagne, par_organisation = S.campagne_par_defaut(utilisateur), False
    elif q.get("vierge") or campagne is None:
        return modele_vierge(utilisateur, campagne, fmt)
    else:
        lignes = lignes_modele(utilisateur, campagne, org, a_faire, Plan(campagne.referentiel), selection, codes)
        par_organisation = q.get("par_organisation") == "on"
    if not lignes and a_faire:
        return None
    if fmt == "xlsx" and not par_organisation and len(lignes) + LIGNES_ENTETE_EXCEL > MAX_LIGNES_EXCEL:
        from .templatetags.collecte import entier
        from parametres.libelles import libelle

        raise ExportTropGros(libelle("suivi.export.erreur.trop_de_lignes", max=entier(MAX_LIGNES_EXCEL)))
    return modele(utilisateur, campagne, lignes, fmt, par_organisation=par_organisation)
