"""« Demandé depuis » d'un KPI dans un référentiel (règle du projet) : « à la création d'un KPI,
demander s'il doit être ajouté aux années précédentes ; dans la gestion des KPI, pouvoir régler quels KPI sont arrivés
quand ». Ajout sans perte : une colonne facultative, vide pour tous les éléments existants (vide = demandé depuis le
début : la saisie, les calculs et les exports ne changent pas ; le périmètre noté des exercices clos reste la vérité).
Aucune date n'est devinée.

Retour arrière : la colonne est retirée (les dates posées depuis sont perdues, rien d'autre).
"""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("referentiel", "0019_organisation_date_ouverture"),
    ]

    operations = [
        migrations.AddField(
            model_name="elementreferentiel",
            name="demande_depuis",
            field=models.DateField(blank=True, null=True, verbose_name="demandé depuis"),
        ),
    ]
