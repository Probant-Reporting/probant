"""Une unité « nombre entier » (comptage) refuse désormais une décimale à la
saisie et à l'import. Avant ce refus, rien d'existant ne doit devenir refusé ni se perdre : tout KPI qui a déjà des
réponses décimales (saisies ou importées) avec une unité entière passe sur une copie non entière de son unité (même
symbole, libellé suivi de « (décimal) »), avec assez de décimales pour afficher ses valeurs (1 ou 2). Exemple : les
des KPI « Effectif moyen » en « employees ». Les autres KPI de l'unité ne changent pas. Chaque changement est
écrit dans le journal. Aucune valeur n'est modifiée."""
from decimal import Decimal

from django.db import migrations

SUFFIXES = {"fr": " (décimal)", "en": " (decimal)", "es": " (decimal)"}


def _decimales(v):
    """Nombre de décimales utiles d'une valeur (12.50 → 1), plafonné à 2, au moins 1."""
    v = Decimal(v).normalize()
    return min(max(-v.as_tuple().exponent, 1), 2)


def copier_unites(apps, schema_editor):
    Unite = apps.get_model("parametres", "Unite")
    KPI = apps.get_model("referentiel", "KPI")
    Reponse = apps.get_model("collecte", "Reponse")
    Journal = apps.get_model("collecte", "Journal")
    for u in Unite.objects.filter(entier=True).order_by("code"):
        concernes = []
        for k in KPI.objects.filter(unite=u).order_by("code"):
            valeurs = Reponse.objects.filter(kpi=k, origine__in=("saisie", "import"), valeur__isnull=False).values_list("valeur", flat=True)
            decimales = [_decimales(v) for v in valeurs.iterator() if v != v.to_integral_value()]
            if decimales:
                concernes.append((k, max(decimales)))
        if not concernes:
            continue
        base = f"{u.code}_decimal"[:56]
        code, i = base, 2
        while Unite.objects.filter(code=code).exists():
            code, i = f"{base}_{i}", i + 1
        traductions = {lg: {**t, **({"libelle": t["libelle"] + SUFFIXES.get(lg, " (decimal)")} if t.get("libelle") else {})}
                       for lg, t in (u.traductions or {}).items() if isinstance(t, dict)}
        d_unite = max(d for _, d in concernes)
        copie = Unite.objects.create(code=code, symbole=u.symbole, libelle=((u.libelle or u.symbole) + SUFFIXES["fr"])[:100], entier=False,
                                     decimales=max(u.decimales, d_unite), famille=u.famille, ordre=u.ordre, traductions=traductions)
        for k, d in concernes:
            avant = k.unite_id
            k.unite = copie
            champs = ["unite"]
            if k.decimales < d:
                k.decimales = d
                champs.append("decimales")
            k.save(update_fields=champs)
            Journal.objects.create(utilisateur=None, action="reglage_kpi", objet="KPI", objet_id=k.code, champ="unite", avant=avant,
                                   apres=f"{copie.code} (valeurs décimales existantes : comptage refusant les décimales)")


class Migration(migrations.Migration):

    dependencies = [
        ("collecte", "0026_alerte_textes"),
        ("parametres", "0017_relance_par_langue"),
        ("referentiel", "0017_libelles_neutres"),
    ]

    operations = [migrations.RunPython(copier_unites, migrations.RunPython.noop)]
