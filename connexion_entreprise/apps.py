from django.apps import AppConfig


class ConnexionEntrepriseConfig(AppConfig):
    """Connexion par le compte d'entreprise (OpenID Connect), docs/single_sign_on.md : le fournisseur prouve seulement qui
    est la personne ; les comptes restent créés et gérés dans l'outil. Réglage de l'installation, dans le registre
    commun (``espaces.routeur``)."""

    name = "connexion_entreprise"
    verbose_name = "Connexion d'entreprise"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from django.db.models.signals import post_delete, post_save

        from . import regles
        from .models import ReglageEntreprise

        # état lu à chaque requête par les sessions (regles.session_permise) : relu aussitôt après un changement
        post_save.connect(regles.oublier_etat, sender=ReglageEntreprise, dispatch_uid="connexion_entreprise_etat_save")
        post_delete.connect(regles.oublier_etat, sender=ReglageEntreprise, dispatch_uid="connexion_entreprise_etat_delete")
