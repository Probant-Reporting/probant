"""Valeurs forcées des KPI calculés : origine « Valeur forcée » des réponses et table des demandes (faites par le
responsable du résultat, acceptées par l'administrateur ou un validateur). Ajout seulement : rien d'existant ne change."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("collecte", "0027_comptages_decimaux"),
        ("referentiel", "0017_libelles_neutres"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="reponse",
            name="origine",
            field=models.CharField(
                choices=[
                    ("saisie", "Saisie"),
                    ("import", "Import"),
                    ("calcul", "Calcul"),
                    ("agregation", "Agrégation"),
                    ("cumul", "Cumul des périodes"),
                    ("forcee", "Valeur forcée"),
                ],
                default="saisie",
                max_length=10,
            ),
        ),
        migrations.CreateModel(
            name="DemandeForcage",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "valeur",
                    models.DecimalField(
                        blank=True, decimal_places=10, max_digits=30, null=True
                    ),
                ),
                (
                    "non_applicable",
                    models.BooleanField(default=False, verbose_name="N/A"),
                ),
                ("justification", models.TextField()),
                (
                    "valeur_calculee",
                    models.DecimalField(
                        blank=True,
                        decimal_places=10,
                        help_text="Ce que donnait le calcul au moment de la demande.",
                        max_digits=30,
                        null=True,
                        verbose_name="résultat calculé",
                    ),
                ),
                (
                    "statut",
                    models.CharField(
                        choices=[
                            ("en_attente", "En attente d'accord"),
                            ("acceptee", "Acceptée"),
                            ("refusee", "Refusée"),
                            ("retiree", "Retirée"),
                            ("levee", "Levée (retour au calcul)"),
                        ],
                        default="en_attente",
                        max_length=12,
                    ),
                ),
                ("date_demande", models.DateTimeField(auto_now_add=True)),
                ("date_traitement", models.DateTimeField(blank=True, null=True)),
                (
                    "motif",
                    models.TextField(
                        blank=True, help_text="Motif du refus ou du retour au calcul."
                    ),
                ),
                (
                    "demandeur",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "kpi",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="demandes_forcage",
                        to="referentiel.kpi",
                    ),
                ),
                (
                    "organisation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="demandes_forcage",
                        to="referentiel.organisation",
                    ),
                ),
                (
                    "periode",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="demandes_forcage",
                        to="collecte.periode",
                        verbose_name="période",
                    ),
                ),
                (
                    "traite_par",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "demande de valeur forcée",
                "verbose_name_plural": "demandes de valeur forcée",
                "ordering": ["-date_demande"],
                "indexes": [
                    models.Index(
                        fields=["periode", "kpi", "organisation"], name="forcage_case"
                    ),
                    models.Index(fields=["statut"], name="forcage_statut"),
                ],
            },
        ),
    ]
