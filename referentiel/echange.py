"""Import et export du référentiel (KPI et organisations) au format Excel."""
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError
from django.db import transaction
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill

from parametres import langues as L

from . import formule as F
from .models import KPI, Description, KPIFormule, Niveau, Organisation, OrgAlias, verifier_formule
from espaces import contexte as ESP

# Format technique historique (fichiers de référentiel d'avant la mise à jour) : une colonne par ancien champ du KPI
CHAMPS_KPI = [
    "code", "id_efrag", "theme", "sous_theme", "type_saisie", "nom_fr", "nom_en", "description", "a_inclure",
    "a_exclure", "formule", "formule_texte", "unite", "type_reponse", "granularite", "methode_agregation",
    "equipe_responsable", "source_donnees", "csrd_2026", "audit_2025", "audit_2026", "nouveau", "preuve_obligatoire",
    "confidentialite", "ordre", "actif", "origine", "a_verifier",
]
# en-tête écrit dans le fichier, quand il diffère du nom du champ ; en-têtes encore lus (normalisés en minuscules)
ENTETES = {"code": "Code KPI"}
# en-têtes d'anciens fichiers de référentiel encore lus (fichiers d'avant la mise à jour)
ALIAS_ENTETES = {"code kpi": "code", "code": "code", "id kpi": "code"}
BOOLEENS = {"nouveau", "preuve_obligatoire", "actif"}
# types de réponse du format historique, créés seulement quand un fichier les utilise : « GHG » (émissions de gaz à effet de
# serre, un nombre) sert à d'anciens référentiels ; une installation neuve ne le propose pas
TYPES_REPONSE_HISTORIQUES = {"GHG": ("GHG", "nombre")}
TYPES = {"Saisi": "Saisi", "Calculé": "Calculé", "Facteur d'émission": "FE", "FE": "FE"}
NOMS = {"nom_fr": "fr", "nom_en": "en"}  # colonne → langue du nom
SIMPLES = ["formule", "methode_agregation", "equipe_responsable", "preuve_obligatoire",
           "confidentialite", "ordre", "actif"]
DESCRIPTIONS = {"description": "description", "a_inclure": "a_inclure", "a_exclure": "a_exclure", "source_donnees": "source"}
CHAMPS_HISTORIQUES = [  # colonne = code du champ personnalisé, libellé, type, valeurs possibles
    ("id_efrag", "ID EFRAG", "texte", []),
    ("csrd_2026", "CSRD 2026", "liste", ["Oui", "Non", "Sous-jacent"]),
    ("audit_2025", "Audit 2025", "liste", ["Oui", "Non", "Sous-jacent"]),
    ("audit_2026", "Audit 2026", "liste", ["Oui", "Non", "Sous-jacent"]),
    ("nouveau", "Nouveau", "case", []),
    ("origine", "Origine", "texte", []),
    ("a_verifier", "À vérifier", "texte", []),
    ("formule_texte", "Formule (texte d'origine)", "texte", []),
]

CHAMPS_HISTORIQUES_TRAD = {  # libellés de départ en anglais et en espagnol (contenus en trois langues)
    "en": {"id_efrag": "ID EFRAG", "csrd_2026": "CSRD 2026", "audit_2025": "Audit 2025", "audit_2026": "Audit 2026",
           "nouveau": "New", "origine": "Origin", "a_verifier": "To check", "formule_texte": "Formula (original text)"},
    "es": {"id_efrag": "ID EFRAG", "csrd_2026": "CSRD 2026", "audit_2025": "Auditoría 2025", "audit_2026": "Auditoría 2026",
           "nouveau": "Nuevo", "origine": "Origen", "a_verifier": "A verificar",
           "formule_texte": "Fórmula (texto original)"},
}
VALEURS_HISTORIQUES_TRAD = {"en": ["Yes", "No", "Underlying"], "es": ["Sí", "No", "Subyacente"]}  # Oui, Non, Sous-jacent


