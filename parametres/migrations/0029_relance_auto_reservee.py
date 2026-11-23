"""Relances automatiques : jour réservé par le dernier envoi (Instance.derniere_relance_auto), pour que deux
planificateurs lancés en même temps n'envoient qu'une fois. Ajout d'un champ vide, sans perte (une base par espace)."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("parametres", "0028_nom_probant"),
    ]

    operations = [
        migrations.AddField(
            model_name="instance",
            name="derniere_relance_auto",
            field=models.DateField(
                blank=True,
                editable=False,
                null=True,
                verbose_name="dernier jour de relances automatiques",
            ),
        ),
    ]
