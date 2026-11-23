"""Unités écrites en anglais dans un référentiel importé (par exemple « employees », « members »…) : symbole dans la langue de
référence de l'installation, les deux autres langues en traductions (règle du projet).

Sans perte : le code des unités (clé dans les fichiers) ne change pas ; une traduction déjà saisie n'est jamais
remplacée ; seules les unités de la liste ``parametres.referentiel.SYMBOLES_ANGLAIS`` sont touchées. Retour arrière :
le symbole anglais est remis dans le champ (les traductions ajoutées restent, elles ne gênent pas)."""
from django.db import migrations

# liste et règle partagées avec les imports de référentiel (une unité créée plus tard est traduite de la même façon)
from parametres.referentiel import SYMBOLES_ANGLAIS, traduire_unite

ANGLAIS = dict(SYMBOLES_ANGLAIS)


def traduire(apps, schema_editor):
    Instance, Unite = apps.get_model("parametres", "Instance"), apps.get_model("parametres", "Unite")
    i = Instance.objects.filter(pk=1).first()
    reference = (i.langue_reference if i else "") or "fr"
    for u in Unite.objects.filter(symbole__in=list(ANGLAIS)):
        if traduire_unite(u, reference):
            u.save(update_fields=["symbole", "traductions"])


def remettre(apps, schema_editor):
    Unite = apps.get_model("parametres", "Unite")
    francais = {fr: en for en, (fr, es) in ANGLAIS.items()}
    for u in Unite.objects.all():
        en = ((u.traductions or {}).get("en") or {}).get("symbole")
        if en in ANGLAIS and francais.get(u.symbole) == en:
            u.symbole = en
            u.save(update_fields=["symbole"])


class Migration(migrations.Migration):
    dependencies = [("parametres", "0020_format_texte_redige")]
    operations = [migrations.RunPython(traduire, remettre)]
