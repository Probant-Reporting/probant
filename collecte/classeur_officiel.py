"""Remplir un classeur Excel officiel (modèle d'une autorité, d'un normalisateur : VSME de l'EFRAG…) sans rien en perdre.

openpyxl réécrit tout le classeur et en perd une partie (listes déroulantes d'un autre onglet, mises en forme
conditionnelles étendues, cases à cocher, images, métadonnées des formules matricielles) : le fichier ne serait plus le
modèle officiel. Ici, seules les cellules à remplir changent, directement dans le XML de leur onglet ; toutes les autres
parties du fichier sont recopiées octet pour octet. Le classeur recalcule ses formules à l'ouverture (``fullCalcOnLoad``).

Une cellule qui porte une formule est refusée (``CelluleInterdite``) : le modèle la calcule lui-même à partir des cellules
de saisie, et l'écraser casserait ses contrôles. Bibliothèque standard seulement (pas de lxml en production).
"""
import datetime
import io
import re
import zipfile
from decimal import Decimal
from xml.sax.saxutils import escape

from openpyxl.utils import column_index_from_string
from openpyxl.utils.cell import coordinate_from_string

LONGUEUR_MAX = 32767  # caractères d'une cellule Excel
_INTERDITS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")  # caractères de contrôle refusés par le XML


class CelluleInterdite(ValueError):
    pass


def _attr(balise, nom):
    m = re.search(rf'\s{nom}="([^"]*)"', balise)
    return m.group(1) if m else None


def parties_des_onglets(z):
    """{nom de l'onglet: chemin de sa partie XML (xl/worksheets/sheetN.xml)}."""
    classeur = z.read("xl/workbook.xml").decode("utf-8")
    liens = z.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    cibles = {_attr(r, "Id"): _attr(r, "Target") for r in re.findall(r"<Relationship\b[^>]*>", liens)}
    sortie = {}
    for balise in re.findall(r"<sheet\b[^>]*>", classeur):
        nom = _attr(balise, "name").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'")
        cible = cibles[_attr(balise, "r:id")]
        sortie[nom] = cible.lstrip("/") if cible.startswith("/") else "xl/" + cible
    return sortie


def _contenu(valeur):
    """(attribut t, contenu XML) d'une valeur ; None si la cellule doit rester vide."""
    if valeur is None:
        return None
    if isinstance(valeur, bool):
        return "b", f"<v>{1 if valeur else 0}</v>"
    if isinstance(valeur, (int, float, Decimal)):
        if isinstance(valeur, Decimal):
            valeur = valeur.normalize()
            texte = format(valeur, "f")
        else:
            texte = repr(valeur) if isinstance(valeur, float) else str(valeur)
        return "", f"<v>{texte}</v>"
    if isinstance(valeur, (datetime.date, datetime.datetime)):
        valeur = valeur.isoformat()[:10]
    texte = _INTERDITS.sub("", str(valeur))[:LONGUEUR_MAX]
    if not texte:
        return None
    return "inlineStr", f'<is><t xml:space="preserve">{escape(texte)}</t></is>'


_CELLULE = r'<c r="{coord}"(?=[\s/>])[^>]*?(?:/>|>.*?</c>)'


def _rang(coord):
    col, ligne = coordinate_from_string(coord)
    return ligne, column_index_from_string(col)


def _ecrire_cellule(xml, coord, valeur, onglet, remplacer_formule=False):
    """XML de l'onglet avec la cellule remplie ; (xml, vrai si une formule a été remplacée)."""
    contenu = _contenu(valeur)
    m = re.search(_CELLULE.format(coord=coord), xml, re.S)
    formule = False
    if m:
        ancienne = m.group(0)
        if "<f>" in ancienne or "<f " in ancienne or "<f/>" in ancienne:
            if not remplacer_formule:
                raise CelluleInterdite(f"{onglet}!{coord} : cellule calculée par le modèle (formule)")
            if re.search(r'<f\b[^>]*\bt="shared"[^>]*\bref="', ancienne):  # formule partagée dont dépendent d'autres cellules
                raise CelluleInterdite(f"{onglet}!{coord} : formule partagée, ne peut pas être remplacée")
            formule = True
        style = _attr(re.match(r"<c\b[^>]*", ancienne).group(0), "s")
    else:
        style = None
    s = f' s="{style}"' if style is not None else ""
    if contenu is None:
        nouvelle = f'<c r="{coord}"{s}/>'
    else:
        t, corps = contenu
        nouvelle = f'<c r="{coord}"{s}{f" t={chr(34)}{t}{chr(34)}" if t else ""}>{corps}</c>'
    if m:
        return xml[:m.start()] + nouvelle + xml[m.end():], formule
    if contenu is None:
        return xml, False
    return _inserer(xml, coord, nouvelle), False


