# Prise IA et KPI sensibles (règle du projet, docs/ai_socket.md) : réglage de l'espace, éteint par
# défaut ; une installation mise à jour le reçoit éteint (rien d'un KPI « Restreint » ou « Confidentiel » ne part plus).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("parametres", "0036_traductions_de_depart_sept_langues"),
    ]

    operations = [
        migrations.AddField(
            model_name="instance",
            name="ia_kpi_sensibles",
            field=models.BooleanField(default=False, verbose_name="KPI sensibles envoyés à l'assistant IA"),
        ),
    ]
