"""Règles de calcul corrigées (``collecte.calcul``). Aucune table ne change.

- Cumul d'une période longue depuis les mois : seulement les mois où l'organisation est ouverte et où le KPI est demandé
  (``Calculateur.case_courte``) ; un site fermé qui a saisi dans les mois compte dans le total de son pays
  (``avec_valeurs_courtes``).
- Formule d'une autre période ([X@N-1]…) : rien ne se lit pour une organisation qui n'y est pas ouverte
  (``Calculateur.lisible``).

Les cases déjà écrites des campagnes non clôturées restent celles de l'ancienne règle jusqu'à leur prochain recalcul
complet (une saisie ne refait que les organisations touchées). La migration pose donc le recalcul des campagnes non
clôturées, fait à la fin de « migrate » avec le code installé (même méthode que ``collecte/0039``).

Exercices clos, et exercices rouverts en gardant les chiffres de l'époque : rien n'y change, aucun chiffre publié ne
bouge (le recalcul ne les touche pas). La nouvelle règle s'y applique seulement à une correction (organisation corrigée
et ses totaux) ou à une réouverture « recalculer avec l'organisation d'aujourd'hui ».

Retour arrière : rien à défaire (un recalcul complet avec l'ancienne version réécrit les cases avec l'ancienne règle).
"""
from django.db import migrations

MOTIF = ("calculs des campagnes non clôturées refaits (cumul des mois : seulement les mois où l'organisation est ouverte "
         "et le KPI demandé ; [X@N-1] d'une organisation pas ouverte : source manquante).")


def poser_recalcul(apps, schema_editor):
    apps.get_model("referentiel", "TravailApresMiseAJour").objects.update_or_create(code="recalcul",
                                                                                  defaults={"motif": MOTIF})


class Migration(migrations.Migration):
    dependencies = [
        ("collecte", "0044_corriger_unites_mal_rapprochees"),
        ("referentiel", "0016_na_compte_zero_entiers"),  # table des travaux après une mise à jour
    ]

    operations = [migrations.RunPython(poser_recalcul, migrations.RunPython.noop)]
