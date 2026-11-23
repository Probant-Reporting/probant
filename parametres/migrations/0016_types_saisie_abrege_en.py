"""Traductions anglaises de l'étiquette courte des types de saisie fournis par défaut (« Saisie » → « Input »,
« Calcul » → « Calc. », « FE » → « EF », comme la bibliothèque des socles) : la pastille du type s'affichait en
français dans l'interface anglaise. Comme 0015 : pour une installation neuve seulement ; une base
qui a déjà des KPI garde ses libellés tels quels (son export en anglais ne change pas), ils restent réglables dans
Paramètres › Langues › Traductions. Retour arrière : sans effet."""
from django.db import migrations

ABREGES_EN = {"Saisi": ("Saisie", "Input"), "Calculé": ("Calcul", "Calc."), "FE": ("FE", "EF")}  # comme parametres.referentiel


def traduire(apps, schema_editor):
    if apps.get_model("referentiel", "KPI").objects.exists():
        return  # installation existante : rien ne change
    for t in apps.get_model("parametres", "TypeSaisie").objects.filter(code__in=ABREGES_EN):
        fr, en = ABREGES_EN[t.code]
        tr = dict(t.traductions or {})
        if t.abrege == fr and not (tr.get("en") or {}).get("abrege"):  # étiquette d'origine, pas encore traduite
            tr["en"] = {**(tr.get("en") or {}), "abrege": en}
            t.traductions = tr
            t.save(update_fields=["traductions"])


class Migration(migrations.Migration):
    dependencies = [("parametres", "0015_types_reponse_en")]
    operations = [migrations.RunPython(traduire, migrations.RunPython.noop)]
