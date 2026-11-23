"""Arbre des organisations des exercices déjà clos (règle du projet, ``collecte.calcul.arbre_fige``).

Personne ne connaît l'arbre de l'époque d'un exercice clos avant cette version : il est noté une fois, tel qu'il est le
jour de la mise à jour, pour chaque période close (toutes ses campagnes clôturées) ou rouverte en gardant les chiffres de
l'époque. Rien n'est recalculé : aucun chiffre ne change. Une migration n'appelle pas le moteur de calcul : elle pose le
travail, fait à la fin de « migrate » avec le code installé (``collecte.mise_a_jour``, code « noter_arbres »).

Retour arrière : rien à défaire (la colonne de ``0042`` est retirée avec elle).
"""
from django.db import migrations

MOTIF = "arbre des organisations des exercices clos noté (celui du jour de la mise à jour)."


def poser(apps, schema_editor):
    apps.get_model("referentiel", "TravailApresMiseAJour").objects.update_or_create(code="noter_arbres",
                                                                                  defaults={"motif": MOTIF})


class Migration(migrations.Migration):
    dependencies = [
        ("collecte", "0042_periode_arbre_fige"),
        ("referentiel", "0016_na_compte_zero_entiers"),
    ]

    operations = [migrations.RunPython(poser, migrations.RunPython.noop)]
