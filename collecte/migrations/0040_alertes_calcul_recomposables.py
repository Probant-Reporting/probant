"""Alertes « calcul impossible » recomposables dans la langue de la personne qui lit.

Pour chaque alerte « calcul impossible » enregistrée avant : le motif (texte écrit par le calcul dans la langue de
l'installation) est relu pour retrouver la clé de son libellé et ses paramètres (``textes["message"]``), et son empreinte
devient celle de la clé et des paramètres (indépendante de la langue). Sans cela, le premier contrôle après la mise à jour
verrait une empreinte changée et rouvrirait les alertes ignorées. Rien d'autre ne change : ni le statut, ni la
justification, ni le texte enregistré, ni la date de mise à jour (mise à jour en base, sans ``save``). Un motif qui ne
vient d'aucun libellé connu garde son texte et son empreinte. Sans retour arrière nécessaire : le code d'avant lit les
mêmes champs (le texte enregistré reste)."""
from django.db import migrations


def langue_installation(apps):
    Instance = apps.get_model("parametres", "Instance")
    i = Instance.objects.filter(pk=1).values("langue", "langue_reference").first() or {}
    from django.conf import settings

    return i.get("langue") or i.get("langue_reference") or settings.LANGUE_PAR_DEFAUT


def convertir(apps, schema_editor):
    from collecte.coherence import empreinte_calcul, spec_texte

    Alerte = apps.get_model("collecte", "Alerte")
    langue = langue_installation(apps)
    for pk, message, empreinte, textes in Alerte.objects.filter(controle="calcul").values_list(
            "pk", "message", "empreinte", "textes").iterator():
        if not message or empreinte != message[:200] or (textes or {}).get("message"):
            continue  # motif par défaut, déjà converti, ou empreinte d'un autre format : rien à faire
        try:
            spec = spec_texte(message, langue)
        except Exception:  # noqa: BLE001 - jamais d'échec de mise à jour pour un texte : l'alerte reste comme avant
            spec = None
        if spec is None:
            continue
        Alerte.objects.filter(pk=pk).update(textes={**(textes or {}), "message": spec}, empreinte=empreinte_calcul(spec))


class Migration(migrations.Migration):
    dependencies = [
        ("collecte", "0039_menage_periodes_hors_perimetre"),
        ("parametres", "0034_exports_arriere_plan"),
    ]

    operations = [migrations.RunPython(convertir, migrations.RunPython.noop)]
