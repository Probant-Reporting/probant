"""Un exercice clos ne reçoit aucune case pour un KPI ajouté depuis
(``collecte.calcul.perimetre_gele``). Le périmètre d'une période est désormais noté à sa première clôture ; pour les
périodes déjà closes d'une installation mise à jour, il est noté une fois, tel qu'elles le demandent aujourd'hui (les
KPI de leurs référentiels et ceux qui y ont une case) : aucun chiffre ne change, aucune case n'est retirée.

Aucune table ne change. Une migration n'appelle pas le moteur de calcul : elle pose le travail, fait à la fin de
« migrate » avec le code installé (``collecte.mise_a_jour``, code « geler_perimetres »).

Retour arrière : rien à défaire (un périmètre noté ne retire rien ; l'ancienne version l'ignorait jusqu'à une réouverture).
"""
from django.db import migrations

MOTIF = "périmètre des exercices clos noté (un KPI ajouté depuis n'y crée plus de case)."


def poser(apps, schema_editor):
    apps.get_model("referentiel", "TravailApresMiseAJour").objects.update_or_create(code="geler_perimetres",
                                                                                  defaults={"motif": MOTIF})


class Migration(migrations.Migration):
    dependencies = [
        ("collecte", "0040_alertes_calcul_recomposables"),
        ("referentiel", "0016_na_compte_zero_entiers"),
    ]

    operations = [migrations.RunPython(poser, migrations.RunPython.noop)]
