"""Modèles d'export : le filtre « Thèmes » désignait des textes ; il désigne désormais des thèmes de référentiel
(identifiants). Les noms reconnus sont convertis, les autres retirés (le modèle porte alors sur tous les thèmes)."""
from django.db import migrations


def convertir(apps, schema_editor):
    Theme, Reglage = apps.get_model("referentiel", "Theme"), apps.get_model("collecte", "ReglageExport")
    par_nom = {}
    for t in Theme.objects.filter(parent=None):
        par_nom.setdefault(t.nom, str(t.id))
    for r in Reglage.objects.all():
        p = dict(r.parametres or {})
        if p.get("themes"):
            p["themes"] = [par_nom[n] for n in p["themes"] if n in par_nom]
            r.parametres = p
            r.save(update_fields=["parametres"])


class Migration(migrations.Migration):
    dependencies = [
        ("collecte", "0011_types_par_comportement"),
        ("referentiel", "0006_referentiels"),
    ]

    operations = [migrations.RunPython(convertir, migrations.RunPython.noop)]
