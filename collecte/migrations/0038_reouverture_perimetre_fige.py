"""Réouverture d'un exercice passé (règles du projet). Ajout sans perte de deux colonnes :

- ``Campagne.chiffres_gardes`` (faux par défaut) : la campagne a été rouverte en gardant les chiffres de l'époque ;
  remis à faux à la clôture suivante. Toutes les campagnes existantes : faux (comportement d'avant).
- ``Periode.perimetre_fige`` (vide par défaut) : KPI qui avaient une case dans la période à sa première réouverture
  après une clôture ; posé par l'outil à la réouverture, jamais par cette migration. Toutes les périodes existantes :
  vide (périmètre d'aujourd'hui, comme avant).

Retour arrière : les deux colonnes sont retirées ; une campagne rouverte « en gardant les chiffres » redevient une
campagne rouverte ordinaire (recalculée au prochain recalcul).
"""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("collecte", "0037_exports_arriere_plan"),
    ]

    operations = [
        migrations.AddField(
            model_name="campagne",
            name="chiffres_gardes",
            field=models.BooleanField(default=False, verbose_name="réouverte en gardant les chiffres de l'époque"),
        ),
        migrations.AddField(
            model_name="periode",
            name="perimetre_fige",
            field=models.JSONField(blank=True, null=True, verbose_name="périmètre gelé à la réouverture"),
        ),
    ]
