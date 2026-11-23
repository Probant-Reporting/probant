"""Contrôles de ``manage.py check`` (lancés aussi au démarrage par ``migrate`` : image Docker, Clever Cloud) sur les
fichiers de langue de l'interface (``controle_libelles``). Anglais ou français abîmé : erreur, le démarrage s'arrête.
Autre langue abîmée (fichier illisible, valeur ni texte ni pluriel) : avertissement, la langue n'est plus proposée.
Messages en anglais (pour l'IT)."""
from django.core import checks

from . import controle_libelles as C


@checks.register()
def fichiers_de_langue(app_configs=None, **kwargs):
    messages = []
    for langue in C.langues_presentes():
        conseil = f"Restore the files libelles/*.{langue}.json of this version of the tool."
        try:
            abimes = [p for p in C.problemes(langue) if p[0] in ("illisible", "forme")]
        except Exception as e:  # noqa: BLE001 - anglais ou français illisible : erreur franche
            messages.append(checks.Error(f"Language files of \"{langue}\" are not valid: {e}", id="parametres.L001", hint=conseil))
            continue
        if not abimes:
            continue
        detail = "; ".join((d or f"{z}.{langue}.json") + (f" ({c})" if c else "") for _, z, c, d in abimes[:5])
        if langue in C.ESSENTIELLES:
            messages.append(checks.Error(f"Language files of \"{langue}\" are damaged: {detail}", id="parametres.L001", hint=conseil))
        else:
            messages.append(checks.Warning(f"Language \"{langue}\" is not offered, damaged files: {detail}", id="parametres.L002",
                                           hint=conseil))
    return messages
