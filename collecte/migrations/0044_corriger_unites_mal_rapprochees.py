"""Unité des KPI rangés dans une mauvaise unité à l'installation d'un modèle de la bibliothèque (rapprochement fautif
d'avant la mise à jour : « €/h » rangée en « h » pour les rémunérations horaires du modèle VS de base), corrigée une fois
(``collecte.unites_mal_rapprochees.corriger``) : seulement les cas prouvés (version livrée du modèle, rejeu de l'ancienne
règle), une ligne d'historique par KPI, aucune valeur changée. Les autres cas douteux sont seulement signalés
(« À traiter », ``check_data``). Une migration n'appelle pas ce code : elle pose le travail, fait à la fin de « migrate »
(``collecte.mise_a_jour``, code « corriger_unites »).

Retour arrière : rien à défaire (l'unité corrigée reste, avec sa ligne d'historique).
"""
from django.db import migrations

MOTIF = "unité des KPI mal rangée à l'installation d'un modèle de la bibliothèque corrigée (aucune valeur changée)."


def poser(apps, schema_editor):
    apps.get_model("referentiel", "TravailApresMiseAJour").objects.update_or_create(code="corriger_unites",
                                                                                  defaults={"motif": MOTIF})


class Migration(migrations.Migration):
    dependencies = [
        ("collecte", "0043_noter_arbres_clos"),
        ("referentiel", "0020_element_demande_depuis"),
    ]

    operations = [migrations.RunPython(poser, migrations.RunPython.noop)]
