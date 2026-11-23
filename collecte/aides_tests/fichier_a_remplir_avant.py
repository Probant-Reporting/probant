"""Construction du fichier à remplir d'avant l'optimisation à gros volume, gardée telle quelle pour les tests d'équivalence :
``_modele``, ``_validations`` (plages ajoutées une à une) et ``ecrire_tableau`` (styles posés cellule par cellule).
Ne pas modifier : copie de ``collecte/imports_modele.py`` et ``collecte/fichiers.py`` au commit 539519f (seuls les imports
relatifs sont écrits en entier).
``ancien_modele`` produit le fichier comme avant, pour le comparer cellule par cellule au fichier d'aujourd'hui."""
from unittest import mock

from django.utils import timezone
from openpyxl.formatting.rule import FormulaRule
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from collecte import dates_courtes as DC
from collecte import fichiers as X
from collecte import saisie as S
from collecte.exports import langue_export, nom_kpi, traduire, valeur_fichier
from collecte.fichiers import date_locale, ecrire_cellule, legende, mise_en_page, style_cellule, style_entete
from collecte.imports_modele import (LARGEUR_VALEUR_TEXTE, _definitions, _nom_onglet, _plages, a_lire, colonnes_a_remplir,
                                     format_nombre_kpi)
from collecte.models import Reponse
from collecte.styles_excel import Alignment, Font, PatternFill
from referentiel.plans import Plan


def ancien_modele(utilisateur, campagne, lignes, format="xlsx", style="fr", par_organisation=False, langue=None):
    """``imports_modele.modele`` avec la construction d'avant."""
    from parametres import langues as L

    langue = langue or langue_export("")
    with L.activer(langue), mock.patch.object(X, "ecrire_tableau", ecrire_tableau):
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

    def donnees(l):
        k, r, c = l.kpi, l.reponse, camp(l)
        place = plan_de(l).decrire(k.code)
        na = oui_langue if r and r.non_applicable else ""
        valeur = valeur_fichier(r, k)
        d = {"organisation": l.organisation.nom, "kpi": k.code, "indicateur": nom_kpi(k, langue), "unite": k.symbole,
             "n1": "N/A" if l.n1 and l.n1.non_applicable else valeur_fichier(l.n1, k), "valeur": valeur, "na": na,
             "commentaire": r.commentaire if r else "", "theme": " › ".join(t for t in (place["theme"], place["sous_theme"]) if t),
             "periode": str(c.periode) if c else "", "exercice": c.exercice if c else None,
             "statut": traduire(Reponse.Statut(l.statut).label, langue) if l.statut else "",
             "referentiel": place["referentiel"], "code_org": l.organisation.code}
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
                from collecte.markdown import extrait, texte_lisible

                c_n1 = X.ecrire_cellule(ws, n, rang["n1"] + 1, extrait(l.n1.texte, 60))
                c_n1.alignment = Alignment(wrap_text=True, vertical="top")  # deux lignes au plus, sans déborder à droite
                X.bulle(c_n1, texte_lisible(l.n1.texte), largeur=420, hauteur=220)
            for cle in ("valeur", "na", "commentaire"):  # zone à remplir : un fin cadre, la grille Excel étant masquée
                ws.cell(n, rang[cle] + 1).border = X.Border(*(X.Side(style="thin", color=X.JAUNE_BORD),) * 4)
            if l.organisation != precedente:  # début d'une organisation : repère visuel
                precedente = l.organisation
                c = ws.cell(n, rang["organisation"] + 1)
                c.font = Font(bold=True, color=X.GRIS_ENTETE_TEXTE)
                for j in range(1, len(colonnes) + 1):
                    ws.cell(n, j).border = X.Border(top=X.Side(style="medium", color="9E9E9E"))
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
            from collecte.markdown import TEXTE_MAX

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
        for debut, fin_ in _plages(rangs):
            dv.add(f"{lettre['valeur']}{debut}:{lettre['valeur']}{fin_}")
        ws.add_data_validation(dv)


def ecrire_tableau(ws, colonnes, lignes, langue="fr", debut=1, figer=None, filtre=True):
    """En-têtes (ligne ``debut``) puis lignes de données, aux couleurs du rôle de chaque colonne ; largeurs, filtre,
    volet figé (``figer`` : clé de la première colonne qui défile, None : aucune colonne figée).
    ``lignes`` : listes de valeurs dans l'ordre des colonnes. Renvoie la dernière ligne écrite."""
    for j, c in enumerate(colonnes, start=1):
        cell = ecrire_cellule(ws, debut, j, c.titre(langue))  # titres d'organisation (tableau) : du texte
        style_entete(cell, c.role)
        ws.column_dimensions[get_column_letter(j)].width = c.largeur
    ws.row_dimensions[debut].height = 32
    n = debut
    for valeurs in lignes:
        n += 1
        for j, (c, v) in enumerate(zip(colonnes, valeurs), start=1):
            cell = ecrire_cellule(ws, n, j, date_locale(v))
            style_cellule(cell, c)
    rang = next((j for j, c in enumerate(colonnes, start=1) if c.cle == figer), 1)
    ws.freeze_panes = ws.cell(debut + 1, rang)
    if filtre:
        ws.auto_filter.ref = f"A{debut}:{get_column_letter(len(colonnes))}{max(n, debut + 1)}"
    if getattr(ws, "_ligne_legende", None):
        ligne, langue_, exemples = ws._ligne_legende
        legende(ws, ligne, 1, langue_, exemples=exemples)
        ws._ligne_legende = None
    mise_en_page(ws, debut)
    return n
