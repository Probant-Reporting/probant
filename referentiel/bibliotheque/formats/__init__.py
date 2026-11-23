"""Formats officiels d'export : classeurs d'une autorité ou d'un normalisateur que l'outil remplit avec les valeurs d'une
période (par exemple le classeur VS de l'EFRAG). Un format = un module de ce dossier (correspondance KPI → cellule) et
son classeur officiel, livré avec l'outil ; collecte/export_officiel.py lit les valeurs et produit le fichier.
"""
from pathlib import Path

DOSSIER = Path(__file__).resolve().parent


def formats():
    """{code: module} des formats officiels connus."""
    from . import vs_efrag

    return {vs_efrag.CODE: vs_efrag}


def format_de(code):
    try:
        return formats()[code]
    except KeyError:
        raise KeyError(f"format officiel inconnu : {code}") from None


def formats_pour(codes_referentiels):
    """Formats qui exportent au moins un des référentiels donnés (par leur code)."""
    codes = set(codes_referentiels)
    return [f for f in formats().values() if codes & set(f.REFERENTIELS)]
