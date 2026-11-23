"""Deux campagnes sur une même période, l'une clôturée : « Figer ses chiffres » (règle du projet).
Ajout sans perte d'une colonne :

- ``Periode.figes_partiels`` (vide par défaut) : les KPI que demande une campagne clôturée de la période alors qu'une
  autre campagne de la même période ne l'est pas, chacun avec l'arbre des organisations du jour où il a été figé. Posé
  par l'outil à la clôture d'une campagne (et tenu à jour à sa réouverture), jamais par cette migration ; les périodes
  déjà dans ce cas reçoivent le leur par le travail après mise à jour posé par ``0047`` (arbre et KPI du jour de la mise
  à jour : aucun chiffre ne change). Vide : rien n'est figé à part (comportement de la version précédente).

Retour arrière : la colonne est retirée ; les KPI d'une campagne clôturée sont de nouveau recalculés tant qu'une autre
campagne de la même période est ouverte (comportement de la version précédente).
"""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("collecte", "0045_recalcul_cumuls_mois_ouverts"),
    ]

    operations = [
        migrations.AddField(
            model_name="periode",
            name="figes_partiels",
            field=models.JSONField(blank=True, null=True, verbose_name="KPI figés par une campagne clôturée"),
        ),
    ]
