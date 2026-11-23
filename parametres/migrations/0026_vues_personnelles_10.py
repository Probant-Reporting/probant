"""Vues personnelles par personne : 10 par défaut au lieu de 25.

Sans perte : une installation restée sur l'ancienne valeur par défaut (25) passe à 10 ; une installation qui a choisi
une autre valeur la garde. Aucune vue n'est touchée : une personne qui a déjà plus de vues que la limite les garde
toutes et peut les modifier ; elle ne peut plus en créer ni en dupliquer (``collecte.vues_visu.limite_vues``).
Retour arrière : les installations à 10 reviennent à 25."""
import django.core.validators
from django.db import migrations, models

ANCIEN, NOUVEAU = 25, 10


def _remplacer(avant, apres):
    def fonction(apps, schema_editor):
        Instance = apps.get_model("parametres", "Instance")
        Instance.objects.using(schema_editor.connection.alias).filter(vues_personnelles_max=avant).update(
            vues_personnelles_max=apres)
    return fonction


class Migration(migrations.Migration):

    dependencies = [
        ("parametres", "0025_na_roles"),
    ]

    operations = [
        migrations.AlterField(
            model_name="instance",
            name="vues_personnelles_max",
            field=models.PositiveSmallIntegerField(
                default=10,
                help_text="Au-delà, une personne ne peut plus créer ni dupliquer de vue (elle garde celles qu'elle a).",
                validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(500)],
                verbose_name="vues personnelles par personne",
            ),
        ),
        migrations.RunPython(_remplacer(ANCIEN, NOUVEAU), _remplacer(NOUVEAU, ANCIEN)),
    ]
