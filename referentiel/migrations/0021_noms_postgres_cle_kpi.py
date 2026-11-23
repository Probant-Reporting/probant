"""PostgreSQL seulement : noms des objets liés à la clé des KPI, alignés sur ceux d'une base neuve.

Une base créée avant la mise à jour a eu sa colonne de clé renommée « code » (0004) : PostgreSQL garde alors les noms
d'origine de l'index « _like » de cette clé et de certaines clés étrangères vers elle (noms tirés de l'ancien nom de la
colonne). Cette migration retrouve ces objets par leur table et leur rôle, jamais par l'ancien nom : l'index de motif
(``varchar_pattern_ops``) sur la seule colonne « code » de la table des KPI, et chaque clé étrangère d'une colonne vers
cette clé. Chacun reçoit le nom que Django lui donne dans une base neuve. Rien d'autre ne change (mêmes colonnes, mêmes
règles). Idempotente : un objet qui a déjà le bon nom n'est pas touché ; base neuve ou SQLite : rien."""
from django.db import migrations

TABLE, COLONNE = "referentiel_kpi", "code"


def renommer(apps, schema_editor):
    c = schema_editor.connection
    if c.vendor != "postgresql":
        return
    KPI = apps.get_model("referentiel", "KPI")
    if KPI._meta.db_table != TABLE or KPI._meta.pk.column != COLONNE:
        return
    q = c.ops.quote_name
    with c.cursor() as cur:
        if TABLE not in c.introspection.table_names(cur):
            return
        # index « _like » de la clé : index de motif sur la seule colonne de clé
        cur.execute("""
            SELECT ic.relname FROM pg_index i
            JOIN pg_class ic ON ic.oid = i.indexrelid
            JOIN pg_opclass o ON o.oid = i.indclass[0]
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = i.indkey[0]
            WHERE i.indrelid = %s::regclass AND i.indnatts = 1 AND NOT i.indisprimary AND a.attname = %s
              AND o.opcname IN ('varchar_pattern_ops', 'text_pattern_ops')""", [TABLE, COLONNE])
        renommages = [("INDEX", None, nom, schema_editor._create_index_name(TABLE, [COLONNE], suffix="_like"))
                      for (nom,) in cur.fetchall()]
        # clés étrangères vers la clé des KPI (une colonne)
        cur.execute("""
            SELECT con.conname, cl.relname, a.attname FROM pg_constraint con
            JOIN pg_class cl ON cl.oid = con.conrelid
            JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = con.conkey[1]
            WHERE con.contype = 'f' AND con.confrelid = %s::regclass AND array_length(con.conkey, 1) = 1""", [TABLE])
        renommages += [("CONTRAINTE", table, nom,
                        schema_editor._create_index_name(table, [colonne], suffix=f"_fk_{TABLE}_{COLONNE}"))
                       for nom, table, colonne in cur.fetchall()]
        for genre, table, nom, attendu in renommages:
            if nom == attendu:
                continue
            cur.execute("SELECT 1 FROM pg_class WHERE relname = %s AND pg_table_is_visible(oid) "
                        "UNION SELECT 1 FROM pg_constraint WHERE conname = %s AND connamespace = "
                        "(SELECT oid FROM pg_namespace WHERE nspname = current_schema())", [attendu, attendu])
            if cur.fetchone():  # nom déjà pris (base modifiée à la main) : laissé tel quel plutôt que d'échouer
                continue
            if genre == "INDEX":
                cur.execute(f"ALTER INDEX {q(nom)} RENAME TO {q(attendu)}")
            else:
                cur.execute(f"ALTER TABLE {q(table)} RENAME CONSTRAINT {q(nom)} TO {q(attendu)}")


class Migration(migrations.Migration):
    dependencies = [("referentiel", "0020_element_demande_depuis")]
    operations = [migrations.RunPython(renommer, migrations.RunPython.noop)]
