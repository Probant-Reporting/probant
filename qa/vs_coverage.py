"""Rebuilds referentiel/bibliotheque/definitions/vs_base_coverage.csv and vs_complet_coverage.csv from the mapping of the
official format (referentiel/bibliotheque/formats/vs_efrag.py) and the inventory of the workbook's input cells.

    python3 qa/official_template_inputs.py referentiel/bibliotheque/formats/vs_digital_template_2.0.0.xlsx /tmp/inputs
    python3 qa/vs_coverage.py /tmp/inputs.json

Then check with python3 manage.py bibliotheque --validate."""
# Commentaires en français, messages en anglais.
import csv, json, os, sys
sys.path.insert(0, ".")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()
from referentiel.bibliotheque import controle as C
from referentiel.bibliotheque import socles as S
from referentiel.bibliotheque.definitions import DOSSIER, vs_base, vs_complet
from referentiel.bibliotheque.formats import vs_efrag as V
libelles = {(l["onglet"], l["cellule"]): l["en"] for l in json.load(open(sys.argv[1], encoding="utf-8"))}
ABR = {V.GI: "Gen", V.ENV: "Env", V.SOC: "Soc", V.GOV: "Gov", V.LANGUE: "Lang", V.SOMMAIRE: "ToC"}
REFS = {"D154": "B10 · 42(d)", "_pays": "B8 · 40(c)"}  # référence de la norme quand le premier KPI de la cellule sert ailleurs
def arbre(m):
    return {c: (ref, o) for c, _, ref, o in C.elements(m.SOCLE)}
AUTO = {"G7": "Display language of the workbook, chosen at export.", "D3": "Name of the exported organisation.",
        "D5": "EUR: the amounts of the templates are in euros.", "D6": "Start of the exported reporting year.", "D7": "Start of the exported reporting year.",
        "D8": "Start of the exported reporting year.", "D10": "End of the exported reporting year.", "D11": "End of the exported reporting year.",
        "D12": "End of the exported reporting year.", "E125": "Option A, or Option B when the Comprehensive Module template is installed and active.",
        "E281": "Employees counted at the end of the reporting period (SOC-EFFECTIF).", "E282": "Employees counted as a headcount (SOC-EFFECTIF)."}
NOTES = {"G5": "kWh converted to MWh in the tool (NRJ-TOTAL-MWH).", "G12": "kWh converted to MWh.", "J12": "Purchased minus renewable electricity, plus purchased heat, steam and cooling (EFRAG guidance § 24), in MWh.",
         "G13": "kWh converted to MWh.", "G14": "Renewable fuels in MWh (0 when only fossil fuels are reported), written in place of the Fuel Converter link (allowed by EFRAG).",
         "J14": "Fossil fuels in MWh on a net calorific value basis (gas converted from gross with CONV-GAZ-PCI), written in place of the Fuel Converter link (allowed by EFRAG).",
         "D22": "Scope 1 calculated in the tool plus the other direct emissions entered (process, other fuels).",
         "E279": "M€ multiplied by 1,000,000 (report currency: EUR).", "J416": "Total in tonnes written in place of the calculation from the waste-code table.",
         "J417": "Total minus hazardous, written in place of the calculation from the waste-code table.",
         "J422": "Recycled ÷ total waste, written in place of the calculation from the waste-code table.",
         "J423": "Prepared for reuse ÷ total waste (from the waste-code table when filled in), written in place of the workbook's formula 1 − J422, which is wrong.",
         "D136": "Rate per 500 full-time workers (1,000,000 hours), like the usual frequency rate.",
         "D158": "The workbook takes the headcount at the start (previous year's SOC-EFFECTIF) and at the end (SOC-EFFECTIF) from the Basic Module.",
         "H6": "Written only if greater than 0.", "H7": "Written only if greater than 0.",
         "D301": "Ticked when water is discharged from production processes (0 means no such processes).", "D302": "Written only if greater than 0.",
         "D159": "Previous year's SOC-EFFECTIF; SOC-EFFECTIF-DEBUT in the first year tracked in the tool.",
         "C72": "Unit of the pollutant tables: kilograms.", "G416": "Unit of the waste totals: tonnes, or kilograms when the table by waste code is filled in.",
         "E21": "Ticked when the table of unchanged disclosures has rows.", "G430": "Ticked when the material table has rows.",
         "C531": "Cell locked by mistake in Digital Template 2.0.0; filled all the same.", "C545": "Cell locked by mistake in Digital Template 2.0.0; filled all the same."}
