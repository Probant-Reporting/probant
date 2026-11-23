"""Rôles qui peuvent répondre « N/A », réglables dans Paramètres › Seuils de suivi. Une colonne
ajoutée, avec tous les rôles qui saisissent (le comportement d'avant) : rien de modifié ni de perdu dans les données."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("parametres", "0024_corbeille_jours"),
    ]

    operations = [
        migrations.AddField(
            model_name="instance",
            name="na_roles",
            field=models.CharField(
                default="admin,validateur,contributeur",
                help_text="Codes de rôle séparés par des virgules ; l'administrateur peut toujours répondre N/A.",
                max_length=60,
                verbose_name="rôles qui peuvent répondre N/A",
            ),
        ),
    ]
