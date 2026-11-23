"""Logo rangé dans fichiers/reglages/logo/ (rangement). Le fichier lui-même est déplacé par la
migration collecte/0029, avec les preuves."""

import parametres.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("parametres", "0017_relance_par_langue"),
    ]

    operations = [
        migrations.AlterField(
            model_name="instance",
            name="logo",
            field=models.FileField(
                blank=True,
                upload_to="reglages/logo/",
                validators=[parametres.models.valider_logo],
            ),
        ),
    ]
