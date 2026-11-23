"""Rangement des fichiers (parametres/rangement.py), sans perte :

- le dossier des fichiers d'un espace s'appelle « fichiers » (avant : « media ») ; son contenu y est déplacé ;
- preuves : preuves/<période>/<organisation>/<KPI>/<fichier> (avant : preuves/<période>/<KPI>/<n° d'organisation>_<fichier>) ;
- logo : reglages/logo/ (avant : identite/) ; fichiers en cours d'import : imports-en-cours/ (avant : imports/).

Chaque fichier est déplacé, jamais copié ni écrasé (suffixe « -2 » si la place est prise), et son nom enregistré en base
suit. Un fichier déjà absent garde son nom enregistré. Migration jouée pour chaque espace, sur son propre dossier.

Reprise sans perte : la migration n'est pas une seule transaction (chaque nom est enregistré aussitôt son
fichier déplacé) ; interrompue (arrêt brutal, disque plein), elle est rejouée au démarrage suivant et retrouve à sa
nouvelle place un fichier déjà déplacé dont le nom n'avait pas encore été enregistré."""
from django.db import migrations


def ranger(apps, schema_editor):
    from espaces import contexte as ESP
    from parametres import rangement as RG

    alias = schema_editor.connection.alias
    try:
        racine = ESP.dossier_medias(ESP.code_de(alias))
    except ValueError:  # base qui n'est pas celle d'un espace (registre commun) : aucun fichier déposé
        return
    RG.ranger_racine(racine)
    Preuve = apps.get_model("collecte", "Preuve")
    for p in Preuve.objects.using(alias).select_related("reponse__periode", "reponse__organisation").order_by("pk").iterator():
        r = p.reponse
        ancien = p.fichier.name
        base = ancien.rsplit("/", 1)[-1]
        prefixe = f"{r.organisation_id}_"
        if base.startswith(prefixe):
            base = base[len(prefixe):]
        nouveau = RG.chemin_preuve(r.periode.debut, r.periode.type == "annee", r.organisation.code or r.organisation_id,
                                   r.kpi_id, base)
        if nouveau == ancien:
            continue
        nom = RG.deplacer(racine, ancien, nouveau)
        if nom is None:  # déjà déplacé par une exécution interrompue, nom pas encore enregistré : retrouvé
            nom = _deja_deplace(Preuve, alias, racine, nouveau)
        if nom is not None and nom != ancien:
            Preuve.objects.using(alias).filter(pk=p.pk).update(fichier=nom)
    Instance = apps.get_model("parametres", "Instance")
    for i in Instance.objects.using(alias).exclude(logo=""):
        ancien = i.logo.name
        if ancien.startswith(RG.LOGO + "/"):
            continue
        nom = RG.deplacer(racine, ancien, f"{RG.LOGO}/{ancien.rsplit('/', 1)[-1]}")
        if nom is not None and nom != ancien:
            Instance.objects.using(alias).filter(pk=i.pk).update(logo=nom)


def _deja_deplace(Preuve, alias, racine, nouveau):
    """Nom (« nouveau », « nouveau-2 »…) d'un fichier présent à sa nouvelle place qu'aucune preuve n'utilise encore."""
    from pathlib import PurePosixPath

    cible = PurePosixPath(nouveau)
    for n in range(1, 100):
        nom = str(cible if n == 1 else cible.with_name(f"{cible.stem}-{n}{cible.suffix}"))
        if not (racine / nom).is_file():
            return None
        if not Preuve.objects.using(alias).filter(fichier=nom).exists():
            return nom
    return None


class Migration(migrations.Migration):
    atomic = False  # chaque déplacement de fichier et son nom en base vont ensemble (reprise sans perte)

    dependencies = [
        ("collecte", "0028_valeurs_forcees"),
        ("parametres", "0018_logo_reglages"),
        ("referentiel", "0017_libelles_neutres"),
    ]

    operations = [migrations.RunPython(ranger, migrations.RunPython.noop)]
