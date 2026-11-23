"""Monnaie de référence de l'espace (Paramètres › Unités et formats) : l'euro par défaut, si bien qu'aucune installation
existante ne change de comportement. Additive, sans perte."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("parametres", "0038_instance_connexions_jours"),
    ]

    operations = [
        migrations.AddField(
            model_name="instance",
            name="monnaie",
            field=models.CharField(
                default="EUR",
                help_text="Code ISO 4217 d'une monnaie de la liste de parametres/monnaies.py.",
                max_length=3,
                verbose_name="monnaie de référence",
            ),
        ),
    ]
