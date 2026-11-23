"""Empreinte du mot de passe du propriétaire gardée avec chaque jeton (un mot de passe changé rend le jeton invalide).
Sans perte : les jetons existants reçoivent l'empreinte du mot de passe actuel de leur propriétaire (ils restent valides
jusqu'au prochain changement)."""
import hashlib

from django.db import migrations, models


def remplir(apps, schema_editor):
    JetonMCP = apps.get_model("serveur_mcp", "JetonMCP")
    alias = schema_editor.connection.alias
    for j in JetonMCP.objects.using(alias).select_related("utilisateur"):
        j.mdp_empreinte = hashlib.sha256(("probant-mcp-mdp:" + (j.utilisateur.password or "")).encode("utf-8")).hexdigest()
        j.save(update_fields=["mdp_empreinte"])


class Migration(migrations.Migration):
    dependencies = [("serveur_mcp", "0001_initial")]

    operations = [
        migrations.AddField(model_name="jetonmcp", name="mdp_empreinte",
                            field=models.CharField(blank=True, default="", max_length=64)),
        migrations.RunPython(remplir, migrations.RunPython.noop),
    ]
