"""Traductions anglaises des types de réponse fournis par défaut (« Numérique » → « Number », « Pourcentage » →
« Percentage »): pour une installation neuve seulement. Une base qui a déjà des KPI garde ses
libellés tels quels (son export en anglais ne change pas) ; ils restent réglables dans Paramètres › Langues › Traductions.
Retour arrière : sans effet."""
from django.db import migrations

TYPES_EN = {"Numérique": "Number", "Pourcentage": "Percentage"}  # comme parametres.referentiel.TYPES_REPONSE_EN


def traduire(apps, schema_editor):
    if apps.get_model("referentiel", "KPI").objects.exists():
        return  # installation existante : rien ne change
    for t in apps.get_model("parametres", "TypeReponse").objects.filter(code__in=TYPES_EN):
        tr = dict(t.traductions or {})
        if not (tr.get("en") or {}).get("libelle"):
            tr["en"] = {**(tr.get("en") or {}), "libelle": TYPES_EN[t.code]}
            t.traductions = tr
            t.save(update_fields=["traductions"])


class Migration(migrations.Migration):
    dependencies = [("parametres", "0014_visualisation"), ("referentiel", "0016_na_compte_zero_entiers")]
    operations = [migrations.RunPython(traduire, migrations.RunPython.noop)]