def ouvrir_classeur(chemin):
    """Classeur des commandes d'import (KPI, organisations, valeurs), contrôlé comme un fichier déposé : un classeur
    piégé est refusé avant d'être ouvert (collecte.fichiers.controler_classeur)."""
    from collecte.fichiers import controler_classeur

    controler_classeur(chemin)
    return load_workbook(chemin, read_only=True, data_only=True)


def preparer_format_historique():
    """Catégories de description et champs personnalisés que ce format remplit (créés s'ils manquent)."""
    from parametres import referentiel as PR
    from parametres.models import ChampPersonnalise

    PR.creer_par_defaut()
    for i, (code, libelle, type_, valeurs) in enumerate(CHAMPS_HISTORIQUES, start=1):
        traductions = {lg: {"libelle": t[code]} for lg, t in CHAMPS_HISTORIQUES_TRAD.items() if code in t}
        for lg, vals in VALEURS_HISTORIQUES_TRAD.items():
            if valeurs:
                traductions.setdefault(lg, {})["valeurs"] = vals
        ChampPersonnalise.objects.get_or_create(code=code, defaults=dict(libelle=libelle, type=type_, valeurs=valeurs, ordre=i,
                                                                          traductions=traductions))


@dataclass
class Rapport:
    crees: int = 0
    modifies: int = 0
    inchanges: int = 0
    erreurs: list = field(default_factory=list)  # (ligne, id, message)
    avertissements: list = field(default_factory=list)

    def __str__(self):
        lignes = [f"Created: {self.crees}; modified: {self.modifies}; unchanged: {self.inchanges}; errors: {len(self.erreurs)}"]
        lignes += [f"  line {l} [{i}]: {m}" for l, i, m in self.erreurs[:50]]
        lignes += [f"  warning [{i}]: {m}" for i, m in self.avertissements[:50]]
        return "\n".join(lignes)


