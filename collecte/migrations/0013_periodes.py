"""Phase 5b (1/3) : périodes ; campagnes et réponses rattachées à une période (colonnes ajoutées, encore facultatives)."""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("collecte", "0012_themes_des_modeles_export"), ("referentiel", "0008_frequences")]

    operations = [
        migrations.CreateModel(
            name="Periode",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("traductions", models.JSONField(blank=True, default=dict, help_text="{langue: {champ: texte}}, hors langue de référence")),
                ("type", models.CharField(choices=[("annee", "Annuelle"), ("semestre", "Semestrielle"), ("trimestre", "Trimestrielle"),
                                                   ("mois", "Mensuelle")], max_length=10)),
                ("debut", models.DateField(verbose_name="début")),
                ("fin", models.DateField(verbose_name="fin")),
                ("libelle", models.CharField(help_text="Ex. « 2026 », « T1 2026 », « mars 2026 ».", max_length=40, verbose_name="libellé")),
            ],
            options={"verbose_name": "période", "ordering": ["debut", "-fin"]},
        ),
        migrations.AddConstraint(model_name="periode", constraint=models.UniqueConstraint(fields=("type", "debut"), name="periode_unique")),
        migrations.AddField(
            model_name="campagne", name="referentiel",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="campagnes",
                                    to="referentiel.referentiel", verbose_name="référentiel"),
        ),
        migrations.AddField(
            model_name="campagne", name="periode",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="campagnes",
                                    to="collecte.periode", verbose_name="période"),
        ),
        migrations.AddField(
            model_name="reponse", name="periode",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="reponses",
                                    to="collecte.periode", verbose_name="période"),
        ),
    ]
