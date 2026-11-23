"""Assistant « Mise en place » : étape en cours et fin de la mise en place. Une installation qui a déjà des comptes
(base existante, démos) est marquée terminée : elle ne voit jamais l'assistant."""
from django.db import migrations, models


def marquer_existantes(apps, schema_editor):
    if apps.get_model("referentiel", "Utilisateur").objects.exists():
        Instance = apps.get_model("parametres", "Instance")
        i, _ = Instance.objects.get_or_create(pk=1)
        i.mise_en_place_terminee = True
        i.save(update_fields=["mise_en_place_terminee"])


class Migration(migrations.Migration):

    dependencies = [
        ("parametres", "0006_retrait_glossaire"),
        ("referentiel", "0009_versions_referentiels"),
    ]

    operations = [
        migrations.AddField(
            model_name="instance",
            name="mise_en_place_etape",
            field=models.PositiveSmallIntegerField(default=0, help_text="Assistant de premier lancement : étape en cours (0 = pas commencé).",
                                                   verbose_name="étape de la mise en place"),
        ),
        migrations.AddField(
            model_name="instance",
            name="mise_en_place_terminee",
            field=models.BooleanField(default=False, verbose_name="mise en place terminée"),
        ),
        migrations.RunPython(marquer_existantes, migrations.RunPython.noop),
    ]
