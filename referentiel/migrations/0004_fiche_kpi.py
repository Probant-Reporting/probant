"""Fiche KPI réglable (phase 3).

- l'ancien identifiant devient le « code » du KPI (même valeur, toujours la clé ; ``_cle_kpi.py``) ;
- unité, type de saisie et type de réponse deviennent des références vers Paramètres › Référentiel
  (une unité par texte distinct ; les codes des types sont les anciennes valeurs : rien à recopier) ;
- description, à inclure, à exclure et source passent dans des catégories de description ;
- les champs de l'ancien format (ID EFRAG, CSRD 2026, audits, nouveau, origine, à vérifier, formule d'origine)
  deviennent des champs personnalisés, créés seulement s'ils portent une information (sinon rien n'est perdu).
"""
from collections import Counter

import django.db.models.deletion
from django.db import migrations, models

import parametres.models
import referentiel.models
from referentiel.migrations._cle_kpi import cle_kpi_nommee_code

# Comptages : nombre entier attendu (ancienne liste du contrôle « format » de la cohérence)
UNITES_COMPTAGE = {"employees", "accidents", "deaths", "complaints", "incidents", "members", "hires", "departures", "cases",
                   "reports", "warehouses", "units", "breaches", "requests", "actions", "suppliers", "countries", "brands",
                   "products", "sales", "parcels", "professions", "applications", "virtual machines", "meals", "nights"}
# Installation neuve (aucun KPI) : quelques unités courantes
UNITES_BASE = [  # symbole, libellé, entier, décimales, famille
    ("kWh", "kilowattheure", False, 0, "Énergie"), ("MWh", "mégawattheure", False, 1, "Énergie"),
    ("tCO2eq", "tonne équivalent CO2", False, 1, "Émissions"), ("kgCO2eq", "kilogramme équivalent CO2", False, 0, "Émissions"),
    ("t", "tonne", False, 1, "Masse"), ("kg", "kilogramme", False, 0, "Masse"), ("m³", "mètre cube", False, 0, "Volume"),
    ("L", "litre", False, 0, "Volume"), ("km", "kilomètre", False, 0, "Distance"), ("€", "euro", False, 0, "Monnaie"),
    ("k€", "millier d'euros", False, 0, "Monnaie"), ("M€", "million d'euros", False, 1, "Monnaie"),
    ("salariés", "salariés", True, 0, "Effectif"), ("h", "heure", False, 0, "Durée"), ("jours", "jours", False, 0, "Durée"),
]
CHAMPS_ANCIEN_FORMAT = [  # code (= ancien champ), libellé, type, valeurs possibles
    ("id_efrag", "ID EFRAG", "texte", []),
    ("csrd_2026", "CSRD 2026", "liste", ["Oui", "Non", "Sous-jacent"]),
    ("audit_2025", "Audit 2025", "liste", ["Oui", "Non", "Sous-jacent"]),
    ("audit_2026", "Audit 2026", "liste", ["Oui", "Non", "Sous-jacent"]),
    ("nouveau", "Nouveau", "case", []),
    ("origine", "Origine", "texte", []),
    ("a_verifier", "À vérifier", "texte", []),
    ("formule_texte", "Formule (texte d'origine)", "texte", []),
]
DESCRIPTIONS = [("description", "description"), ("a_inclure", "a_inclure"), ("a_exclure", "a_exclure"), ("source", "source_donnees")]


def famille(symbole):
    s = symbole.lower()
    if "co2" in s or "co₂" in s:
        return "Émissions"
    if s in ("kwh", "mwh", "gwh", "wh"):
        return "Énergie"
    if s in ("t", "kg", "g", "tonne(s)", "tonnes"):
        return "Masse"
    if s in ("€", "k€", "m€"):
        return "Monnaie"
    if s in ("m³", "m3", "l"):
        return "Volume"
    if s in ("hours", "days", "years", "h", "jours"):
        return "Durée"
    if s in ("employees", "fte", "people", "members", "employés"):
        return "Effectif"
    if s == "%":
        return "Pourcentage"
    if s.startswith("/"):
        return "Note"
    return ""


