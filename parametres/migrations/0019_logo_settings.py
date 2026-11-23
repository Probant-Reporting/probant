"""Logo rangé dans files/settings/logo/ (noms anglais). Le fichier est déplacé par collecte/0030."""

import parametres.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("parametres", "0018_logo_reglages"),
    ]

    operations = [
        migrations.AlterField(
            model_name="instance",
            name="logo",
            field=models.FileField(
                blank=True,
                upload_to="settings/logo/",
                validators=[parametres.models.valider_logo],
            ),
        ),
    ]
