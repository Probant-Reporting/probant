"""Conservation des preuves des KPI sensibles : durée en mois (Instance.preuves_sensibles_mois), vide par défaut = aucune
durée, aucune preuve proposée à la suppression. Ajout d'un champ vide, sans perte (une base par espace)."""
import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("parametres", "0030_tableau_colonnes"),
    ]

    operations = [
        migrations.AddField(
            model_name="instance",
            name="preuves_sensibles_mois",
            field=models.PositiveSmallIntegerField(
                blank=True,
                help_text="Vide : pas de durée, aucune preuve n'est proposée à la suppression.",
                null=True,
                validators=[
                    django.core.validators.MinValueValidator(1),
                    django.core.validators.MaxValueValidator(240),
                ],
                verbose_name="durée de conservation des preuves des KPI sensibles (mois)",
            ),
        ),
    ]
