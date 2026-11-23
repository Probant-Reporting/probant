"""Input cells of an official EFRAG VS workbook (unlocked, no formula) in its 4 disclosure sheets, with row label (en, fr, es),
paragraph, data validation and Excel name
one row per table (its first one).

    python3 qa/official_template_inputs.py referentiel/bibliotheque/formats/vs_digital_template_2.0.0.xlsx /tmp/inputs

Writes /tmp/inputs.json and /tmp/inputs.csv. Used to inventory a new version of the workbook (see qa/vs_coverage.py)."""
# Commentaires en français, messages en anglais.
import csv, json, re, sys, warnings, zipfile
import openpyxl
from openpyxl.utils import range_boundaries, column_index_from_string
from openpyxl.utils.cell import coordinate_from_string
warnings.filterwarnings("ignore")
src = sys.argv[1]
wb = openpyxl.load_workbook(src)
tr = {r[0]: {"en": r[2], "fr": r[4], "es": r[12]} for r in wb["Translations"].iter_rows(min_row=4, values_only=True) if r[0]}
# plages nommées (hors template_) et noms template_checkbox
plages = []
for nom, d in wb.defined_names.items():
    for f, p in d.destinations:
        p = p.replace("$", "")
        plages.append((nom, f, range_boundaries(p if ":" in p else p + ":" + p)))
def noms_de(f, coord):
    col, row = coordinate_from_string(coord)
    ci = column_index_from_string(col)
    return [(n, b) for n, ff, b in plages if ff == f and b[0] <= ci <= b[2] and b[1] <= row <= b[3]]
z = zipfile.ZipFile(src)
import xml.etree.ElementTree as ET
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
wbx = ET.fromstring(z.read("xl/workbook.xml"))
chemins = {s.get("name"): "xl/" + rels[s.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")].replace("/xl/", "").lstrip("/") for s in wbx.find("m:sheets", NS)}
val14 = {}
for nom, ch in chemins.items():
    x = z.read(ch).decode("utf-8")
    for bloc in re.findall(r"<x14:dataValidation\b.*?</x14:dataValidation>", x, re.S):
        f = re.search(r"<xm:f>(.*?)</xm:f>", bloc, re.S)
        sq = re.search(r"<xm:sqref>(.*?)</xm:sqref>", bloc, re.S)
        typ = re.search(r'type="(\w+)"', bloc)
        for p in (sq.group(1).split() if sq else []):
            val14.setdefault(nom, []).append((range_boundaries(p if ":" in p else p + ":" + p), typ.group(1) if typ else "list", f.group(1) if f else ""))
def validation(ws, coord):
    for dv in ws.data_validations.dataValidation:
        if coord in dv.sqref:
            return dv.type or "", dv.formula1 or ""
    col, row = coordinate_from_string(coord)
    ci = column_index_from_string(col)
    for b, t, f in val14.get(ws.title, []):
        if b[0] <= ci <= b[2] and b[1] <= row <= b[3]:
            return t, f
    return "", ""
def libelle(ws, r, jusqua):
    ids = []
    for c in range(1, jusqua):
        v = ws.cell(r, c).value
        if isinstance(v, str):
            ids += [i for i in re.findall(r"template_label_[A-Za-z0-9_]+", v) if i in tr]
            if not v.startswith("=") and not ids and len(v) > 3 and c >= 3:
                return v, {"en": v, "fr": "", "es": ""}
    return (ids[0], tr[ids[0]]) if ids else ("", {"en": "", "fr": "", "es": ""})
sortie = []
for nom_feuille in ("General Information", "Environmental Disclosures", "Social Disclosures", "Governance Disclosures"):
    ws = wb[nom_feuille]
    vus_tables = set()
    dernier_para = ""
    for r in range(1, ws.max_row + 1):
        a = ws.cell(r, 1).value
        if a not in (None, "") and not str(a).startswith("ℹ") and not str(a).startswith("="):
            dernier_para = str(a)
        for c in range(3, 16):
            cell = ws.cell(r, c)
            if cell.protection.locked or (isinstance(cell.value, str) and cell.value.startswith("=")):
                continue
            if type(cell).__name__ == "MergedCell":
                continue
            coord = cell.coordinate
            ns = noms_de(nom_feuille, coord)
            table = next((n for n, b in ns if b[3] - b[1] >= 5), "")
            if table:
                cle = (table, c)
                if cle in vus_tables:
                    continue
                vus_tables.add(cle)
            lab_id, lab = libelle(ws, r, c)
            if not lab_id:  # entête de colonne d'un tableau
                for rr in range(r - 1, max(r - 6, 0), -1):
                    v = ws.cell(rr, c).value
                    if isinstance(v, str):
                        ids = [i for i in re.findall(r"template_label_[A-Za-z0-9_]+", v) if i in tr]
                        if ids:
                            lab_id, lab = ids[0], tr[ids[0]]
                            break
            t, f = validation(ws, coord)
            sortie.append({"onglet": nom_feuille, "cellule": coord, "ligne": r, "paragraphe": dernier_para if ws.cell(r, 1).value not in (None, "") else "",
                           "label_id": lab_id, "en": lab["en"] or "", "fr": lab["fr"] or "", "es": lab["es"] or "",
                           "valeur_defaut": "" if cell.value is None else str(cell.value), "format": cell.number_format,
                           "validation": t, "liste": f[:200], "noms": " ".join(n for n, _ in ns), "table": table})
json.dump(sortie, open(sys.argv[2] + ".json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
with open(sys.argv[2] + ".csv", "w", encoding="utf-8", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(sortie[0]))
    w.writeheader()
    w.writerows(sortie)
print(len(sortie), "cellules de saisie")
