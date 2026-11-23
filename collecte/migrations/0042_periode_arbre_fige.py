"""Arbre des organisations gardé à chaque clôture (règle du projet). Ajout sans perte d'une colonne :

- ``Periode.arbre_fige`` (vide par défaut) : pour chaque organisation existante à la clôture de la période, son parent,
  son niveau, son état (active, date de désactivation, date d'ouverture). Posé par l'outil à la clôture, jamais par
  cette migration ; les exercices déjà clos le reçoivent par le travail après mise à jour posé par ``0043`` (arbre du
  jour de la mise à jour : aucun chiffre ne change). Vide : arbre d'aujourd'hui (comme avant).

Retour arrière : la colonne est retirée ; un exercice rouvert « en gardant les chiffres » se calcule de nouveau avec
l'arbre d'aujourd'hui (comportement de la version précédente).
"""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("collecte", "0041_geler_perimetres_clos"),
    ]

    operations = [
        migrations.AddField(
            model_name="periode",
            name="arbre_fige",
            field=models.JSONField(blank=True, null=True, verbose_name="arbre des organisations à la clôture"),
        ),
    ]