def _inserer(xml, coord, nouvelle):
    """Ajoute une cellule absente du XML, à sa place (lignes puis colonnes dans l'ordre)."""
    ligne, colonne = _rang(coord)
    m = re.search(rf'<row r="{ligne}"(?=[\s>/])[^>]*?(?:/>|>(.*?)</row>)', xml, re.S)
    if m:
        balise_row = re.match(r"<row\b[^>]*?(?=/?>)", m.group(0)).group(0)
        corps = m.group(1) or ""
        cellules = list(re.finditer(r'<c r="([A-Z]+)(\d+)"(?=[\s/>])[^>]*?(?:/>|>.*?</c>)', corps, re.S))
        pos = len(corps)
        for c in cellules:
            if column_index_from_string(c.group(1)) > colonne:
                pos = c.start()
                break
        corps = corps[:pos] + nouvelle + corps[pos:]
        balise_row = re.sub(r'\sspans="[^"]*"', "", balise_row)
        return xml[:m.start()] + f"{balise_row}>{corps}</row>" + xml[m.end():]
    debut = xml.index("<sheetData")
    fin_balise = xml.index(">", debut)
    if xml[fin_balise - 1] == "/":  # <sheetData/> vide
        return xml[:debut] + f'<sheetData><row r="{ligne}">{nouvelle}</row></sheetData>' + xml[fin_balise + 1:]
    fin = xml.index("</sheetData>")
    pos = fin
    for r in re.finditer(r'<row r="(\d+)"', xml[fin_balise:fin]):
        if int(r.group(1)) > ligne:
            pos = fin_balise + r.start()
            break
    return xml[:pos] + f'<row r="{ligne}">{nouvelle}</row>' + xml[pos:]


def _recalcul_a_l_ouverture(xml):
    if "<calcPr" not in xml:
        return xml.replace("</workbook>", '<calcPr fullCalcOnLoad="1"/></workbook>')
    return re.sub(r"<calcPr\b([^>]*?)(\s*/?)>", lambda m: "<calcPr" + re.sub(r'\sfullCalcOnLoad="[^"]*"', "", m.group(1))
                  + ' fullCalcOnLoad="1"' + m.group(2) + ">", xml, count=1)


CHAINE_CALCUL = "xl/calcChain.xml"


def _sans_chaine_de_calcul(nom, donnees):
    """Liens et types de contenu sans la chaîne de calcul (Excel la reconstruit à l'ouverture)."""
    texte = donnees.decode("utf-8")
    if nom == "xl/_rels/workbook.xml.rels":
        texte = re.sub(r'<Relationship\b[^>]*Target="(?:/xl/)?calcChain\.xml"[^>]*/>', "", texte)
    elif nom == "[Content_Types].xml":
        texte = re.sub(r'<Override\b[^>]*PartName="/xl/calcChain\.xml"[^>]*/>', "", texte)
    return texte.encode("utf-8")


def remplir(modele, ecritures, formules_remplacees=()):
    """Octets du classeur ``modele`` (chemin ou octets) dont les cellules ``ecritures`` {(onglet, "E278"): valeur} sont
    remplies : nombre, texte, booléen, date (écrite AAAA-MM-JJ) ; None vide la cellule. CelluleInterdite pour une cellule
    à formule, sauf celles de ``formules_remplacees`` {(onglet, cellule)} : le modèle permet d'y mettre la valeur finale à
    la place du calcul (la chaîne de calcul est alors retirée, Excel la reconstruit) ; KeyError pour un onglet inconnu."""
    remplacees = {(o, c.replace("$", "").upper()) for o, c in formules_remplacees}
    source = io.BytesIO(modele) if isinstance(modele, (bytes, bytearray)) else open(modele, "rb")
    with source, zipfile.ZipFile(source) as z:
        parties = parties_des_onglets(z)
        par_partie = {}
        for (onglet, coord), valeur in ecritures.items():
            if onglet not in parties:
                raise KeyError(f"onglet inconnu dans le modèle : {onglet}")
            par_partie.setdefault(parties[onglet], []).append((onglet, coord.replace("$", "").upper(), valeur))
        nouvelles, formule_remplacee = {}, False
        for partie, liste in par_partie.items():
            xml = z.read(partie).decode("utf-8")
            for onglet, coord, valeur in sorted(liste, key=lambda e: _rang(e[1])):
                xml, remplacee = _ecrire_cellule(xml, coord, valeur, onglet, (onglet, coord) in remplacees)
                formule_remplacee = formule_remplacee or remplacee
            nouvelles[partie] = xml.encode("utf-8")
        sortie = io.BytesIO()
        with zipfile.ZipFile(sortie, "w") as dest:
            for info in z.infolist():
                if formule_remplacee and info.filename == CHAINE_CALCUL:
                    continue
                donnees = nouvelles.get(info.filename) or z.read(info.filename)
                if info.filename == "xl/workbook.xml":
                    donnees = _recalcul_a_l_ouverture(donnees.decode("utf-8")).encode("utf-8")
                elif formule_remplacee and info.filename in ("xl/_rels/workbook.xml.rels", "[Content_Types].xml"):
                    donnees = _sans_chaine_de_calcul(info.filename, donnees)
                dest.writestr(info, donnees, compress_type=info.compress_type)
    return sortie.getvalue()
