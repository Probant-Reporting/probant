from django.apps import AppConfig


class ServeurMcpConfig(AppConfig):
    """Serveur MCP : un assistant (IA) lit et agit dans l'outil avec les droits de la personne (docs/mcp.md)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "serveur_mcp"
    verbose_name = "Serveur MCP"

    def ready(self):
        from django.db.models.signals import post_save, pre_save

        from collecte.models import Journal
        from referentiel.models import Utilisateur

        from .jetons import apres_enregistrement_compte, avant_enregistrement_compte
        from .journal import noter_ecriture

        # chaque ligne du journal écrite pendant un appel d'outil est marquée « via MCP » (JournalMCP)
        post_save.connect(noter_ecriture, sender=Journal, dispatch_uid="serveur_mcp.journal")
        # mot de passe changé (tout chemin qui enregistre le compte) : jetons de la personne révoqués dans tous les espaces
        pre_save.connect(avant_enregistrement_compte, sender=Utilisateur, dispatch_uid="serveur_mcp.mdp_avant")
        post_save.connect(apres_enregistrement_compte, sender=Utilisateur, dispatch_uid="serveur_mcp.mdp_apres")
