"""Base existante (créée avant les paramètres de l'installation) : la ligne des paramètres est créée, en français (seule
langue de l'outil à l'époque : la langue de référence de ses contenus le reste). L'identité garde les valeurs par défaut,
neutres. Base neuve : rien.

Renommée : une base créée avant la note sous l'ancien nom dans django_migrations ; le nom actuel y est
ajouté avant toute migration (``espaces/migrations_renommees.py``). Elle ne repasse donc jamais sur une base qui l'a eue."""
from django.db import migrations


def creer(apps, schema_editor):
    Organisation = apps.get_model("referentiel", "Organisation")
    KPI = apps.get_model("referentiel", "KPI")
    if Organisation.objects.exists() or KPI.objects.exists():
        apps.get_model("parametres", "Instance").objects.update_or_create(pk=1, defaults={"langue": "fr"})


class Migration(migrations.Migration):
    dependencies = [("parametres", "0001_instance"), ("referentiel", "0002_mot_de_passe_provisoire")]
    operations = [migrations.RunPython(creer, migrations.RunPython.noop)]
