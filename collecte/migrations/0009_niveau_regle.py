"""RegleCoherence.niveau devient une référence vers les niveaux réglables (codes et données inchangés)."""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("parametres", "0003_niveaux"),
        ("collecte", "0008_ordre_modeles_export"),
    ]

    operations = [
        migrations.AlterField(
            model_name="reglecoherence",
            name="niveau",
            field=models.ForeignKey(db_column="niveau", on_delete=django.db.models.deletion.PROTECT,
                                    related_name="regles", to="parametres.niveauhierarchique", verbose_name="niveau de contrôle"),
        ),
    ]
