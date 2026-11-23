"""Textes de départ d'une installation migrée : catégories de description des KPI (Description, À inclure, À exclure,
Source des données) en anglais et espagnol ; types de saisie (Saisi, Calculé, FE) et types de réponse (Numérique,
Pourcentage) en espagnol (l'anglais existait déjà).

La migration 0004 a créé les catégories en français seulement, et ``creer_par_defaut`` ne s'exécute que sur une base
vide : toute installation migrée affichait « À inclure » en anglais. Sans perte : seul un élément de code fourni dont le
libellé est celui d'origine reçoit les traductions manquantes ; un libellé renommé ou une traduction déjà saisie n'est
jamais touché. Pas de changement de modèle. Retour arrière : sans effet (les traductions ajoutées ne gênent pas)."""
from django.db import migrations

# code : (libellé d'origine en français, traductions) ; les textes sont figés ici (une migration ne suit pas le code)
CATEGORIES = {
    "description": ("Description", {"en": "Description", "es": "Descripción"}),
    "a_inclure": ("À inclure", {"en": "To include", "es": "Incluir"}),
    "a_exclure": ("À exclure", {"en": "To exclude", "es": "Excluir"}),
    "source": ("Source des données", {"en": "Data source", "es": "Fuente de los datos"}),
}
# code : (libellé d'origine, champs en espagnol)
TYPES_SAISIE_ES = {"Saisi": ("Saisi", {"libelle": "Introducido", "abrege": "Entrada"}),
                   "Calculé": ("Calculé", {"libelle": "Calculado", "abrege": "Cálc."}),
                   "FE": ("Facteur d'émission", {"libelle": "Factor de emisión", "abrege": "FE"})}
TYPES_REPONSE_ES = {"Numérique": ("Numérique", {"libelle": "Número"}), "Pourcentage": ("Pourcentage", {"libelle": "Porcentaje"})}


def _completer(objet, langue, champs):
    """Ajoute les champs absents de la traduction ``langue`` ; renvoie True si l'objet a changé."""
    traductions = dict(objet.traductions or {})
    cible = dict(traductions.get(langue) or {})
    for champ, texte in champs.items():
        if not cible.get(champ):
            cible[champ] = texte
    if cible == (traductions.get(langue) or {}):
        return False
    traductions[langue] = cible
    objet.traductions = traductions
    return True


def traduire(apps, schema_editor):
    tables = [("TypeSaisie", TYPES_SAISIE_ES), ("TypeReponse", TYPES_REPONSE_ES),
              ("CategorieDescription", {code: (origine, trads) for code, (origine, trads) in CATEGORIES.items()})]
    for modele, table in tables:
        Modele = apps.get_model("parametres", modele)
        for code, (origine, champs) in table.items():
            o = Modele.objects.filter(code=code).first()
            if o is None or o.libelle != origine:
                continue
            if modele == "CategorieDescription":
                modifie = [_completer(o, langue, {"libelle": texte}) for langue, texte in champs.items()]
            else:
                modifie = [_completer(o, "es", champs)]
            if any(modifie):
                o.save(update_fields=["traductions"])


class Migration(migrations.Migration):
    dependencies = [("parametres", "0026_vues_personnelles_10")]
    operations = [migrations.RunPython(traduire, migrations.RunPython.noop)]
