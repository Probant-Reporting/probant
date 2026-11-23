"""Phase 5b : fréquence, mois de début d'exercice et comparaison des référentiels ; agrégation des KPI dans le temps.

Les référentiels existants restent annuels, exercice de janvier à décembre, comparés à N-1 (comme avant).
Agrégation dans le temps par défaut selon le type de réponse : somme pour un nombre, moyenne pour un pourcentage,
dernière valeur pour un oui / non, une liste ou un paramètre hérité (facteur d'émission). Réglable dans la fiche KPI."""
import django.core.validators
from django.db import migrations, models


def agregations_par_defaut(apps, schema_editor):
    KPI = apps.get_model("referentiel", "KPI")
    for k in KPI.objects.select_related("type_reponse", "type_saisie"):
        fmt = k.type_reponse.format if k.type_reponse_id else "nombre"
        if fmt in ("oui_non", "liste") or k.type_saisie.comportement == "herite":
            mode = "derniere"
        elif fmt == "pourcentage":
            mode = "moyenne"
        else:
            mode = "somme"
        if mode != k.agregation_temps:
            KPI.objects.filter(pk=k.pk).update(agregation_temps=mode)


class Migration(migrations.Migration):
    dependencies = [("referentiel", "0007_retrait_themes_kpi"), ("parametres", "0006_retrait_glossaire")]

    operations = [
        migrations.AddField(
            model_name="referentiel", name="frequence",
            field=models.CharField(choices=[("annee", "Annuelle"), ("semestre", "Semestrielle"), ("trimestre", "Trimestrielle"),
                                            ("mois", "Mensuelle")], default="annee",
                                   help_text="Une campagne par période : année, semestre, trimestre ou mois.",
                                   max_length=10, verbose_name="fréquence"),
        ),
        migrations.AddField(
            model_name="referentiel", name="mois_debut",
            field=models.PositiveSmallIntegerField(default=1, help_text="1 = janvier. Les semestres et trimestres en partent.",
                                                   validators=[django.core.validators.MinValueValidator(1),
                                                               django.core.validators.MaxValueValidator(12)],
                                                   verbose_name="mois de début d'exercice"),
        ),
        migrations.AddField(
            model_name="referentiel", name="comparaison",
            field=models.CharField(choices=[("N-1", "Même période de l'exercice précédent"), ("P-1", "Période précédente")],
                                   default="N-1", help_text="Valeur de référence pour l'écart affiché et les contrôles de cohérence.",
                                   max_length=3, verbose_name="comparaison"),
        ),
        migrations.AddField(
            model_name="kpi", name="agregation_temps",
            field=models.CharField(choices=[("somme", "Somme des périodes"), ("moyenne", "Moyenne des périodes"),
                                            ("derniere", "Dernière valeur"), ("aucune", "Aucune : saisie séparée à chaque fréquence")],
                                   default="somme",
                                   help_text="Si le KPI se collecte aussi plus souvent (ex. tous les mois) dans un autre référentiel : comment "
                                             "les périodes courtes donnent la valeur de la période longue (ex. l'année).",
                                   max_length=10, verbose_name="agrégation dans le temps"),
        ),
        migrations.AlterField(
            model_name="kpi", name="formule",
            field=models.TextField(blank=True, help_text="Ex. : [ACC-01] / [HEU-01] * 1000000 ; [ID@N-1] = même période l'an dernier ; "
                                                         "[ID@P-1] = période précédente"),
        ),
        migrations.RunPython(agregations_par_defaut, migrations.RunPython.noop),
    ]
