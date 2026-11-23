"""KPI qualitatifs : 5e format de réponse « texte rédigé » (Markdown), et un type de réponse
« Texte rédigé » fourni (libellé en français, anglais et espagnol), créé s'il n'existe encore aucun type de ce format.

Sans perte : aucun KPI, aucune réponse ne change ; la réponse rédigée se range dans ``Reponse.texte`` (champ texte sans
limite de taille, déjà là pour les oui / non et les listes). Le libellé du type est dans la langue de référence de
l'installation (français par défaut) ; les autres langues sont ses traductions. Retour arrière : le type est retiré s'il
n'est utilisé par aucun KPI (sinon il reste, et le retour arrière est refusé : des réponses rédigées seraient perdues)."""
from django.db import migrations, models

LIBELLES = {"fr": "Texte rédigé", "en": "Written text", "es": "Texto redactado"}  # comme parametres.referentiel.TYPES_REPONSE
CODE = "TexteRedige"


def _code_libre(TypeReponse):
    code, i = CODE, 2
    while TypeReponse.objects.filter(code=code).exists():
        code, i = f"{CODE}{i}", i + 1
    return code


def creer(apps, schema_editor):
    TypeReponse, Instance = apps.get_model("parametres", "TypeReponse"), apps.get_model("parametres", "Instance")
    if TypeReponse.objects.filter(format="texte").exists():
        return
    instance = Instance.objects.first()
    ref = (getattr(instance, "langue_reference", None) or "fr").split("-")[0]
    libelle = LIBELLES.get(ref, LIBELLES["fr"])
    traductions = {lg: {"libelle": t} for lg, t in LIBELLES.items() if lg != ref}
    ordre = (TypeReponse.objects.order_by("-ordre").values_list("ordre", flat=True).first() or 0) + 1
    TypeReponse.objects.create(code=_code_libre(TypeReponse), libelle=libelle, format="texte", ordre=ordre, traductions=traductions)


def retirer(apps, schema_editor):
    TypeReponse, KPI = apps.get_model("parametres", "TypeReponse"), apps.get_model("referentiel", "KPI")
    if KPI.objects.filter(type_reponse__format="texte").exists():
        raise RuntimeError("Some KPIs use the 'written text' format: going back would lose their answers.")
    TypeReponse.objects.filter(format="texte").delete()


class Migration(migrations.Migration):
    dependencies = [("parametres", "0019_logo_settings"), ("referentiel", "0017_libelles_neutres")]
    operations = [
        migrations.AlterField(model_name="typereponse", name="format", field=models.CharField(
            choices=[("nombre", "Nombre"), ("pourcentage", "Pourcentage"), ("oui_non", "Oui / non"), ("liste", "Liste de choix"),
                     ("texte", "Texte rédigé")],
            default="nombre", max_length=12)),
        migrations.RunPython(creer, retirer),
    ]
