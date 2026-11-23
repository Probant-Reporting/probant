# Migration additive : un index du journal (filtres par exercice et par organisation de la page Journal, périmètre de
# l'auditeur), sans changement des données. Le numéro 0035 appartient à une autre migration.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("collecte", "0035_menage_mois_hors_perimetre"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="journal",
            index=models.Index(fields=["objet", "objet_id", "action", "date"], name="journal_objet_action_idx"),
        ),
    ]
