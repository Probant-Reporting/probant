"""Phase 5b (2/3) : une période annuelle par exercice (1er janvier – 31 décembre, libellé « 2026 ») ; chaque campagne
devient la campagne de cette période pour le premier référentiel (« Reporting RSE <structure> », créé s'il n'existe
pas) ; chaque réponse prend la période de sa campagne. Statuts, dates, seuils, valeurs, preuves et alertes inchangés."""
import datetime

from django.db import migrations
from django.db.models import OuterRef, Subquery


def remplir(apps, schema_editor):
    Campagne = apps.get_model("collecte", "Campagne")
    Periode = apps.get_model("collecte", "Periode")
    Reponse = apps.get_model("collecte", "Reponse")
    Referentiel = apps.get_model("referentiel", "Referentiel")
    Instance = apps.get_model("parametres", "Instance")
    if not Campagne.objects.exists():
        return
    ref = (Referentiel.objects.filter(actif=True).order_by("ordre", "code").first()
           or Referentiel.objects.order_by("ordre", "code").first())
    if ref is None:
        i = Instance.objects.filter(pk=1).first()
        nom = getattr(i, "nom", "") or ""
        ref = Referentiel.objects.create(code="RSE", nom=f"Reporting RSE {nom}".strip(), ordre=1,
                                         couleur=getattr(i, "couleur_principale", "") or "#1F5FAD")
    for c in Campagne.objects.all():
        p, _ = Periode.objects.get_or_create(type="annee", debut=datetime.date(c.exercice, 1, 1),
                                             defaults={"fin": datetime.date(c.exercice, 12, 31), "libelle": str(c.exercice)})
        c.periode, c.referentiel = p, ref
        c.save(update_fields=["periode", "referentiel"])
    Reponse.objects.update(periode=Subquery(Campagne.objects.filter(pk=OuterRef("campagne_id")).values("periode")[:1]))


def vider(apps, schema_editor):
    Campagne = apps.get_model("collecte", "Campagne")
    Reponse = apps.get_model("collecte", "Reponse")
    Reponse.objects.update(periode=None)
    Campagne.objects.update(periode=None, referentiel=None)


class Migration(migrations.Migration):
    dependencies = [("collecte", "0013_periodes"), ("parametres", "0006_retrait_glossaire")]

    operations = [migrations.RunPython(remplir, vider)]
