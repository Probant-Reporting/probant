"""Vue d'accueil de la Visualisation par rôle (admin RSE, validateurs, contributeurs, lecteurs, auditeurs), sans perte.

Avant : une seule vue partagée « vue d'accueil pour tous » (VueVisu.accueil). Après : une vue d'accueil par rôle
(AccueilVisu, une ligne par rôle). La vue d'accueil pour tous d'une installation existante devient celle des 5 rôles :
rien ne change à l'écran tant que l'admin ne règle rien.

Retour arrière : le champ « accueil » revient, posé sur la vue d'accueil du plus grand nombre de rôles (à égalité, celle
des lecteurs, puis la plus ancienne) ; c'est la seule chose que l'ancien format sait garder.
"""
from collections import Counter

import django.db.models.deletion
from django.db import migrations, models

ROLES = ["admin", "validateur", "contributeur", "lecteur", "auditeur"]  # figé ici (Utilisateur.Role)


def vers_les_roles(apps, schema_editor):
    VueVisu = apps.get_model("collecte", "VueVisu")
    AccueilVisu = apps.get_model("collecte", "AccueilVisu")
    vue = VueVisu.objects.filter(accueil=True).order_by("pk").first()
    if vue is not None:
        for role in ROLES:
            AccueilVisu.objects.update_or_create(role=role, defaults={"vue": vue})


def vers_une_vue(apps, schema_editor):
    VueVisu = apps.get_model("collecte", "VueVisu")
    AccueilVisu = apps.get_model("collecte", "AccueilVisu")
    roles = dict(AccueilVisu.objects.values_list("role", "vue_id"))
    if not roles:
        return
    compte = Counter(roles.values())
    vue_id = max(compte, key=lambda i: (compte[i], i == roles.get("lecteur"), -i))
    VueVisu.objects.filter(accueil=True).update(accueil=False)
    VueVisu.objects.filter(pk=vue_id).update(accueil=True)


class Migration(migrations.Migration):

    dependencies = [
        ("collecte", "0023_tableaux_en_vues"),
    ]

    operations = [
        migrations.CreateModel(
            name="AccueilVisu",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(max_length=20, unique=True, verbose_name="rôle")),
                ("vue", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="accueils", to="collecte.vuevisu")),
            ],
            options={
                "verbose_name": "vue d'accueil d'un rôle",
                "verbose_name_plural": "vues d'accueil des rôles",
                "ordering": ["role"],
            },
        ),
        migrations.RunPython(vers_les_roles, vers_une_vue),
        migrations.RemoveConstraint(
            model_name="vuevisu",
            name="vue_accueil_unique",
        ),
        migrations.RemoveField(
            model_name="vuevisu",
            name="accueil",
        ),
    ]
