"""Périodes dont une campagne est déjà clôturée à côté d'une campagne encore ouverte (règle « Figer ses chiffres »,
règle du projet, ``collecte.calcul.noter_figes_partiels``).

Rien n'a été noté à la clôture de ces campagnes (version précédente) : leurs KPI, et l'arbre des organisations, sont
notés une fois, tels qu'ils sont le jour de la mise à jour. Jusqu'ici, ces KPI étaient recalculés avec l'arbre
d'aujourd'hui à chaque changement : leurs chiffres enregistrés sont ceux de cet arbre, ils ne bougent pas. Rien n'est
recalculé : aucun chiffre ne change ; ensuite, plus rien ne les réécrit (sauf une correction importée dans la campagne
clôturée). Les périodes entièrement closes, et celles rouvertes en gardant les chiffres de l'époque, ne
changent pas. Une migration n'appelle pas le moteur de calcul : elle pose le travail, fait à la fin de « migrate » avec
le code installé (``collecte.mise_a_jour``, code « noter_figes_partiels »).

Retour arrière : rien à défaire (la colonne de ``0046`` est retirée avec elle).
"""
from django.db import migrations

MOTIF = "KPI des campagnes clôturées à côté d'une campagne ouverte figés (arbre du jour de la mise à jour)."


def poser(apps, schema_editor):
    apps.get_model("referentiel", "TravailApresMiseAJour").objects.update_or_create(code="noter_figes_partiels",
                                                                                  defaults={"motif": MOTIF})


class Migration(migrations.Migration):
    dependencies = [
        ("collecte", "0046_periode_figes_partiels"),
        ("referentiel", "0016_na_compte_zero_entiers"),
    ]

    operations = [migrations.RunPython(poser, migrations.RunPython.noop)]
