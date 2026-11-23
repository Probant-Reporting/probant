"""Version, origine, provenance et identifiant stable des référentiels (paquets référentiels, bibliothèque)."""
import uuid

from django.db import migrations, models


def identifiants(apps, schema_editor):
    for r in apps.get_model("referentiel", "Referentiel").objects.all():
        r.identifiant = uuid.uuid4()
        r.save(update_fields=["identifiant"])


class Migration(migrations.Migration):

    dependencies = [
        ("referentiel", "0008_frequences"),
    ]

    operations = [
        migrations.AddField(
            model_name="referentiel",
            name="origine",
            field=models.CharField(choices=[("cree", "Créé dans l'outil"), ("importe", "Importé (paquet)"),
                                            ("fourni", "Fourni (bibliothèque)")], default="cree", max_length=10),
        ),
        migrations.AddField(
            model_name="referentiel",
            name="provenance",
            field=models.CharField(blank=True, help_text="D'où il vient : bibliothèque, fichier, installation d'origine.", max_length=200),
        ),
        migrations.AddField(
            model_name="referentiel",
            name="version",
            field=models.CharField(default="1.0", help_text="Ex. « 1.0 », « 2026.1 » : comparée à la réimportation d'un paquet.",
                                   max_length=20),
        ),
        migrations.AddField(
            model_name="referentiel",
            name="identifiant",
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.RunPython(identifiants, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="referentiel",
            name="identifiant",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True,
                                   help_text="Identité stable, transmise par les paquets : reconnaît une nouvelle version du même référentiel."),
        ),
    ]
