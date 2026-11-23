"""Thématique d'unité « Pourcentage » (ancien nom) fusionnée dans « Pourcentage et ratios » (catalogue des unités)."""
from django.db import migrations


def fusionner(apps, schema_editor):
    apps.get_model("parametres", "Unite").objects.filter(famille="Pourcentage").update(famille="Pourcentage et ratios")


class Migration(migrations.Migration):
    dependencies = [("parametres", "0009_palettes_enregistrees")]
    operations = [migrations.RunPython(fusionner, migrations.RunPython.noop)]
