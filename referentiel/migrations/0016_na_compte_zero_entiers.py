"""Sans perte pour les installations existantes :

- KPI calculé : nouvelle case « Une source N/A compte comme 0 » (CALC-01). Elle est cochée pour les KPI dont la formule
  n'est qu'une somme (références, nombres, + et −, parenthèses), décochée sinon (ratios, produits, moyennes : une source
  N/A y rend toujours le résultat N/A) ;
- unité « nombre entier » (comptage) : ses KPI passent à 0 décimale (affichage seulement, aucune valeur ne change) ;
- les calculs des campagnes non clôturées sont refaits une fois, au démarrage, avec la nouvelle règle : la migration
  pose seulement le travail à faire (``TravailApresMiseAJour``) ; la fin de « migrate » le fait avec le code installé,
  quand la base est entièrement à jour (``collecte.mise_a_jour``). Les périodes clôturées restent figées.

Retour arrière : la case et la table des travaux sont retirées ; les décimales et les valeurs recalculées restent telles
quelles (rien d'autre ne change).
"""
import re

from django.db import migrations, models

REFERENCE = re.compile(r"\[[^\[\]]+\]")
SOMME = re.compile(r"^[\s0-9.+\-()]*$")  # ce qui reste d'une somme une fois les références retirées


def est_somme(formule):
    """Formule purement additive, lue sans le code de l'outil (qui peut changer d'une version à l'autre)."""
    formule = formule or ""
    return bool(REFERENCE.search(formule)) and bool(SOMME.match(REFERENCE.sub("0", formule)))


def cocher_sommes(apps, schema_editor):
    KPI = apps.get_model("referentiel", "KPI")
    calcules = set(apps.get_model("parametres", "TypeSaisie").objects.filter(comportement="calcul").values_list("code", flat=True))
    codes = [code for code, formule in KPI.objects.filter(type_saisie_id__in=calcules).exclude(formule="")
             .values_list("code", "formule") if est_somme(formule)]
    KPI.objects.filter(code__in=codes).update(na_compte_zero=True)


def entiers_sans_decimale(apps, schema_editor):
    KPI = apps.get_model("referentiel", "KPI")
    KPI.objects.filter(unite__entier=True).exclude(decimales=0).update(decimales=0)


def poser_recalcul(apps, schema_editor):
    apps.get_model("referentiel", "TravailApresMiseAJour").objects.update_or_create(
        code="recalcul", defaults={"motif": "calculs des campagnes non clôturées refaits (une source N/A compte désormais "
                                            "comme 0 dans les sommes : case de la fiche KPI)."})


class Migration(migrations.Migration):
    dependencies = [
        ("referentiel", "0015_roles_lecture_seule"),
        ("parametres", "0011_formats_simplifies"),  # unités « nombre entier » posées avant de mettre leurs KPI à 0 décimale
    ]

    operations = [
        migrations.AddField(
            model_name="kpi",
            name="na_compte_zero",
            field=models.BooleanField(
                default=False,
                help_text="KPI calculé : une source N/A (non applicable) compte comme 0, pour un total ; le résultat n'est N/A "
                          "que si toutes les sources le sont. Sinon, une source N/A rend le résultat N/A (ratios, moyennes). "
                          "Proposé coché à la création pour une formule qui n'est qu'une somme (+ et − seulement).",
                verbose_name="une source N/A compte comme 0",
            ),
        ),
        migrations.CreateModel(
            name="TravailApresMiseAJour",
            fields=[
                ("code", models.CharField(max_length=40, primary_key=True, serialize=False)),
                ("motif", models.CharField(blank=True, max_length=300)),
                ("date", models.DateTimeField(auto_now_add=True)),
            ],
            options={"verbose_name": "travail après une mise à jour", "verbose_name_plural": "travaux après une mise à jour"},
        ),
        migrations.RunPython(cocher_sommes, migrations.RunPython.noop),
        migrations.RunPython(entiers_sans_decimale, migrations.RunPython.noop),
        migrations.RunPython(poser_recalcul, migrations.RunPython.noop),
    ]
