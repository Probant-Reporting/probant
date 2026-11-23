"""docs/library.md (in English, for installations abroad): built from referentiel/bibliotheque/socles.py by
the English wording of the library, with the English wording of the texts that exist only in French in the sources."""
from . import socles as S
from .catalogue_anglais import T  # noqa: F401 (textes anglais du catalogue, repris par tr)
from .outils import langue as en_langue
from .sources import documents as documents_sources

HEAD = "# Library of provided frameworks\n\nThe library provides ready-made templates: the Voluntary Standard VS, pay transparency, and the eleven ESRS templates of the CSRD (ESRS 2 and ESRS E1 to G1, one per standard, to install according to materiality; ESRS 2 always). A framework of your own is not distributed: you import it. This file is produced by `python manage.py bibliotheque` from `referentiel/bibliotheque/socles.py` and `referentiel/bibliotheque/definitions/` (one file per template; check a template with `python manage.py bibliotheque --validate`), which also produces the templates (JSON files) installed from Administration › Frameworks › Add a framework › Install from the library (where you tick the KPIs you want).\n\n- A KPI shared by several base templates has the same code and the same definition everywhere: installing several base templates reuses it (a single value entered, a single catalogue), without conflict.\n- Entry levels: the templates have none. On installation, the tool attaches each KPI to the organisation tree, whatever its levels: an inherited parameter (emission factor, conversion factor) at the highest level (a single value, carried over below; exception: the emission factor of electricity, which depends on the country, goes to the Country level if it exists, otherwise to the second level of a tree with three or more levels), an input KPI at the lowest level, unless the template advises the top level (one answer for the company) or the entity level (one answer per legal entity, such as the pay transparency report: the Entity or Subsidiary level, otherwise the level just above the lowest in a tree with three or more levels) (its values roll up through aggregation), a calculated KPI at the highest level of its non-inherited sources; a KPI already present in the installation keeps its level. The level can then be changed in the KPI sheet, or for several KPIs at once in the framework's content.\n- KPIs to tick: you can install only part of a template; an unticked formula source is added anyway if a ticked calculated KPI uses it.\n- Source documents: each template lists the documents it is based on (title, publisher, version, date of the document, public address, day it was read, licence). The date is the one the document writes; when it writes no exact date, only the year is given. The tool shows the same list on the card of the template, on the installation screens and on the page of the installed framework.\n- Units, entry and answer types, description categories: reused if they already exist (same code or same label, same behaviour or same format), otherwise created.\n- Annual frequency, comparison with N-1: adjustable after installation (as long as no campaign exists for the frequency).\n- Formulas: `[CODE]` same period, `[CODE@N-1]` same period of the previous reporting year. So that a total remains calculable, enter 0 rather than N/A when a source is absent.\n"

ZERO_FR = " Saisir 0 s'il n'y en a pas (N/A rendrait le total non applicable)."
ZERO_EN = " Enter 0 if there is none (N/A would make the total not applicable)."

TYPES = {"Saisi": "Input", "Calculé": "Calculated", "FE": "Emission factor"}
AGREG = {"Somme": "Sum", "Moyenne": "Average", "Aucune": "None", "Décompte": "Count", "Formule": "Formula"}
TEMPS = {"somme": "sum", "moyenne": "average", "derniere": "last value", "aucune": "none"}
UNIT_EN = {u[0]: u[1] for u in S.UNITES}


def tr(s):
    if not s:
        return s
    if isinstance(s, (tuple, list)):  # nouveaux modèles : (français, anglais)
        return en_langue(s, "en")
    zero = s.endswith(ZERO_FR)
    base = s[: -len(ZERO_FR)] if zero else s
    if base not in T:
        raise KeyError("Missing translation (referentiel/bibliotheque/documentation.py): " + base)
    return T[base] + (ZERO_EN if zero else "")


def nom_regle(nom):
    """Nom anglais d'une règle : 5e élément de la règle (catalogue et modèles)."""
    return S.REGLES[nom][4]


def unite_en(d):
    fmt = S.FORMATS.get(d["reponse"], "nombre")
    if fmt == "pourcentage":
        return "%"
    if fmt == "oui_non":
        return "yes / no"
    if fmt == "texte":
        return "written text"
    if fmt == "tableau":
        colonnes = next(t[3] for t in S.TYPES_REPONSE if t[0] == d["reponse"])
        return "table: " + ", ".join((c.get("libelle") or {}).get("en") or c.get("code") for c in colonnes)
    if fmt == "liste":
        valeurs = next(t[3] for t in S.TYPES_REPONSE if t[0] == d["reponse"])
        return "list: " + ", ".join(valeurs.get("en") or valeurs.get("fr") or [])
    return UNIT_EN.get(d["unite"], d["unite"]) or "—"


def cell(t):
    return str(t or "").replace("|", "\\|").replace("\n", " ")


