"""Types de réponse simplifiés : les formats « Nombre entier » et « Montant » et la devise disparaissent, l'unité les porte.

Sans perte pour les KPI existants :
- « Nombre entier » → « Nombre » ; chaque KPI concerné prend une unité « entière » (case Entier cochée) : son unité si elle
  n'est utilisée que par des KPI entiers, sinon une copie entière de son unité (même symbole), ou l'unité « nombre » s'il
  n'en avait pas ;
- « Montant » → « Nombre » ; un KPI sans unité prend l'unité de la devise (« € » si vide), créée dans la thématique Monnaie
  si besoin ; un KPI qui avait déjà une unité la garde (c'était déjà elle qui s'affichait).
"""
from django.db import migrations, models


def _code_libre(Unite, base):
    code, i = base[:56], 2
    while Unite.objects.filter(code=code).exists():
        code, i = f"{base[:56]}~{i}", i + 1
    return code


def _ordre(Unite):
    return (Unite.objects.order_by("-ordre").values_list("ordre", flat=True).first() or 0) + 1


def convertir(apps, schema_editor):
    TypeReponse, KPI, Unite = apps.get_model("parametres", "TypeReponse"), apps.get_model("referentiel", "KPI"), apps.get_model("parametres", "Unite")

    def unite_entiere(u):
        if u is None:
            v = Unite.objects.filter(symbole__iexact="nombre", entier=True).first()
            return v or Unite.objects.create(code=_code_libre(Unite, "nombre"), symbole="nombre", libelle="nombre", entier=True,
                                             decimales=0, famille="Comptages", ordre=_ordre(Unite))
        if u.entier:
            return u
        if not KPI.objects.filter(unite=u).exclude(type_reponse__format="entier").exists():
            u.entier, u.decimales = True, 0
            u.save(update_fields=["entier", "decimales"])
            return u
        v = Unite.objects.filter(symbole=u.symbole, entier=True).first()
        return v or Unite.objects.create(code=_code_libre(Unite, f"{u.code}~entier"), symbole=u.symbole, libelle=u.libelle, entier=True,
                                         decimales=0, famille=u.famille, traductions=u.traductions, ordre=_ordre(Unite))

    for t in TypeReponse.objects.filter(format="entier"):
        for k in KPI.objects.filter(type_reponse=t).select_related("unite"):
            k.unite, k.decimales = unite_entiere(k.unite), 0
            k.save(update_fields=["unite", "decimales"])
        t.format = "nombre"
        t.save(update_fields=["format"])
    for t in TypeReponse.objects.filter(format="montant"):
        devise = (t.devise or "€").strip()
        kpis = KPI.objects.filter(type_reponse=t, unite__isnull=True)
        if kpis.exists():
            u = Unite.objects.filter(symbole=devise).first() or Unite.objects.create(
                code=_code_libre(Unite, devise), symbole=devise, libelle=devise, famille="Monnaie", decimales=0, ordre=_ordre(Unite))
            kpis.update(unite=u)
        t.format = "nombre"
        t.save(update_fields=["format"])


class Migration(migrations.Migration):
    dependencies = [("parametres", "0010_thematique_pourcentage"), ("referentiel", "0009_versions_referentiels")]
    operations = [
        migrations.RunPython(convertir, migrations.RunPython.noop),
        migrations.RemoveField(model_name="typereponse", name="devise"),
        migrations.AlterField(model_name="typereponse", name="format", field=models.CharField(
            choices=[("nombre", "Nombre"), ("pourcentage", "Pourcentage"), ("oui_non", "Oui / non"), ("liste", "Liste de choix")],
            default="nombre", max_length=12)),
    ]
