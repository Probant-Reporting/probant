"""Phase 5b (3/3) : la réponse est unique par KPI × organisation × période (la campagne n'en fait plus partie) ;
une campagne par référentiel et période ; plusieurs campagnes peuvent être ouvertes en même temps."""
import django.db.models.deletion
from django.db import migrations, models
from django.db.models import OuterRef, Subquery


def campagnes_des_reponses(apps, schema_editor):
    """Retour arrière : chaque réponse reprend la campagne de sa période (premier référentiel)."""
    Campagne = apps.get_model("collecte", "Campagne")
    Reponse = apps.get_model("collecte", "Reponse")
    Reponse.objects.update(campagne=Subquery(Campagne.objects.filter(periode=OuterRef("periode_id"))
                                             .order_by("referentiel__ordre", "referentiel_id").values("pk")[:1]))


class Migration(migrations.Migration):
    dependencies = [("collecte", "0014_periodes_donnees")]

    operations = [
        migrations.AlterField(
            model_name="reponse", name="campagne",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name="reponses",
                                    to="collecte.campagne"),
        ),
        migrations.RunPython(migrations.RunPython.noop, campagnes_des_reponses),
        migrations.RemoveConstraint(model_name="reponse", name="reponse_unique"),
        migrations.RemoveIndex(model_name="reponse", name="collecte_re_campagn_f938fd_idx"),
        migrations.RemoveField(model_name="reponse", name="campagne"),
        migrations.AlterField(
            model_name="reponse", name="periode",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="reponses", to="collecte.periode",
                                    verbose_name="période"),
        ),
        migrations.AddConstraint(model_name="reponse",
                                 constraint=models.UniqueConstraint(fields=("periode", "kpi", "organisation"), name="reponse_unique")),
        migrations.AddIndex(model_name="reponse", index=models.Index(fields=["periode", "kpi"], name="reponse_periode_kpi")),
        migrations.AlterField(
            model_name="reponse", name="origine",
            field=models.CharField(choices=[("saisie", "Saisie"), ("import", "Import"), ("calcul", "Calcul"), ("agregation", "Agrégation"),
                                            ("cumul", "Cumul des périodes")], default="saisie", max_length=10),
        ),
        migrations.RemoveField(model_name="campagne", name="date_fin_exercice"),
        migrations.AlterField(
            model_name="campagne", name="exercice",
            field=models.PositiveIntegerField(help_text="Exercice de la période (année où il commence)."),
        ),
        migrations.AlterField(
            model_name="campagne", name="referentiel",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="campagnes",
                                    to="referentiel.referentiel", verbose_name="référentiel"),
        ),
        migrations.AlterField(
            model_name="campagne", name="periode",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="campagnes", to="collecte.periode",
                                    verbose_name="période"),
        ),
        migrations.AddConstraint(model_name="campagne",
                                 constraint=models.UniqueConstraint(fields=("referentiel", "periode"), name="campagne_unique")),
        migrations.AlterModelOptions(name="campagne", options={"ordering": ["referentiel__ordre", "referentiel_id", "-periode__debut"]}),
    ]
