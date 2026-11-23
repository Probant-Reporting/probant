"""Conversion des tableaux de la Visualisation (TableauVisu) en vues (VueVisu), sans perte (bascule de la Visualisation
v2). Une vue par tableau, un visuel par tuile, dans le même ordre ; titre, largeur, nom, description, propriétaire,
partage et dates conservés ; l'ordre des tableaux (partagés d'abord, puis par nom) devient VueVisu.ordre.

Correspondance tuile → visuel :
- chiffre → chiffre (même KPI) ;
- evolution → barres sur l'axe des périodes ;
- organisations → comparaison des organisations ;
- repartition → anneau (mêmes parts : organisations, ou décompte d'un oui / non ou d'une liste) ;
- tableau → tableau, même source (``liste:<id>`` ou ``theme:<id>``) ;
- forme inconnue → visuel « indisponible », la tuile d'origine gardée dans ``origine.brut`` (jamais jetée).

Fonctions figées, recopiées ici (la migration n'importe pas le code de l'application, appelé à évoluer). Idempotente ;
le retour arrière retire seulement les vues converties. La table des tableaux n'est ni modifiée ni vidée : elle reste
pour un retour en arrière et pour les redirections, jusqu'à une migration ultérieure.
"""
from django.db import migrations

LARGEURS = {1: 4, 2: 8, 3: 12}  # tiers → colonnes sur 12
DEFAUT = {"chiffre": 1, "evolution": 2, "organisations": 2, "repartition": 1, "tableau": 3}  # TableauVisu.LARGEUR_DEFAUT
FORMES = {"chiffre": ("chiffre", {}), "evolution": ("barres", {"axe": "periodes"}),
          "organisations": ("organisations", {"axe": "organisations"}), "repartition": ("anneau", {}),
          "tableau": ("tableau", {})}


def convertir_tuiles(t_id, tuiles):
    visuels = []
    if not isinstance(tuiles, list):  # contenu abîmé (pas une liste) : une seule tuile, gardée telle quelle
        tuiles = [tuiles] if tuiles else []
    for i, x in enumerate(tuiles):
        x = x if isinstance(x, dict) else {"type": str(x)}
        ancien = x.get("type") or ""
        ancien = ancien if isinstance(ancien, str) else str(ancien)
        forme, extra = FORMES.get(ancien, ("indisponible", {}))
        largeur = x.get("largeur") or DEFAUT.get(ancien, 1)
        v = {"id": f"t{t_id}-{i + 1}", "type": forme, "titre": str(x.get("titre") or "")[:150],
             "kpis": [str(x["kpi"])] if x.get("kpi") else [],
             "source": str(x.get("source") or "") if ancien == "tableau" else "",
             "axe": "", "series": "",
             "largeur": LARGEURS.get(largeur, 4) if isinstance(largeur, int) else 4, "hauteur": "m",
             "filtres": {}, "options": {}, "origine": {"tableau": t_id, "tuile": i + 1, "type": ancien}, **extra}
        if ancien not in FORMES:
            v["origine"]["brut"] = x  # forme inconnue : gardée telle quelle, jamais jetée
        if x.get("saisi") and not x.get("kpi"):
            v["origine"]["saisi"] = x["saisi"]
        visuels.append(v)
    return visuels


def tableaux_en_vues(apps, schema_editor):
    """Une vue par tableau (idempotente : un tableau déjà converti est sauté)."""
    TableauVisu = apps.get_model("collecte", "TableauVisu")
    VueVisu = apps.get_model("collecte", "VueVisu")
    deja = set(VueVisu.objects.exclude(ancien_tableau=None).values_list("ancien_tableau", flat=True))
    for rang, t in enumerate(TableauVisu.objects.order_by("-partage", "nom", "pk")):
        if t.pk in deja:
            continue
        v = VueVisu.objects.create(nom=t.nom, description=t.description, proprietaire_id=t.proprietaire_id,
                                   partage=t.partage, ordre=rang, filtres={}, schema=1,
                                   visuels=convertir_tuiles(t.pk, t.tuiles), ancien_tableau=t.pk)
        VueVisu.objects.filter(pk=v.pk).update(date_creation=t.date_creation, date_maj=t.date_maj)


def retour(apps, schema_editor):
    """Retour arrière : les vues converties sont retirées ; les tableaux, jamais touchés, restent."""
    apps.get_model("collecte", "VueVisu").objects.exclude(ancien_tableau=None).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("collecte", "0022_vues_visualisation"),
    ]

    operations = [
        migrations.RunPython(tableaux_en_vues, retour),
    ]