def creer_unites(apps, schema_editor):
    KPI, Unite = apps.get_model("referentiel", "KPI"), apps.get_model("parametres", "Unite")
    decimales = {}
    for u, d in KPI.objects.exclude(unite="").exclude(unite=None).values_list("unite", "decimales"):
        decimales.setdefault(u, Counter())[d] += 1
    if not decimales and not KPI.objects.exists() and not Unite.objects.exists():
        for i, (symbole, libelle, entier, dec, fam) in enumerate(UNITES_BASE, start=1):
            Unite.objects.create(code=symbole, symbole=symbole, libelle=libelle, entier=entier, decimales=dec, famille=fam, ordre=i)
    for i, u in enumerate(sorted(decimales, key=str.lower), start=1):
        entier = u.lower() in UNITES_COMPTAGE
        Unite.objects.get_or_create(code=u, defaults=dict(symbole=u, entier=entier, famille=famille(u), ordre=i,
                                                           decimales=0 if entier else decimales[u].most_common(1)[0][0]))
    KPI.objects.filter(unite="").update(unite=None)


def types_manquants(apps, schema_editor):
    """Un type inconnu (base modifiée à la main) devient un type de plus plutôt que d'être perdu."""
    KPI = apps.get_model("referentiel", "KPI")
    TypeSaisie, TypeReponse = apps.get_model("parametres", "TypeSaisie"), apps.get_model("parametres", "TypeReponse")
    for code in set(KPI.objects.values_list("type_saisie", flat=True)) - set(TypeSaisie.objects.values_list("code", flat=True)):
        TypeSaisie.objects.create(code=code, libelle=code, abrege=code[:20], couleur="#5A6B85", couleur_fond="#E6E9EE",
                                  couleur_texte="#3F4B5E", comportement="saisie", ordre=99)
    for code in set(KPI.objects.values_list("type_reponse", flat=True)) - set(TypeReponse.objects.values_list("code", flat=True)):
        TypeReponse.objects.create(code=code, libelle=code, format="nombre", ordre=99)


