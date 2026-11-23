"""Date d'ouverture d'une organisation (règle du projet) : « un site ne compte qu'à partir de
cette date ». Ajout sans perte : une colonne facultative, vide pour toutes les organisations existantes (vide = ouverte
depuis toujours : les calculs, la saisie et les exports ne changent pas tant qu'un administrateur ne pose pas de date).
Aucune date n'est devinée.

Retour arrière : la colonne est retirée (les dates posées depuis sont perdues, rien d'autre).
"""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("referentiel", "0018_dates_version"),
    ]

    operations = [
        migrations.AddField(
            model_name="organisation",
            name="date_ouverture",
            field=models.DateField(blank=True, null=True, verbose_name="ouverte depuis"),
        ),
    ]