def texte_cellule(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def entete(champ):
    """En-tête d'une colonne du format historique : « Code KPI » pour le code, sinon le nom du champ."""
    return ENTETES.get(champ, champ)


def colonne_langue(h):
    """Colonnes facultatives par langue : nom, définitions et thèmes traduits.

    (base, langue) d'une colonne par langue (« description_en » → (« description », « en »)), sinon None.
    « nom_fr » et « nom_en » restent les colonnes du format historique."""
    import re

    m = re.fullmatch(r"(nom|description|a_inclure|a_exclure|source_donnees|theme|sous_theme)_([a-z]{2}(?:[-_][a-z]{2})?)", h or "")
    if not m or h in NOMS:
        return None
    return m.group(1), m.group(2).replace("_", "-")


def lire_kpi_excel(chemin, onglet="KPI"):
    """Lignes du format historique : (numéro, {champ : texte}). Le code se lit sous « Code KPI » ou sous un ancien en-tête
    générique (ALIAS_ENTETES). Les colonnes par langue (``colonne_langue``) sont lues aussi."""
    wb = ouvrir_classeur(chemin)
    ws = wb[onglet]
    lignes = ws.iter_rows(values_only=True)
    entetes = [ALIAS_ENTETES.get(texte_cellule(h).lower(), texte_cellule(h)) for h in next(lignes)]
    manquants = set(CHAMPS_KPI) - set(entetes) - {"formule_texte", "origine", "a_verifier", "id_efrag"}
    if manquants:
        raise ValueError(f"Missing columns in the sheet {onglet}: {', '.join(sorted(map(entete, manquants)))}")
    for n, row in enumerate(lignes, start=2):
        d = {h: texte_cellule(v) for h, v in zip(entetes, row) if h in CHAMPS_KPI or colonne_langue(h)}
        if d.get("code"):
            yield n, d


def creer_types_historiques(codes):
    """Types de réponse du format historique utilisés par un fichier et absents de l'installation (« GHG »), créés à la
    demande, à la suite des autres ; une installation neuve ne les a pas."""
    from django.db.models import Max

    from parametres.models import TypeReponse

    for code in sorted(set(codes) & set(TYPES_REPONSE_HISTORIQUES)):
        if not TypeReponse.objects.filter(code=code).exists():
            libelle, fmt = TYPES_REPONSE_HISTORIQUES[code]
            ordre = (TypeReponse.objects.aggregate(m=Max("ordre"))["m"] or 0) + 1
            TypeReponse.objects.create(code=code, libelle=libelle, format=fmt, ordre=ordre)


def _valeur(c, x):
    if c in BOOLEENS:
        return x.lower() in ("oui", "yes", "true", "1", "vrai")
    if c == "ordre":
        return int(float(x)) if x else 0
    if c in ("csrd_2026", "audit_2025", "audit_2026"):
        return {"Yes": "Oui", "No": "Non", "": "Non"}.get(x, x)
    return x


def _traductions(d):
    """{langue: {base: texte}} des colonnes par langue d'une ligne, hors langue de référence (elle se lit dans les
    colonnes historiques « nom_fr », « description », « theme »…). Une langue pas encore active est gardée aussi : il
    suffira de l'activer (Paramètres › Langues) pour que ses textes s'affichent."""
    reference = L.reference()
    sortie = {}
    for h, v in d.items():
        cl = colonne_langue(h)
        if cl and cl[1] != reference:
            sortie.setdefault(cl[1], {})[cl[0]] = v
    return sortie


def _descriptions_langue(kpi, langue):
    return {x.categorie_id: x.texte for x in kpi.descriptions.all() if x.langue == langue}


def _etat(kpi, descriptions, place=None, autres=None):
    return ([autres] if autres else []) + ([getattr(kpi, c) for c in SIMPLES] + [place] + [L.texte(kpi, "libelle", l) for l in NOMS.values()] + [kpi.type_saisie_id, kpi.type_reponse_id, kpi.unite_id, kpi.granularite_id,
                                                   sorted(kpi.champs.items()), sorted(descriptions.items())])


@ESP.atomic
def importer_kpi(chemin, simulation=False):
    """Crée ou met à jour les KPI depuis l'Excel au format historique. En simulation, rien n'est enregistré.

    Unités créées à la volée ; description, à inclure, à exclure et source dans les catégories de description ;
    ID EFRAG, CSRD, audits, nouveau, origine, à vérifier et formule d'origine en champs personnalisés."""
    from collecte import reglages as R
    from parametres import referentiel as PR
    from parametres.models import TypeReponse, TypeSaisie

    preparer_format_historique()
    rapport = Rapport()
    lignes = list(lire_kpi_excel(chemin))
    creer_types_historiques({d["type_reponse"] for _, d in lignes if d.get("type_reponse")})
    ids_fichier = Counter(d["code"] for _, d in lignes)
    for i, nb in ids_fichier.items():
        if nb > 1:
            rapport.erreurs.append(("-", i, f"KPI code present {nb} times in the file"))
    tous_ids = set(KPI.objects.values_list("code", flat=True)) | set(ids_fichier)
    # format de chaque KPI après l'import (celui du fichier, sinon celui de la base), et formules qui le citent après
    # l'import : un KPI cité dans une formule ne devient pas oui / non ou liste, une formule ne cite pas un tel KPI
    formats = dict(TypeReponse.objects.values_list("code", "format"))
    calcul = {c for c, comportement in TypeSaisie.objects.values_list("code", "comportement") if comportement == "calcul"}
    format_base = {k.code: k.format for k in KPI.objects.all()}
    format_apres = dict(format_base)
    nouvelles = {}
    for _, d in lignes:
        if "type_reponse" in d:
            format_apres[d["code"]] = formats.get(d["type_reponse"])
        nouvelles[d["code"]] = d.get("formule", "") if TYPES.get(d.get("type_saisie"), d.get("type_saisie")) in calcul else ""
    cites = R.citations(nouvelles)
    numerique = (None, *R.FORMATS_NUMERIQUES)
    cites_devenus_texte = {kid for kid in ids_fichier if kid in format_base and format_base[kid] in numerique
                           and format_apres.get(kid) not in numerique and cites.get(kid)}
    non_numeriques = {k for k, f in format_apres.items() if f not in numerique} - cites_devenus_texte
    # graphe des dépendances tel qu'il sera après import, pour détecter les boucles
    graphe = defaultdict(set)
    for _, d in lignes:
        if TYPES.get(d.get("type_saisie")) == "Calculé" and d.get("formule"):
            graphe[d["code"]] = F.codes_cites(d["formule"], "N")
    existants = {k.code: k for k in KPI.objects.prefetch_related("descriptions")}
    # thème et sous-thème : place des KPI dans le référentiel par défaut (créé s'il n'y en a aucun)
    from .composition import chemin_noms, placer, referentiel_par_defaut, theme_par_chemin

    from .models import Referentiel

    ref = referentiel_par_defaut() if not simulation else Referentiel.objects.filter(actif=True).first()
    places = {e.kpi_id: (chemin_noms(e), e.ordre) for e in ref.elements.select_related("theme__parent__parent")} if ref else {}
    unites = {}
    a_enregistrer = []
    for n, d in lignes:
        kid = d["code"]
        kpi = existants.get(kid) or KPI(code=kid)
        anciennes = {x.categorie_id: x.texte for x in kpi.descriptions.all() if x.langue == L.reference()} if kid in existants else {}
        trad = _traductions(d)
        # définitions dans les autres langues : avant / après (une cellule vide ne retire rien)
        autres_avant = {lg: _descriptions_langue(kpi, lg) for lg in trad} if kid in existants else {}
        avant = _etat(kpi, anciennes, places.get(kid), autres_avant) if kid in existants else None
        place = ([x for x in (d.get("theme"), d.get("sous_theme")) if x], _valeur("ordre", d["ordre"]) if d.get("ordre") else kpi.ordre) \
            if ("theme" in d or "sous_theme" in d) else places.get(kid)
        for c in SIMPLES:
            if c in d:
                setattr(kpi, c, _valeur(c, d[c]))
        for colonne, langue in NOMS.items():
            if colonne in d:
                L.definir(kpi, "libelle", langue, d[colonne])
        autres = {}
        for langue, textes in trad.items():
            if textes.get("nom"):
                L.definir(kpi, "libelle", langue, textes["nom"])
            autres[langue] = dict(autres_avant.get(langue, {}))
            autres[langue].update({DESCRIPTIONS_PAR_BASE[b]: t for b, t in textes.items() if b in DESCRIPTIONS_PAR_BASE and t})
        type_avant = kpi.type_reponse if kid in existants else None
        unite_avant = kpi.unite_id if kid in existants else None
        if "type_saisie" in d:
            kpi.type_saisie_id = TYPES.get(d["type_saisie"], d["type_saisie"])
        if "type_reponse" in d:
            kpi.type_reponse_id = d["type_reponse"]
        if "granularite" in d:
            kpi.granularite_id = d["granularite"]
        if "unite" in d:
            u = d["unite"][:60]
            if u and u not in unites:
                unites[u] = PR.unite_depuis_symbole(u)
            kpi.unite = unites.get(u) if u else None
        champs = dict(kpi.champs)
        for code, _, type_, _ in CHAMPS_HISTORIQUES:
            if code in d:
                v = _valeur(code, d[code])
                if v:
                    champs[code] = True if type_ == "case" else v
                else:
                    champs.pop(code, None)
        kpi.champs = champs
        descriptions = dict(anciennes)
        for colonne, categorie in DESCRIPTIONS.items():
            if colonne in d:
                if d[colonne]:
                    descriptions[categorie] = d[colonne]
                else:
                    descriptions.pop(categorie, None)
        kpi._na_compte_zero_coherent()  # nouveau KPI calculé : une source N/A compte comme 0 dans une somme
        kpi._decimales_coherentes()  # unité « nombre entier » : 0 décimale
        try:
            kpi.clean_fields()
            regles = kpi.erreurs_regles()
            if regles:
                raise ValidationError(list(regles.values()))
            if kid in existants:  # mêmes contrôles que la fiche KPI : format et unité figés par les réponses, format par les formules
                motifs = [R.motif_format_fige(kid, type_avant, kpi.type_reponse),
                          R.motif_unite_figee(kid, unite_avant, kpi.unite)]  # unité figée par les réponses
                if kid in cites_devenus_texte:
                    motifs.append(R.motif_cite_en_formule(format_apres[kid], cites[kid]))
                if any(motifs):
                    raise ValidationError([m for m in motifs if m])
            if kpi.est_calcule and kpi.formule:
                verifier_formule(kid, kpi.formule, kpis_existants=tous_ids, graphe=graphe, non_numeriques=non_numeriques)
        except ValidationError as e:
            rapport.erreurs.append((n, kid, " ; ".join(e.messages)))
            continue
        if kid not in existants:
            rapport.crees += 1
        elif _etat(kpi, descriptions, place, autres) != avant or _themes_a_traduire(trad, place, ref):
            rapport.modifies += 1
        else:
            rapport.inchanges += 1
            continue
        a_enregistrer.append((kpi, descriptions, place, autres, trad))
    if rapport.erreurs or simulation:
        transaction.set_rollback(True, using=ESP.alias_courant())
        return rapport
    cache = {}
    for kpi, descriptions, place, autres, trad in a_enregistrer:
        super(KPI, kpi).save()  # sans reconstruire les dépendances une par une
        enregistrer_descriptions(kpi, descriptions)
        for langue, textes in autres.items():
            if textes:
                enregistrer_descriptions(kpi, textes, langue)
        if place is not None:
            theme = theme_par_chemin(ref, place[0], cache)
            placer(kpi, ref, theme, place[1])
            traduire_themes(theme, trad)
    reconstruire_toutes_dependances()
    return rapport


DESCRIPTIONS_PAR_BASE = {"description": "description", "a_inclure": "a_inclure", "a_exclure": "a_exclure",
                         "source_donnees": "source"}


def _chaine_themes(theme):
    """[thème du sommet, …, thème du KPI]."""
    chaine = []
    while theme is not None:
        chaine.insert(0, theme)
        theme = theme.parent
    return chaine


def _themes_cibles(chaine, base):
    """Thème que traduit une colonne : « theme_xx » le sommet, « sous_theme_xx » le thème du KPI (s'il est en dessous)."""
    if base == "theme":
        return chaine[0] if chaine else None
    return chaine[-1] if len(chaine) > 1 else None


def _themes_a_traduire(trad, place, ref):
    """Vrai si une colonne « theme_xx » / « sous_theme_xx » change la traduction d'un thème existant."""
    if not trad or not place or ref is None:
        return False
    from .models import Theme

    parent, chaine = None, []
    for nom in [n for n in place[0] if n]:
        t = Theme.objects.filter(referentiel=ref, parent=parent, nom=nom).first()
        if t is None:
            return True
        chaine.append(t)
        parent = t
    for langue, textes in trad.items():
        for base in ("theme", "sous_theme"):
            t = _themes_cibles(chaine, base)
            if t is not None and textes.get(base) and L.texte(t, "nom", langue) != textes[base]:
                return True
    return False


def traduire_themes(theme, trad):
    """Traductions des thèmes depuis les colonnes « theme_xx » et « sous_theme_xx » d'une ligne."""
    chaine = _chaine_themes(theme)
    for langue, textes in trad.items():
        for base in ("theme", "sous_theme"):
            t = _themes_cibles(chaine, base)
            if t is not None and textes.get(base) and L.texte(t, "nom", langue) != textes[base]:
                L.definir(t, "nom", langue, textes[base])
                t.save(update_fields=["traductions"])


def enregistrer_descriptions(kpi, textes, langue=None):
    """{code de catégorie: texte} dans une langue (celle de référence par défaut) : crée, modifie ou retire les
    descriptions du KPI (texte vide = retirée)."""
    langue = langue or L.reference()
    actuelles = {x.categorie_id: x for x in Description.objects.filter(kpi=kpi, langue=langue)}
    for categorie, texte in textes.items():
        texte = (texte or "").strip()
        x = actuelles.get(categorie)
        if not texte:
            if x:
                x.delete()
        elif x is None:
            Description.objects.create(kpi=kpi, categorie_id=categorie, langue=langue, texte=texte)
        elif x.texte != texte:
            x.texte = texte
            x.save(update_fields=["texte"])


def reconstruire_toutes_dependances():
    KPIFormule.objects.all().delete()
    liens = []
    for kpi in KPI.objects.filter(type_saisie__comportement="calcul").exclude(formule=""):
        for r in F.references(kpi.formule):
            liens.append(KPIFormule(kpi_calcule_id=kpi.code, kpi_source_id=r.kpi, decalage=r.decalage))
    KPIFormule.objects.bulk_create(liens, batch_size=1000)
    return len(liens)


def exporter_kpi(chemin):
    """Référentiel au format technique historique (réimportable par import_kpi)."""
    wb = Workbook()
    ws = wb.active
    ws.title = "KPI"
    # colonnes par langue (langues actives hors référence) : nom (sauf « nom_en », colonne historique), définitions, thèmes
    langues = L.langues_a_traduire()
    par_langue = [(f"{b}_{lg}", b, lg) for lg in langues for b in ("nom", *DESCRIPTIONS_PAR_BASE, "theme", "sous_theme")
                  if f"{b}_{lg}" not in NOMS]
    ws.append([entete(c) for c in CHAMPS_KPI] + [c for c, _, _ in par_langue])
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F3864")
    from .composition import chemin_noms, referentiel_par_defaut

    ref = referentiel_par_defaut()
    elements = {e.kpi_id: e for e in ref.elements.select_related("theme__parent__parent")}
    for k in KPI.objects.prefetch_related("descriptions"):
        types = {v: c for c, v in TYPES.items() if c != "FE"}
        noms = chemin_noms(elements.get(k.code))
        valeurs = {"code": k.code, "type_saisie": types.get(k.type_saisie_id, k.type_saisie_id), "type_reponse": k.type_reponse_id,
                   "unite": k.unite.symbole if k.unite_id else "", "granularite": k.granularite_id}
        valeurs.update({c: getattr(k, c) for c in SIMPLES})
        valeurs.update({"theme": noms[0] if noms else "", "sous_theme": " › ".join(noms[1:])})
        valeurs.update({colonne: L.texte(k, "libelle", langue) for colonne, langue in NOMS.items()})
        valeurs.update({colonne: k.texte_description(categorie, L.reference(), repli=False) for colonne, categorie in DESCRIPTIONS.items()})
        valeurs.update({code: k.champs.get(code, False if type_ == "case" else "Non" if type_ == "liste" else "")
                        for code, _, type_, _ in CHAMPS_HISTORIQUES})
        chaine = _chaine_themes(elements[k.code].theme) if k.code in elements else []
        for colonne, base, lg in par_langue:
            if base == "nom":
                valeurs[colonne] = L.texte(k, "libelle", lg)
            elif base in DESCRIPTIONS_PAR_BASE:
                valeurs[colonne] = k.texte_description(DESCRIPTIONS_PAR_BASE[base], lg, repli=False)
            else:
                t = _themes_cibles(chaine, base)
                valeurs[colonne] = L.texte(t, "nom", lg) if t is not None else ""
        row = []
        for c in [*CHAMPS_KPI, *(c for c, _, _ in par_langue)]:
            v = valeurs.get(c, "")
            if c in BOOLEENS:
                v = "Oui" if v else "Non"
            row.append(v)
        ws.append(row)
        for cell in ws[ws.max_row]:
            if isinstance(cell.value, str) and cell.value.startswith("="):
                cell.data_type = "s"
    ws.freeze_panes = "B2"
    from collecte.fichiers import signer

    signer(wb).save(chemin)


# ---------------------------------------------------------------- organisations
NIVEAUX = {"Group": Niveau.GROUP, "Country": Niveau.COUNTRY, "Entity": Niveau.ENTITY, "Site": Niveau.SITE}


@ESP.atomic
def importer_organisations(chemin, onglet="Organizational structure"):
    """Import depuis l'onglet « Organizational structure » du fichier de définition des KPI et de structure.

    Ce format historique suppose les 4 niveaux d'origine (codes Group, Country, Entity, Site)."""
    from parametres.models import NiveauHierarchique

    manquants = set(NIVEAUX.values()) - set(NiveauHierarchique.objects.values_list("code", flat=True))
    if manquants:
        raise ValidationError(f"Missing levels ({', '.join(sorted(manquants))}): this format assumes the 4 original levels.")
    wb = ouvrir_classeur(chemin)
    rows = list(wb[onglet].iter_rows(values_only=True))
    entetes = [texte_cellule(h) for h in rows[0]]
    col = {h: i for i, h in enumerate(entetes)}
    # libellé de l'organisation dans le fichier historique : colonne « Original … label »
    ancien = next((h for h in entetes if h.lower().startswith("original") and h.lower().endswith("label")), None)
    rapport = Rapport()
    par_cle = {}
    for n, row in enumerate(rows[1:], start=2):
        g = lambda h: texte_cellule(row[col[h]]) if h in col and col[h] < len(row) else ""  # noqa: E731
        niveau = NIVEAUX.get(g("Level"))
        if not niveau:
            continue
        cle = {
            Niveau.GROUP: ("G",),
            Niveau.COUNTRY: ("C", g("Country")),
            Niveau.ENTITY: ("E", g("Country"), g("Entity")),
            Niveau.SITE: ("S", g("Country"), g("Entity"), g("Site")),
        }[niveau]
        parent_cle = {Niveau.GROUP: None, Niveau.COUNTRY: ("G",), Niveau.ENTITY: ("C", g("Country")),
                      Niveau.SITE: ("E", g("Country"), g("Entity"))}[niveau]
        nom = g("Unit (display)") or cle[-1]
        parent = par_cle.get(parent_cle) if parent_cle else None
        if parent_cle and parent is None:
            rapport.erreurs.append((n, nom, "Parent not found (must come before the line)"))
            continue
        actif = g("Status").lower() not in ("fermée", "fermee", "closed", "inactive", "inactif")
        org, cree = Organisation.objects.update_or_create(
            nom=nom, defaults=dict(niveau_id=niveau, parent=parent, rang=n, actif=actif, nom_court=cle[-1][:60] if len(cle) > 1 else "Groupe"),
        )
        rapport.crees += cree
        rapport.modifies += not cree
        par_cle[cle] = org
        libelle = g(ancien) if ancien else ""
        if libelle:
            # « source » est une valeur enregistrée en base (clé d'unicité avec le libellé) : on la garde telle quelle
            OrgAlias.objects.get_or_create(source="Ancien outil", libelle=libelle, defaults={"organisation": org})
    if rapport.erreurs:  # tout ou rien : une ligne refusée, rien n'est enregistré
        transaction.set_rollback(True, using=ESP.alias_courant())
        rapport.crees = rapport.modifies = 0
    return rapport
