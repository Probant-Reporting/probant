"""Une période mensuelle ne calcule plus que les KPI du périmètre de ses campagnes
(``collecte.calcul.perimetre_calcul``). Aucune table ne change.

Les cases déjà écrites pour les autres KPI (le plus souvent « incomplet ») sont sans objet. Elles ne sont pas effacées
ici : une migration ne doit pas appeler le moteur de calcul (``collecte.mise_a_jour``), et le périmètre d'un mois dépend
des référentiels, des formules et des campagnes du moment. La migration pose seulement le recalcul des campagnes non
clôturées, fait à la fin de « migrate » avec le code installé : le recalcul complet d'un mois retire ces cases comme
toute case sans objet (gardée, vide, si elle porte un commentaire ou une preuve). Les mois clôturés restent figés,
tels qu'ils ont été publiés ; « check_data » y signale ces cases pour information seulement.

Retour arrière : rien à défaire (les cases retirées n'avaient aucune valeur lue ailleurs ; un recalcul complet avec
l'ancienne version les réécrit).
"""
from django.db import migrations

MOTIF = ("calculs des campagnes non clôturées refaits (un mois ne calcule plus que les KPI du périmètre de ses "
         "campagnes : cases sans objet retirées).")


def poser_recalcul(apps, schema_editor):
    apps.get_model("referentiel", "TravailApresMiseAJour").objects.update_or_create(code="recalcul",
                                                                                  defaults={"motif": MOTIF})


class Migration(migrations.Migration):
    dependencies = [
        ("collecte", "0034_journal_index_action_objet"),
        ("referentiel", "0016_na_compte_zero_entiers"),  # table des travaux après une mise à jour
    ]

    operations = [migrations.RunPython(poser_recalcul, migrations.RunPython.noop)]
