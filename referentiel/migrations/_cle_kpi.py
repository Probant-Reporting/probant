"""Clé des KPI : désormais, 0001 la crée directement sous le nom « code » (avant : un autre nom, renommé
« code » par 0004). Une base créée avant et pas encore passée par 0004 a toujours l'autre nom : sa colonne de clé est
renommée « code » (mêmes valeurs, liens des autres tables suivis), au début de 0003 et de 0004, selon le point de départ.
Base neuve ou déjà passée par 0004 : rien. Le nom d'avant n'est pas écrit : il est lu dans la base (clé primaire).

Fichier commençant par « _ » : Django ne le prend pas pour une migration."""


def cle_kpi_nommee_code(apps, schema_editor):
    KPI = apps.get_model("referentiel", "KPI")
    connexion = schema_editor.connection
    table = KPI._meta.db_table
    with connexion.cursor() as curseur:
        if table not in connexion.introspection.table_names(curseur):
            return
        colonne = connexion.introspection.get_primary_key_column(curseur, table)
    cle = KPI._meta.pk
    if colonne in (None, cle.column):
        return
    ancienne = cle.clone()
    ancienne.set_attributes_from_name(colonne)
    ancienne.model = KPI
    schema_editor.alter_field(KPI, ancienne, cle)  # comme RenameField : colonne renommée, rien d'autre