def themes_of(socle):
    out = {}

    def walk(nodes, parent):
        for n in nodes:
            if S.est_theme(n):
                code, fr, en, contenu = n
                out[code] = {"parent": parent, "en": en}
                walk(contenu, code)
    walk(socle["arbre"], "")
    return out


def kpis_of(socle):
    out = []

    def walk(nodes, parent):
        for n in nodes:
            if S.est_theme(n):
                walk(n[3], n[0])
            else:
                t = (n,) if isinstance(n, str) else tuple(n)
                out.append((t[0], parent, t[2] if len(t) > 2 else True, t[1] if len(t) > 1 else ""))
    walk(socle["arbre"], "")
    return out




def documentation():
    lines = [HEAD.rstrip("\n"), "", "## Base templates", "",
             "| Code | Name | KPIs | of which calculated | Themes | Rules | Version | Date |", "|---|---|---|---|---|---|---|---|"]
    socles_de = {}
    for s in S.SOCLES:
        for code, *_ in kpis_of(s):
            socles_de.setdefault(code, []).append(s["nom"][1])
    for s in S.SOCLES:
        ks = kpis_of(s)
        lines.append(f"| `{s['code']}` | {s['nom'][1]} | {len(ks)} | {sum(1 for c, *_ in ks if S.KPIS[c]['type'] == 'Calculé')} | "
                     f"{len(themes_of(s))} | {len(s['regles'])} | {s.get('version', S.VERSION)} | {s.get('date', '—')} |")
    for s in S.SOCLES:
        th = themes_of(s)

        def path(code):
            t = th.get(code)
            return "" if t is None else (path(t["parent"]) + " › " if t["parent"] else "") + t["en"]
        lines += ["", f"## {s['nom'][1]} (`{s['code']}`)", "", s["description"][1], ""]
        src = s.get("source")
        if src:  # modèle de definitions/ : sa norme d'origine et la référence de chaque KPI dans la norme
            lines += [f"Template version: {s.get('version', S.VERSION)}, dated {s.get('date', '—')}.", "", "Source documents:", "",
                      "| Document | Publisher | Version | Document date | Read on | Licence |", "|---|---|---|---|---|---|"]
            for d in documents_sources(src):
                lines.append(f"| [{cell(d['titre'])}]({d['url']}) | {cell(d['editeur'])} | {cell(d['version'])} | "
                             f"{d['date'] or '—'} | {d['consulte_le']} | {cell(d['licence'])} |")
            lines += ["", "| Theme | Code | KPI | Reference | Mandatory |", "|---|---|---|---|---|"]
        else:
            lines += ["| Theme | Code | KPI | Mandatory |", "|---|---|---|---|"]
        for code, theme, oblig, ref in kpis_of(s):
            lines.append(f"| {cell(path(theme))} | `{code}` | {cell(S.KPIS[code]['en'])} | " + (f"{cell(ref) or '—'} | " if src else "")
                         + f"{'yes' if oblig else 'no'} |")
        if s["regles"]:
            lines += ["", "Consistency rules: " + "; ".join(f"\"{nom_regle(r)}\"" for r in s["regles"]) + "."]
    lines += ["", "## KPI catalogue", "",
              "| Code | Name (fr / en) | Unit | Type | Aggregation (organisations / time) | Formula | Definition | Base templates |",
              "|---|---|---|---|---|---|---|---|"]
    for code, d in S.KPIS.items():
        if code not in socles_de:  # KPI du catalogue commun qu'aucun modèle fourni n'utilise (socles retirés)
            continue
        unite = unite_en(d)
        temps = "—" if d["type"] == "Calculé" else TEMPS[d["temps"] or S.temps_par_defaut(d)]
        definition = " ".join(x for x in (tr(d["description"]), f"Include: {tr(d['a_inclure'])}" if d["a_inclure"] else "",
                                          f"Exclude: {tr(d['a_exclure'])}" if d["a_exclure"] else "",
                                          f"Source: {tr(d['source'])}" if d["source"] else "") if x)
        lines.append(f"| `{code}` | {cell(d['fr'])} / {cell(d['en'])} | {cell(unite)} | {TYPES[d['type']]} | "
                     f"{AGREG[d['agregation']]} / {temps} | {('`' + d['formule'] + '`') if d['formule'] else '—'} | "
                     f"{cell(definition)} | {', '.join(socles_de.get(code, []))} |")
    lines += ["", "## Consistency rules", "", "Checked at the entry level of the left-hand KPI.", "", "| Name | Rule |", "|---|---|"]
    utilisees = {r for s in S.SOCLES for r in s["regles"]}
    for nom, (g, op, dr, *_) in S.REGLES.items():
        if nom not in utilisees:
            continue
        lines.append(f"| {nom_regle(nom)} | `{g} {op} {dr}` |")
    return "\n".join(lines) + "\n"
