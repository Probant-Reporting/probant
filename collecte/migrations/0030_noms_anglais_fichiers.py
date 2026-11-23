"""Noms anglais des dossiers de fichiers (pour les installations à l'étranger), sans perte :
fichiers/ → files/, preuves/ → evidence/, reglages/logo/ → settings/logo/, imports-en-cours/ → pending-imports/.

Les dossiers sont fusionnés (parametres/rangement.py : jamais rien d'écrasé) ; le nom enregistré en base d'une preuve
ou du logo suit seulement si le fichier est bien à sa nouvelle place. Migration jouée pour chaque espace."""
from django.db import migrations


def renommer(apps, schema_editor):
    from espaces import contexte as ESP
    from parametres import rangement as RG

    alias = schema_editor.connection.alias
    try:
        racine = ESP.dossier_medias(ESP.code_de(alias))
    except ValueError:  # registre commun : aucun fichier déposé
        return
    RG.ranger_racine(racine)

    def nouveau_nom(nom):
        for ancien, nouveau in RG.ANCIENS.items():
            if nom.startswith(ancien + "/") and (racine / (nouveau + nom[len(ancien):])).is_file():
                return nouveau + nom[len(ancien):]
        return None

    Preuve = apps.get_model("collecte", "Preuve")
    for pk, nom in Preuve.objects.using(alias).values_list("pk", "fichier").iterator():
        n = nouveau_nom(nom or "")
        if n:
            Preuve.objects.using(alias).filter(pk=pk).update(fichier=n)
    Instance = apps.get_model("parametres", "Instance")
    for pk, nom in Instance.objects.using(alias).exclude(logo="").values_list("pk", "logo"):
        n = nouveau_nom(nom or "")
        if n:
            Instance.objects.using(alias).filter(pk=pk).update(logo=n)


class Migration(migrations.Migration):
    dependencies = [
        ("collecte", "0029_rangement_fichiers"),
        ("parametres", "0019_logo_settings"),
    ]

    operations = [migrations.RunPython(renommer, migrations.RunPython.noop)]
