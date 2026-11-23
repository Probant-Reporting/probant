"""Corbeille réglable : nombre de jours pendant lesquels un export, une liste de KPI ou une vue supprimés
restent restaurables (Paramètres › Hébergement). Une colonne ajoutée, à 30 jours (le délai d'avant, qui était fixe) :
rien de modifié ni de perdu dans les données."""
import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("parametres", "0023_texte_confidentialite"),
    ]

    operations = [
        migrations.AddField(
            model_name="instance",
            name="corbeille_jours",
            field=models.PositiveSmallIntegerField(
                default=30,
                help_text="Un export, une liste de KPI ou une vue supprimés restent restaurables ce nombre de jours, puis sont effacés.",
                validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(365)],
                verbose_name="jours dans la corbeille",
            ),
        ),
    ]
