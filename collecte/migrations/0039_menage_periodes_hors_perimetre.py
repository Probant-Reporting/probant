"""La règle (« une période ne calcule que les KPI du périmètre de ses
campagnes ») vaut aussi pour les années, les semestres et les trimestres (``collecte.calcul.perimetre_calcul``). Aucune
table ne change.

Même méthode que ``collecte/0035`` (mois) : les cases déjà écrites pour des KPI hors du périmètre (le plus souvent
« incomplet ») ne sont pas effacées ici (une migration n'appelle pas le moteur de calcul). La migration pose le recalcul
des campagnes non clôturées, fait à la fin de « migrate » avec le code installé : le recalcul complet d'une période
retire ces cases comme toute case sans objet (gardée, vide, si elle porte un commentaire ou une preuve ; une saisie, une
valeur importée ou forcée n'est jamais effacée).

Exercices clos : rien n'y change. Aucune case n'y est retirée, aucun chiffre publié ne bouge ; leurs cases hors du
périmètre restent telles qu'elles ont été publiées (« check_data » les signale pour information), jusqu'à une
réouverture qui recalcule (choix « recalculer avec l'organisation d'aujourd'hui »).

Retour arrière : rien à défaire (un recalcul complet avec l'ancienne version réécrit les cases retirées).
"""
from django.db import migrations

MOTIF = ("calculs des campagnes non clôturées refaits (une année, un semestre ou un trimestre ne calcule plus que les "
         "KPI du périmètre de ses campagnes : cases sans objet retirées).")


def poser_recalcul(apps, schema_editor):
    apps.get_model("referentiel", "TravailApresMiseAJour").objects.update_or_create(code="recalcul",
                                                                                  defaults={"motif": MOTIF})


class Migration(migrations.Migration):
    dependencies = [
        ("collecte", "0038_reouverture_perimetre_fige"),
        ("referentiel", "0016_na_compte_zero_entiers"),  # table des travaux après une mise à jour
    ]

    operations = [migrations.RunPython(poser_recalcul, migrations.RunPython.noop)]
