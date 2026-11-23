import sys

from django.apps import AppConfig


def _creer_schema(sender, connection, **kwargs):
    """PostgreSQL : crée à la première connexion le schéma de l'alias (registre « commun », espaces « espace_<code> »)."""
    if connection.vendor != "postgresql" or connection.alias == "__no_db__":
        return
    from .contexte import schema_de

    schema = schema_de(connection.settings_dict)
    if not schema:
        return
    with connection.connection.cursor() as c:  # curseur brut : hors des gardes
        c.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", [schema])
        if c.fetchone() is None:
            c.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')


class EspacesConfig(AppConfig):
    name = "espaces"
    verbose_name = "Espaces"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from django.db.backends.signals import connection_created

        connection_created.connect(_creer_schema, dispatch_uid="espaces.schema")
        from . import comptes

        comptes.brancher()
        if "test" in sys.argv[1:2]:  # aussi dans les processus des tests en parallèle
            from .essais import ouvrir_bases

            ouvrir_bases()
