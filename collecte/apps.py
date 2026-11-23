from importlib import import_module

from django.apps import AppConfig


class CollecteConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "collecte"
    verbose_name = "Collecte"

    def ready(self):
        from django.db.models.signals import post_migrate

        import_module(f"{self.name}.signals")  # branche le recalcul automatique après une saisie
        # travaux posés par une migration (ex. refaire les calculs quand une règle change), faits une fois la base à jour
        post_migrate.connect(import_module(f"{self.name}.mise_a_jour").apres_migrate, sender=self,
                             dispatch_uid="collecte.travaux_apres_mise_a_jour")
