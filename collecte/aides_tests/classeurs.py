"""Comparaison de deux fichiers Excel produits par l'outil (tests d'équivalence d'une construction plus rapide) : les
parties du fichier (onglets, styles, textes partagés, commentaires) doivent être identiques octet par octet, sauf les
propriétés du document (dates de création et de modification). Si une partie diffère, ``differences`` dit aussi la
première cellule qui change, pour le message du test."""
import io
import zipfile

from openpyxl import load_workbook

IGNOREES = {"docProps/core.xml"}  # dates de création et de modification du classeur


def parties(octets):
    with zipfile.ZipFile(io.BytesIO(octets)) as z:
        return {n: z.read(n) for n in z.namelist() if n not in IGNOREES}


def _cellule(c):
    return (c.value, c.data_type, c.number_format, repr(c.font), repr(c.fill), repr(c.border), repr(c.alignment),
            repr(c.protection), c.comment.text if c.comment else None)


def premiere_cellule_differente(a, b):
    wa, wb = load_workbook(io.BytesIO(a)), load_workbook(io.BytesIO(b))
    if wa.sheetnames != wb.sheetnames:
        return f"onglets : {wa.sheetnames} != {wb.sheetnames}"
    for nom in wa.sheetnames:
        sa, sb = wa[nom], wb[nom]
        for ra, rb in zip(sa.iter_rows(), sb.iter_rows()):
            for ca, cb in zip(ra, rb):
                if _cellule(ca) != _cellule(cb):
                    return f"{nom}!{ca.coordinate} : {_cellule(ca)} != {_cellule(cb)}"
        if (sa.max_row, sa.max_column) != (sb.max_row, sb.max_column):
            return f"{nom} : taille {(sa.max_row, sa.max_column)} != {(sb.max_row, sb.max_column)}"
    return "aucune cellule différente (mise en forme conditionnelle, validations, réglages de l'onglet ?)"


def differences(a, b):
    """[] si les deux fichiers sont identiques (hors propriétés du document), sinon la liste des parties qui diffèrent
    et la première cellule différente."""
    pa, pb = parties(a), parties(b)
    autres = sorted(n for n in set(pa) | set(pb) if pa.get(n) != pb.get(n))
    return autres + [premiere_cellule_differente(a, b)] if autres else []
