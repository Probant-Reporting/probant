from django.apps import AppConfig


class ParametresConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "parametres"
    verbose_name = "Paramètres de l'installation"

    def ready(self):
        # runserver (développement) : redémarre aussi quand un fichier de textes change (libelles/*.json). Sans cela, après
        # un « git pull » qui ajoute des textes, la page montre leurs clés tant que le serveur n'est pas relancé. Sans effet en production (pas de rechargement automatique).
        from django.utils.autoreload import autoreload_started

        from . import controles  # noqa: F401 - contrôle des fichiers de langue (manage.py check, démarrage)

        autoreload_started.connect(_surveiller_libelles)


def _surveiller_libelles(sender, **kwargs):
    from django.conf import settings

    sender.watch_dir(settings.BASE_DIR / "libelles", "*.json")
