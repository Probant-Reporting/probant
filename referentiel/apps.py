from django.apps import AppConfig


class ReferentielConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "referentiel"
    verbose_name = "Référentiel"

    def ready(self):
        from . import connexion  # noqa: F401  (compte des échecs de connexion)
