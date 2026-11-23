"""Organisation.niveau et KPI.granularite deviennent des références vers les niveaux réglables (Paramètres › Niveaux).

Les colonnes et les codes ne changent pas (Group, Country, Entity, Site) : les données restent rattachées.
Un code inconnu (base modifiée à la main) devient un niveau supplémentaire, en bas de l'arbre, plutôt que d'être perdu.
"""
import django.db.models.deletion
from django.db import migrations, models

from referentiel.migrations._cle_kpi import cle_kpi_nommee_code


def niveaux_manquants(apps, schema_editor):
    N = apps.get_model("parametres", "NiveauHierarchique")
    Organisation, KPI = apps.get_model("referentiel", "Organisation"), apps.get_model("referentiel", "KPI")
    codes = set(Organisation.objects.values_list("niveau", flat=True)) | set(KPI.objects.values_list("granularite", flat=True))
    connus = set(N.objects.values_list("code", flat=True))
    rang = N.objects.aggregate(m=models.Max("rang"))["m"] or 0
    for code in sorted(c for c in codes - connus if c):
        rang += 1
        N.objects.create(code=code, rang=rang, nom=code, nom_pluriel=code, couleur="#5A6B85",
                         couleur_fond="#E6E9EE", couleur_texte="#3F4B5E", couleur_pale="#F3F4F7")


class Migration(migrations.Migration):

    dependencies = [
        ("parametres", "0003_niveaux"),
        ("referentiel", "0002_mot_de_passe_provisoire"),
    ]

    operations = [
        migrations.RunPython(cle_kpi_nommee_code, migrations.RunPython.noop),  # base d'une version antérieure (_cle_kpi.py)
        migrations.RunPython(niveaux_manquants, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="organisation",
            name="niveau",
            field=models.ForeignKey(db_column="niveau", on_delete=django.db.models.deletion.PROTECT,
                                    related_name="organisations", to="parametres.niveauhierarchique"),
        ),
        migrations.AlterField(
            model_name="kpi",
            name="granularite",
            field=models.ForeignKey(db_column="granularite", on_delete=django.db.models.deletion.PROTECT,
                                    related_name="kpis", to="parametres.niveauhierarchique", verbose_name="granularité"),
        ),
    ]
