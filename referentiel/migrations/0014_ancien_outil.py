"""Migration vide, gardée pour que l'historique des migrations reste le même : elle servait à renommer un libellé de
source dans les données d'une installation précise et ne fait plus rien. Aucune valeur, aucun KPI n'est touché."""
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("referentiel", "0013_organisation_code_unique")]
    operations = []
