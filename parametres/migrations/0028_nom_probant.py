"""Nom de l'outil par défaut : « Probant ».

Ce nom est le défaut dès ``0001_instance`` : la ligne de l'instance d'une base neuve le reçoit à sa création
(``0002_identite``). Cette migration ne fait que poser le défaut du modèle ; elle ne change aucune donnée, dans un sens
comme dans l'autre, et un nom choisi par un administrateur n'est jamais touché."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("parametres", "0027_categories_traduites"),
    ]

    operations = [
        migrations.AlterField(
            model_name="instance",
            name="titre",
            field=models.CharField(
                default="Probant",
                help_text="Affiché en haut à gauche et dans l'onglet du navigateur.",
                max_length=60,
                verbose_name="nom de l'outil",
            ),
        ),
    ]
