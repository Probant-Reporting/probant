"""Dates de la version d'un référentiel (règle du projet) : date du contenu de la version et date de la
dernière installation ou mise à jour depuis la bibliothèque ou un fichier. Ajout sans perte : deux colonnes vides, puis
reprise de ce que l'on sait déjà :

- installé ou mis à jour le : la dernière entrée du journal qui dit qu'un fichier référentiel a été importé ou un modèle de
  la bibliothèque installé (référentiels importés ou fournis seulement) ;
- date de la version : pour un modèle de la bibliothèque installé dans la même version que celle fournie avec l'outil, la
  date de cette version (fichier JSON de la bibliothèque, lu une seule fois ici).
"""
import datetime
import json
from pathlib import Path

from django.db import migrations, models

BIBLIOTHEQUE = Path(__file__).resolve().parent.parent / "bibliotheque"


def dates_fournies():
    """{identifiant: (version, date)} des modèles de la bibliothèque ; {} si un fichier est illisible."""
    sortie = {}
    for chemin in sorted(BIBLIOTHEQUE.glob("*.json")):
        try:
            r = json.loads(chemin.read_text(encoding="utf-8")).get("referentiel") or {}
            sortie[str(r.get("identifiant"))] = (str(r.get("version") or ""), datetime.date.fromisoformat(r["date_version"]))
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
    return sortie


def reprendre(apps, schema_editor):
    Referentiel = apps.get_model("referentiel", "Referentiel")
    Journal = apps.get_model("collecte", "Journal")
    fournies = dates_fournies()
    for ref in Referentiel.objects.exclude(origine="cree"):
        changes = []
        derniere = (Journal.objects.filter(objet="Referentiel", objet_id=ref.pk, action="import_paquet").order_by("-date").first()
                    or Journal.objects.filter(objet="Referentiel", objet_id=ref.pk, action="reglage_referentiels",
                                              champ="référentiel").order_by("-date").first())
        if derniere is not None:
            ref.mis_a_jour_le = derniere.date
            changes.append("mis_a_jour_le")
        version, date = fournies.get(str(ref.identifiant), ("", None))
        if ref.origine == "fourni" and date is not None and version == ref.version:
            ref.date_version = date
            changes.append("date_version")
        if changes:
            ref.save(update_fields=changes)


class Migration(migrations.Migration):

    dependencies = [
        ("referentiel", "0017_libelles_neutres"),
        ("collecte", "0034_journal_index_action_objet"),
    ]

    operations = [
        migrations.AddField(
            model_name="referentiel",
            name="date_version",
            field=models.DateField(blank=True, help_text="Date du contenu de cette version : donnée par la bibliothèque ou le fichier importé, ou posée quand la version change dans l'outil.", null=True, verbose_name="date de la version"),
        ),
        migrations.AddField(
            model_name="referentiel",
            name="mis_a_jour_le",
            field=models.DateTimeField(blank=True, help_text="Dernière installation ou mise à jour depuis la bibliothèque ou un fichier référentiel.", null=True, verbose_name="installé ou mis à jour le"),
        ),
        migrations.RunPython(reprendre, migrations.RunPython.noop),
    ]
