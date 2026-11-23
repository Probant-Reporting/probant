"""Textes de départ d'une installation, dans les sept langues de l'interface (règle du projet) : les
niveaux de l'arbre fournis (Groupe, Pays, Entité, Site), les types de saisie (Saisi, Calculé, Facteur d'émission), les types de
réponse (Numérique, Pourcentage, Texte rédigé), les catégories de description et les quinze unités créées par les premières
migrations n'avaient de traduction qu'en anglais et en espagnol (les unités, les niveaux en espagnol : aucune). L'allemand,
l'italien, le néerlandais et le portugais montraient donc le français (« Site », « Saisie », « Calcul », « Facteur d'émission »…).

Additive et sans perte : seul un élément de code fourni dont le texte est encore celui d'origine reçoit les traductions
manquantes ; un texte renommé, une traduction déjà saisie, la langue de référence de l'installation ne sont jamais touchés.
Pas de changement de modèle. Retour arrière : sans effet (les traductions ajoutées ne gênent pas). Les textes sont figés ici
(une migration ne suit pas le code) ; ceux d'une installation neuve ou vidée sont dans ``parametres/referentiel.py`` et
``parametres/niveaux.py``."""
from django.db import migrations

# ---- niveaux : code → (nom d'origine, pluriel d'origine, {langue: (nom, pluriel)})
NIVEAUX = {
    "Group": ("Groupe", "Groupe", {"es": ("Grupo", "Grupo"), "de": ("Konzern", "Konzern"), "it": ("Gruppo", "Gruppo"),
                                   "nl": ("Groep", "Groep"), "pt": ("Grupo", "Grupo")}),
    "Country": ("Pays", "Pays", {"es": ("País", "Países"), "de": ("Land", "Länder"), "it": ("Paese", "Paesi"),
                                 "nl": ("Land", "Landen"), "pt": ("País", "Países")}),
    "Entity": ("Entité", "Entités", {"es": ("Entidad", "Entidades"), "de": ("Gesellschaft", "Gesellschaften"),
                                     "it": ("Entità", "Entità"), "nl": ("Entiteit", "Entiteiten"), "pt": ("Entidade", "Entidades")}),
    "Site": ("Site", "Sites", {"es": ("Centro", "Centros"), "de": ("Standort", "Standorte"), "it": ("Sede", "Sedi"),
                               "nl": ("Locatie", "Locaties"), "pt": ("Local", "Locais")}),
}
# ---- types de saisie : code → (libellé d'origine, abrégé d'origine, {langue: (libellé, abrégé)}) ; l'espagnol existait déjà
TYPES_SAISIE = {
    "Saisi": ("Saisi", "Saisie", {"de": ("Erfasst", "Eingabe"), "it": ("Inserito", "Inserim."), "nl": ("Ingevoerd", "Invoer"),
                                  "pt": ("Introduzido", "Introd.")}),
    "Calculé": ("Calculé", "Calcul", {"de": ("Berechnet", "Berechn."), "it": ("Calcolato", "Calcolo"),
                                      "nl": ("Berekend", "Berek."), "pt": ("Calculado", "Cálc.")}),
    "FE": ("Facteur d'émission", "FE", {"de": ("Emissionsfaktor", "EF"), "it": ("Fattore di emissione", "FE"),
                                        "nl": ("Emissiefactor", "EF"), "pt": ("Fator de emissão", "FE")}),
}
# ---- types de réponse : code → (libellé d'origine, {langue: libellé})
TYPES_REPONSE = {
    "Numérique": ("Numérique", {"de": "Zahl", "it": "Numero", "nl": "Getal", "pt": "Número"}),
    "Pourcentage": ("Pourcentage", {"de": "Prozentsatz", "it": "Percentuale", "nl": "Percentage", "pt": "Percentagem"}),
    "TexteRedige": ("Texte rédigé", {"de": "Ausformulierter Text", "it": "Testo redatto", "nl": "Uitgeschreven tekst",
                                     "pt": "Texto redigido"}),
}
# ---- catégories de description : code → (libellé d'origine, {langue: libellé})
CATEGORIES = {
    "description": ("Description", {"de": "Beschreibung", "it": "Descrizione", "nl": "Beschrijving", "pt": "Descrição"}),
    "a_inclure": ("À inclure", {"de": "Einzuschließen", "it": "Da includere", "nl": "Op te nemen", "pt": "A incluir"}),
    "a_exclure": ("À exclure", {"de": "Auszuschließen", "it": "Da escludere", "nl": "Uit te sluiten", "pt": "A excluir"}),
    "source": ("Source des données", {"de": "Datenquelle", "it": "Fonte dei dati", "nl": "Gegevensbron", "pt": "Fonte dos dados"}),
}
# ---- unités créées par les premières migrations : code → (libellé d'origine, {langue: libellé}) ; pour « salariés » et
# « jours », dont le symbole est un mot, le libellé traduit sert aussi de symbole
UNITES = {
    "kWh": ("kilowattheure", {"en": "kilowatt-hour", "es": "kilovatio hora", "de": "Kilowattstunde", "it": "kilowattora",
                              "nl": "kilowattuur", "pt": "quilowatt-hora"}),
    "MWh": ("mégawattheure", {"en": "megawatt-hour", "es": "megavatio hora", "de": "Megawattstunde", "it": "megawattora",
                              "nl": "megawattuur", "pt": "megawatt-hora"}),
    "tCO2eq": ("tonne équivalent CO2", {"en": "tonne of CO₂ equivalent", "es": "tonelada de CO₂ equivalente",
                                        "de": "Tonne CO₂-Äquivalent", "it": "tonnellata di CO₂ equivalente",
                                        "nl": "ton CO₂-equivalent", "pt": "tonelada de CO₂ equivalente"}),
    "kgCO2eq": ("kilogramme équivalent CO2", {"en": "kilogram of CO₂ equivalent", "es": "kilogramo de CO₂ equivalente",
                                              "de": "Kilogramm CO₂-Äquivalent", "it": "chilogrammo di CO₂ equivalente",
                                              "nl": "kilogram CO₂-equivalent", "pt": "quilograma de CO₂ equivalente"}),
    "t": ("tonne", {"en": "tonne", "es": "tonelada", "de": "Tonne", "it": "tonnellata", "nl": "ton", "pt": "tonelada"}),
    "kg": ("kilogramme", {"en": "kilogram", "es": "kilogramo", "de": "Kilogramm", "it": "chilogrammo", "nl": "kilogram",
                          "pt": "quilograma"}),
    "m³": ("mètre cube", {"en": "cubic metre", "es": "metro cúbico", "de": "Kubikmeter", "it": "metro cubo",
                          "nl": "kubieke meter", "pt": "metro cúbico"}),
    "L": ("litre", {"en": "litre", "es": "litro", "de": "Liter", "it": "litro", "nl": "liter", "pt": "litro"}),
    "km": ("kilomètre", {"en": "kilometre", "es": "kilómetro", "de": "Kilometer", "it": "chilometro", "nl": "kilometer",
                         "pt": "quilómetro"}),
    "€": ("euro", {"en": "euro", "es": "euro", "de": "Euro", "it": "euro", "nl": "euro", "pt": "euro"}),
    "k€": ("millier d'euros", {"en": "thousand euros", "es": "miles de euros", "de": "Tausend Euro", "it": "migliaia di euro",
                               "nl": "duizend euro", "pt": "milhares de euros"}),
    "M€": ("million d'euros", {"en": "million euros", "es": "millones de euros", "de": "Millionen Euro",
                               "it": "milioni di euro", "nl": "miljoen euro", "pt": "milhões de euros"}),
    "salariés": ("salariés", {"en": "employees", "es": "empleados", "de": "Beschäftigte", "it": "dipendenti",
                              "nl": "werknemers", "pt": "trabalhadores"}),
    "h": ("heure", {"en": "hour", "es": "hora", "de": "Stunde", "it": "ora", "nl": "uur", "pt": "hora"}),
    "jours": ("jours", {"en": "days", "es": "días", "de": "Tage", "it": "giorni", "nl": "dagen", "pt": "dias"}),
}
SYMBOLES_MOTS = ("salariés", "jours")


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
    Instance = apps.get_model("parametres", "Instance")
    instance = Instance.objects.filter(pk=1).first()
    reference = (instance.langue_reference if instance else "") or "fr"

    def appliquer(modele, code, origine, par_langue):
        """origine : {champ: texte d'origine} ; par_langue : {langue: {champ: texte}}."""
        o = apps.get_model("parametres", modele).objects.filter(code=code).first()
        if o is None or any(getattr(o, champ) != texte for champ, texte in origine.items()):
            return  # absent ou renommé par l'installation : jamais touché
        modifie = [_completer(o, langue, champs) for langue, champs in par_langue.items() if langue != reference]
        if any(modifie):
            o.save(update_fields=["traductions"])

    for code, (nom, pluriel, langues) in NIVEAUX.items():
        appliquer("NiveauHierarchique", code, {"nom": nom, "nom_pluriel": pluriel},
                  {lg: {"nom": n, "nom_pluriel": p} for lg, (n, p) in langues.items()})
    for code, (libelle, abrege, langues) in TYPES_SAISIE.items():
        appliquer("TypeSaisie", code, {"libelle": libelle, "abrege": abrege},
                  {lg: {"libelle": t, "abrege": a} for lg, (t, a) in langues.items()})
    for code, (libelle, langues) in TYPES_REPONSE.items():
        appliquer("TypeReponse", code, {"libelle": libelle}, {lg: {"libelle": t} for lg, t in langues.items()})
    for code, (libelle, langues) in CATEGORIES.items():
        appliquer("CategorieDescription", code, {"libelle": libelle}, {lg: {"libelle": t} for lg, t in langues.items()})
    for code, (libelle, langues) in UNITES.items():
        appliquer("Unite", code, {"libelle": libelle},
                  {lg: ({"libelle": t, "symbole": t} if code in SYMBOLES_MOTS else {"libelle": t}) for lg, t in langues.items()})


class Migration(migrations.Migration):
    dependencies = [("parametres", "0034_exports_arriere_plan")]
    operations = [migrations.RunPython(traduire, migrations.RunPython.noop)]