def descriptions_et_champs(apps, schema_editor):
    KPI, Description = apps.get_model("referentiel", "KPI"), apps.get_model("referentiel", "Description")
    Champ = apps.get_model("parametres", "ChampPersonnalise")
    kpis = list(KPI.objects.all())
    Description.objects.bulk_create([Description(kpi=k, categorie_id=cat, texte=getattr(k, champ))
                                     for k in kpis for cat, champ in DESCRIPTIONS if getattr(k, champ)], batch_size=1000)

    def porte_information(code, type_):
        if type_ == "case":
            return any(getattr(k, code) for k in kpis)
        if type_ == "liste":
            return any(getattr(k, code) not in ("", "Non") for k in kpis)
        return any(getattr(k, code) for k in kpis)

    retenus = []
    for i, (code, libelle, type_, valeurs) in enumerate(CHAMPS_ANCIEN_FORMAT, start=1):
        if porte_information(code, type_):
            Champ.objects.get_or_create(code=code, defaults=dict(libelle=libelle, type=type_, valeurs=valeurs, ordre=i))
            retenus.append((code, type_))
    for k in kpis:
        champs = {}
        for code, type_ in retenus:
            v = getattr(k, code)
            if type_ == "case":
                if v:
                    champs[code] = True
            elif v:
                champs[code] = v
        k.champs = champs
    KPI.objects.bulk_update(kpis, ["champs"], batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ("parametres", "0004_referentiel_reglable"),
        ("referentiel", "0003_niveaux_dynamiques"),
    ]

    operations = [
        # le code du KPI : l'ancien identifiant, même valeur (0001 le nomme « code » ; base d'avant : colonne renommée ici)
        migrations.RunPython(cle_kpi_nommee_code, migrations.RunPython.noop),
        migrations.AlterModelOptions(  # l'ordre de tri citait l'ancien nom
            name="kpi",
            options={"base_manager_name": "objects", "ordering": ["ordre", "code"], "verbose_name": "KPI", "verbose_name_plural": "KPI"},
        ),
        migrations.AlterField(
            model_name="kpi",
            name="code",
            field=models.CharField(help_text="Choisi à la création, puis figé : il sert dans les formules et les fichiers.",
                                   max_length=30, primary_key=True, serialize=False, validators=[referentiel.models.valider_code_kpi]),
        ),
        # unités : une par texte distinct, puis référence
        migrations.AlterField(model_name="kpi", name="unite", field=models.CharField(max_length=60, null=True, blank=True)),
        migrations.RunPython(creer_unites, migrations.RunPython.noop),
        migrations.RunPython(types_manquants, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="kpi",
            name="unite",
            field=models.ForeignKey(blank=True, db_column="unite", null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name="kpis", to="parametres.unite", verbose_name="unité"),
        ),
        migrations.AlterField(
            model_name="kpi",
            name="type_saisie",
            field=models.ForeignKey(db_column="type_saisie", on_delete=django.db.models.deletion.PROTECT, related_name="kpis",
                                    to="parametres.typesaisie", verbose_name="type de saisie"),
        ),
        migrations.AlterField(
            model_name="kpi",
            name="type_reponse",
            field=models.ForeignKey(db_column="type_reponse", on_delete=django.db.models.deletion.PROTECT, related_name="kpis",
                                    to="parametres.typereponse", verbose_name="type de réponse",
                                    default=parametres.models.type_reponse_par_defaut),
        ),
        migrations.AlterField(
            model_name="kpi",
            name="methode_agregation",
            field=models.CharField(choices=[("Somme", "Somme"), ("Formule", "Formule"), ("Décompte", "Décompte"), ("Aucune", "Aucune")],
                                   default="Aucune", max_length=10, verbose_name="agrégation"),
        ),
        # descriptions et champs personnalisés
        migrations.CreateModel(
            name="Description",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("texte", models.TextField()),
                ("categorie", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="textes",
                                                to="parametres.categoriedescription", verbose_name="catégorie")),
                ("kpi", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="descriptions", to="referentiel.kpi")),
            ],
            options={
                "verbose_name": "description de KPI",
                "verbose_name_plural": "descriptions de KPI",
                "constraints": [models.UniqueConstraint(fields=("kpi", "categorie"), name="description_unique")],
            },
        ),
        migrations.AddField(
            model_name="kpi",
            name="champs",
            field=models.JSONField(blank=True, default=dict, verbose_name="champs personnalisés",
                                   help_text="{code du champ: valeur} (Paramètres › Référentiel › Champs personnalisés)"),
        ),
        migrations.RunPython(descriptions_et_champs, migrations.RunPython.noop),
        migrations.RemoveField(model_name="kpi", name="description"),
        migrations.RemoveField(model_name="kpi", name="a_inclure"),
        migrations.RemoveField(model_name="kpi", name="a_exclure"),
        migrations.RemoveField(model_name="kpi", name="source_donnees"),
        migrations.RemoveField(model_name="kpi", name="id_efrag"),
        migrations.RemoveField(model_name="kpi", name="csrd_2026"),
        migrations.RemoveField(model_name="kpi", name="audit_2025"),
        migrations.RemoveField(model_name="kpi", name="audit_2026"),
        migrations.RemoveField(model_name="kpi", name="nouveau"),
        migrations.RemoveField(model_name="kpi", name="origine"),
        migrations.RemoveField(model_name="kpi", name="a_verifier"),
        migrations.RemoveField(model_name="kpi", name="formule_texte"),
    ]
