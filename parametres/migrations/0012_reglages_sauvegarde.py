"""Réglages de la sauvegarde automatique dans l'outil (Paramètres › Hébergement)."""

import os

from django.conf import settings
from django.db import migrations, models

import parametres.models


def reprendre_reglages_serveur(apps, schema_editor):
    """Une installation existante garde l'heure, le nombre d'archives et l'activation réglés par l'IT (variables
    SAUVEGARDE_HEURE, SAUVEGARDE_CONSERVER, SAUVEGARDE_AUTO) : ils deviennent les réglages de l'outil."""
    apps.get_model("parametres", "Instance").objects.update(
        sauvegarde_heure=settings.SAUVEGARDE_HEURE, sauvegarde_conserver=settings.SAUVEGARDE_CONSERVER,
        sauvegarde_auto=os.environ.get("BACKUP_AUTO", os.environ.get("SAUVEGARDE_AUTO", "1")) == "1")


class Migration(migrations.Migration):

    dependencies = [
        ("parametres", "0011_formats_simplifies"),
    ]

    operations = [
        migrations.AddField(
            model_name="instance",
            name="sauvegarde_auto",
            field=models.BooleanField(
                default=True, verbose_name="sauvegarde automatique"
            ),
        ),
        migrations.AddField(
            model_name="instance",
            name="sauvegarde_conserver",
            field=models.PositiveSmallIntegerField(
                default=parametres.models._sauvegarde_conserver_defaut,
                help_text="Au-delà, les plus anciennes sont supprimées.",
                verbose_name="sauvegardes gardées",
            ),
        ),
        migrations.AddField(
            model_name="instance",
            name="sauvegarde_frequence",
            field=models.CharField(
                choices=[
                    ("6h", "Toutes les 6 heures"),
                    ("12h", "Toutes les 12 heures"),
                    ("jour", "Chaque jour"),
                    ("semaine", "Chaque semaine"),
                ],
                default="jour",
                max_length=8,
                verbose_name="fréquence",
            ),
        ),
        migrations.AddField(
            model_name="instance",
            name="sauvegarde_heure",
            field=models.CharField(
                default=parametres.models._sauvegarde_heure_defaut,
                help_text="HH:MM : heure de la sauvegarde quotidienne, ou de la première de la journée.",
                max_length=5,
                verbose_name="heure de départ",
            ),
        ),
        migrations.RunPython(reprendre_reglages_serveur, migrations.RunPython.noop),
    ]
