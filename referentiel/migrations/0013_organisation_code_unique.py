"""Code d'organisation unique (migration séparée : sous PostgreSQL, pas de contrainte posée dans la transaction du remplissage)."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("referentiel", "0012_organisation_code"),
    ]

    operations = [
        migrations.AlterField(
            model_name="organisation",
            name="code",
            field=models.CharField(blank=True, help_text="Identifiant stable dans les exports (Power BI) : ne change pas quand on renomme.",
                                   max_length=30, unique=True, verbose_name="code"),
        ),
    ]
