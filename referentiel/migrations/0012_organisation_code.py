"""Code d'organisation stable (exports Power BI) : ajouté vide, puis tiré du nom de chaque organisation existante."""
import re
import unicodedata

from django.db import migrations, models


def _code(texte):
    t = unicodedata.normalize("NFKD", str(texte or "")).encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z0-9_.]+", "-", t).strip("-")[:30]


def remplir(apps, schema_editor):
    Organisation = apps.get_model("referentiel", "Organisation")
    pris = set()
    for o in Organisation.objects.order_by("pk"):
        base = _code(o.nom)[:26] or "ORG"
        code, n = base, 1
        while code in pris:
            n += 1
            code = f"{base}-{n}"
        pris.add(code)
        Organisation.objects.filter(pk=o.pk).update(code=code)


class Migration(migrations.Migration):

    dependencies = [
        ("referentiel", "0011_retrait_code_dans_referentiel"),
    ]

    operations = [
        migrations.AddField(
            model_name="organisation",
            name="code",
            field=models.CharField(blank=True, default="", max_length=30, verbose_name="code"),
            preserve_default=False,
        ),
        migrations.RunPython(remplir, migrations.RunPython.noop),
    ]