CASES = {"E392", "C508", "G10", "G29", "J19", "G68", "G189", "D301", "E536", "D143", "H5", "H10", "H22", "E526"}
lignes = {"base": [], "complet": []}
for modele, m in (("base", vs_base), ("complet", vs_complet)):
    pl = arbre(m)
    for cel in V.CELLULES:
        dans = cel.module.startswith("B") or cel.module == "Rapport"
        if (modele == "base") != dans:
            continue
        codes = [k for k in cel.codes if k in pl]
        ref = f"{cel.module} · {ABR[cel.onglet]}!{cel.cellule}"
        if cel.codes and codes:
            r0 = pl[codes[0]][0] or cel.module
            ref = f"{REFS.get(cel.cellule, r0)} ({ABR[cel.onglet]}!{cel.cellule})"
        datapoint = libelles.get((cel.onglet, cel.cellule)) or (S.KPIS[codes[0]]["en"] if codes else cel.cellule)
        datapoint = " ".join(str(datapoint).split())[:160]
        if not cel.codes:
            lignes[modele].append({"reference": ref, "requirement": "mandatory", "datapoint": datapoint, "status": "automatic", "kpi_codes": "",
                                   "note": AUTO.get(cel.cellule, "Filled by the export.")})
            continue
        if not codes:
            continue
        optionnel = all(not pl[k][1] for k in codes)
        exigence = "voluntary" if optionnel else ("if_applicable" if (not cel.obligatoire or cel.cellule in CASES) else "mandatory")
        if exigence == "mandatory":
            codes = [k for k in codes if pl[k][1]]
        note = NOTES.get(cel.cellule, "Yellow checkbox (not reported in XBRL): ticked when the information exists." if cel.cellule in CASES else "")
        lignes[modele].append({"reference": ref, "requirement": exigence, "datapoint": datapoint, "status": "covered", "kpi_codes": " ".join(codes), "note": note})
    for b in V.BLOCS:
        if (modele == "base") != b.module.startswith("B"):
            continue
        codes = [k for k in b.codes if k in pl]
        ref = f"{REFS.get(b.remplir.__name__) or pl[codes[0]][0] or b.module} ({ABR[b.onglet]}!{b.colonnes[0]}{b.lignes[0]}:{b.colonnes[-1]}{b.lignes[1]})"
        notes = {"_filiales": "Table answer (one row per subsidiary) collected at the top of the tree.",
                 "_omissions": "Table answer (one row per omitted disclosure); each row ticks its 'classified or sensitive information' checkbox in the table of contents.",
                 "_inchangees": "Table answer; written in the display language of the workbook (its list values are translated labels).",
                 "_polluants": "Table answer collected per site (one row per pollutant, kg); rows of the same pollutant added up.",
                 "_autres_polluants": "Table answer collected per site (pollutants outside the EU list, kg).",
                 "_dechets": "Optional table answer per site (one row per European waste code); written in kg so that the workbook's totals are right (its formula reads the unit in G438).",
                 "_matieres": "Table answer (one row per key material, quantity and unit).",
                 "_cibles_scope3": "Table answer (one row per scope 3 category: base year and target values).",
                 "_nace": "Codes typed in the tool (one per line) matched to EFRAG's NACE list.",
                 "_sites": "One row per site (lowest level of the tree, open during the year), from the site's answers.",
                 "_biodiversite": "Sites answering 'in' or 'near' a sensitive area, with their ID from the list of sites.",
                 "_pays": "Sum of the sites' headcount per country of the site; filled when there is more than one country."}
        exig_bloc = "voluntary" if all(not pl[k][1] for k in codes) else ("if_applicable" if b.module in ("B4", "B5", "B7", "B8") or b.remplir.__name__ in ("_filiales", "_omissions") else "mandatory")
        if exig_bloc == "mandatory":  # les KPI facultatifs d'une ligne obligatoire (coordonnées GPS) ne sont pas cités
            codes = [k for k in codes if pl[k][1]]
        lignes[modele].append({"reference": ref, "requirement": exig_bloc,
                               "datapoint": {"_filiales": "List of subsidiaries with registered address (consolidated basis)",
                                             "_omissions": "Disclosures omitted as classified or sensitive information",
                                             "_inchangees": "Disclosures unchanged from the previous report",
                                             "_polluants": "Emissions of each pollutant of the EU list to air, water and soil",
                                             "_autres_polluants": "Emissions of other pollutants to air, water and soil",
                                             "_dechets": "Waste generated by European waste code, with shares diverted to recycling and reuse",
                                             "_matieres": "Annual mass-flow of relevant materials used",
                                             "_cibles_scope3": "Scope 3 base year and target values by category",
                                             "_nace": "NACE sector classification code(s)", "_sites": "List of sites (address, postal code, city, country)",
                                             "_biodiversite": "Sites in or near biodiversity sensitive areas", "_pays": "Employees by country of employment contract"}[b.remplir.__name__],
                               "status": "covered", "kpi_codes": " ".join(codes), "note": notes[b.remplir.__name__]})
EXTRA = {"base": [
    ("B9 · 41(a) (Soc!D134)", "mandatory", "Hours worked by one full-time employee", "automatic", "", "The workbook's default of 2,000 hours is kept; the company can change it in the workbook."),
], "complet": []}
for modele, extra in EXTRA.items():
    for ref, req, dp, st, codes, note in extra:
        lignes[modele].append({"reference": ref, "requirement": req, "datapoint": dp, "status": st, "kpi_codes": codes, "note": note})
for modele, liste in lignes.items():
    with open(DOSSIER / f"vs_{modele}_coverage.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=C.COLONNES_COUVERTURE, lineterminator="\n")
        w.writeheader()
        w.writerows(liste)
    print(modele, len(liste))
