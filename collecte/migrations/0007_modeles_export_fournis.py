"""Les préréglages fournis deviennent des modèles d'export ordinaires : partagés, modifiables et supprimables."""
from django.db import migrations

FOURNIS = [
    ("Power BI – toutes les années", "Base de données Excel, tous les exercices, valeurs saisies, calculées et agrégées.",
     dict(presentation="base", format="xlsx", exercices=["tous"], contenus=["valide", "brouillon", "calcule"])),
    ("Tableau de l'exercice avec N-1", "Une ligne par KPI, une colonne par organisation, valeur N-1 à côté.",
     dict(presentation="tableau", format="xlsx", exercices=["courant"], contenus=["valide", "brouillon", "calcule"], n1=True)),
    ("Cases restant à saisir", "Ce qui manque encore pour l'exercice en cours : cases vides et brouillons.",
     dict(presentation="base", format="xlsx", exercices=["courant"], contenus=["a_saisir", "brouillon"], types=["Saisi", "FE"])),
    ("Rapport de revue de l'exercice", "Par organisation : valeur, N-1, écart, statut, commentaire, avec la synthèse.",
     dict(presentation="revue", format="xlsx", exercices=["courant"], contenus=["valide", "brouillon", "a_saisir"], types=["Saisi", "FE"])),
    ("CSV pour Power BI", "Base de données en CSV standard (séparateur virgule, point décimal), tous les exercices.",
     dict(presentation="base", format="csv", csv="intl", exercices=["tous"], contenus=["valide", "brouillon", "calcule"])),
]


def creer(apps, schema_editor):
    R = apps.get_model("collecte", "ReglageExport")
    for nom, description, parametres in FOURNIS:
        R.objects.get_or_create(nom=nom, defaults={"description": description, "parametres": parametres, "partage": True})


class Migration(migrations.Migration):
    dependencies = [("collecte", "0006_reglages_export")]
    operations = [migrations.RunPython(creer, migrations.RunPython.noop)]
