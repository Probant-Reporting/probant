"""Langues des contenus : nom_fr devient le nom de référence (libelle), nom_en une traduction anglaise ; chaque description
porte sa langue (celle de référence pour les textes existants). Aucun texte n'est perdu."""
from django.db import migrations, models


def ref(apps):
    i = apps.get_model("parametres", "Instance").objects.filter(pk=1).first()
    return (i.langue_reference if i else "") or "fr"


def noms_en_traductions(apps, schema_editor):
    """nom_en → traductions["en"]["libelle"] ; si la référence est l'anglais, nom_en devient le nom de référence."""
    KPI = apps.get_model("referentiel", "KPI")
    r = ref(apps)
    modifies = []
    for k in KPI.objects.exclude(nom_en=""):
        if r == "en":
            if k.libelle:
                k.traductions = {"fr": {"libelle": k.libelle}}
            k.libelle = k.nom_en
        else:
            k.traductions = {"en": {"libelle": k.nom_en}}
        modifies.append(k)
    KPI.objects.bulk_update(modifies, ["libelle", "traductions"], batch_size=500)


def descriptions_en_reference(apps, schema_editor):
    r = ref(apps)
    if r != "fr":
        apps.get_model("referentiel", "Description").objects.update(langue=r)


class Migration(migrations.Migration):

    dependencies = [
        ("parametres", "0005_langues"),
        ("referentiel", "0004_fiche_kpi"),
    ]

    operations = [
        migrations.AlterField(
            model_name="utilisateur",
            name="langue",
            field=models.CharField(blank=True, default="", max_length=10,
                                   help_text="Langue des contenus (noms des KPI, descriptions…) ; vide = langue par défaut de l'installation."),
        ),
        migrations.RenameField(model_name="kpi", old_name="nom_fr", new_name="libelle"),
        migrations.AlterField(
            model_name="kpi",
            name="libelle",
            field=models.CharField(blank=True, max_length=300, verbose_name="nom",
                                   help_text="Nom dans la langue de référence ; les autres langues sont dans les traductions."),
        ),
        migrations.AddField(
            model_name="kpi",
            name="traductions",
            field=models.JSONField(blank=True, default=dict, help_text="{langue: {champ: texte}}, hors langue de référence"),
        ),
        migrations.RunPython(noms_en_traductions, migrations.RunPython.noop),
        migrations.RemoveField(model_name="kpi", name="nom_en"),
        migrations.RemoveConstraint(model_name="description", name="description_unique"),
        migrations.AddField(
            model_name="description",
            name="langue",
            field=models.CharField(default="fr", max_length=10),
        ),
        migrations.RunPython(descriptions_en_reference, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="description",
            constraint=models.UniqueConstraint(fields=("kpi", "categorie", "langue"), name="description_unique"),
        ),
    ]
