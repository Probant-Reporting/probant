"""Schéma d'une base SQLite d'espace comparé à celui que le code attend (restauration d'une archive : contenu non fiable).

Référence : les tables des modèles rangés dans une base d'espace, créées par l'éditeur de schéma de Django dans une base
en mémoire (jamais de migration, aucune donnée). Pour chaque table de la référence, la base contrôlée doit avoir
exactement les mêmes éléments de définition (colonnes avec leur type, NOT NULL, clé, CHECK, COLLATE, DEFAULT, REFERENCES,
ON DELETE…, et contraintes de table), dans n'importe quel ordre (une colonne ajoutée par une migration va à la fin), et
exactement les mêmes index (au nom près). Rien de plus : un CHECK ajouté, une colonne retirée, un index UNIQUE ajouté, une
clé étrangère en ON DELETE CASCADE sont des écarts. Les tables en plus (tables d'une version antérieure que le code ne lit
plus) sont admises ; les déclencheurs, vues, tables virtuelles et colonnes calculées sont refusés partout
(``objets_interdits``)."""
import re
import sqlite3
from functools import lru_cache

ESPACES = re.compile(r"\s+")


def _normaliser(texte):
    t = ESPACES.sub(" ", texte.strip()).lower()
    t = re.sub(r"\s*([(),])\s*", r"\1", t)
    return t.replace('"', "").replace("`", "").replace("[", "").replace("]", "")


def elements_de_table(sql):
    """Éléments de premier niveau de la définition d'une table (colonnes, contraintes), normalisés, en ensemble."""
    debut = sql.index("(")
    corps, profondeur, courant, elements, guillemet = sql[debut + 1:], 0, "", [], None
    for c in corps:
        if guillemet:
            courant += c
            if c == guillemet:
                guillemet = None
            continue
        if c in "\"'`":
            guillemet = c
        elif c == "(":
            profondeur += 1
        elif c == ")":
            if profondeur == 0:
                break
            profondeur -= 1
        elif c == "," and profondeur == 0:
            elements.append(courant)
            courant = ""
            continue
        courant += c
    elements.append(courant)
    return frozenset(_normaliser(e) for e in elements if e.strip())


def _index_sans_nom(sql):
    return _normaliser(re.sub(r'(?is)^\s*create\s+(unique\s+)?index\s+("[^"]*"|\S+)\s+on', r"create \1index on", sql))


def schema(connexion):
    """{table: (éléments, frozenset(index))} des tables d'une connexion sqlite3."""
    tables = {n: s for n, s in connexion.execute("SELECT name, sql FROM sqlite_master WHERE lower(type) = 'table' "
                                                 "AND name NOT LIKE 'sqlite_%'")}
    index = {}
    for table, sql in connexion.execute("SELECT tbl_name, sql FROM sqlite_master WHERE lower(type) = 'index' AND sql IS NOT NULL"):
        index.setdefault(table, set()).add(_index_sans_nom(sql))
    return {t: (elements_de_table(s or "()"), frozenset(index.get(t, ()))) for t, s in tables.items()}


def _checks(sql):
    """Contraintes CHECK du texte d'une table, avec leurs guillemets (un texte entre guillemets n'est pas une contrainte :
    jamais retirés ici), espaces réduits. Lues hors des chaînes et des noms entre guillemets."""
    sortie, i, n, guillemet = set(), 0, len(sql), None
    while i < n:
        c = sql[i]
        if guillemet:
            if c == guillemet:
                guillemet = None
            i += 1
            continue
        if c in "\"'`[":
            guillemet = "]" if c == "[" else c
            i += 1
            continue
        if sql[i:i + 5].upper() == "CHECK" and (i == 0 or not (sql[i - 1].isalnum() or sql[i - 1] == "_")):
            j = i + 5
            while j < n and sql[j].isspace():
                j += 1
            if j < n and sql[j] == "(":
                profondeur, k, g = 0, j, None
                while k < n:
                    x = sql[k]
                    if g:
                        g = None if x == g else g
                    elif x in "\"'`":
                        g = x
                    elif x == "(":
                        profondeur += 1
                    elif x == ")":
                        profondeur -= 1
                        if profondeur == 0:
                            break
                    k += 1
                sortie.add(ESPACES.sub(" ", sql[j:k + 1]).strip())
                i = k + 1
                continue
        i += 1
    return frozenset(sortie)


def structure(connexion):
    """{table: (colonnes, index, clés étrangères, CHECK)} tels que SQLite les comprend (PRAGMA), indépendants de la façon
    dont le texte de CREATE TABLE est écrit (une ancienne version de Django l'écrivait autrement) : un type écrit entre
    guillemets pour cacher NOT NULL, UNIQUE, PRIMARY KEY ou REFERENCES est vu comme ce qu'il est (un nom de type)."""
    sortie = {}
    for table, sql in connexion.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"):
        q = table.replace('"', '""')
        colonnes = frozenset((r[1], ESPACES.sub(" ", (r[2] or "").strip()).upper(), r[3], r[4], r[5], r[6])
                             for r in connexion.execute(f'PRAGMA table_xinfo("{q}")'))
        index = set()
        for r in connexion.execute(f'PRAGMA index_list("{q}")'):
            nom = r[1].replace('"', '""')
            cles = tuple((x[2], x[3], x[4]) for x in connexion.execute(f'PRAGMA index_xinfo("{nom}")') if x[5])
            index.add((r[2], r[3], r[4], cles))  # unique, origine (c, u, pk), partiel, colonnes (nom, ordre, collation)
        cles_etrangeres = {}
        for r in connexion.execute(f'PRAGMA foreign_key_list("{q}")'):
            cles_etrangeres.setdefault(r[0], []).append((r[2], r[3], r[4], r[5], r[6], r[7]))
        sortie[table] = (colonnes, frozenset(index), frozenset(tuple(v) for v in cles_etrangeres.values()),
                         _checks(sql or ""))
    return sortie


def modeles_d_espace():
    from django.apps import apps

    from espaces.routeur import est_commun

    return [m for m in apps.get_models(include_auto_created=True)
            if m._meta.managed and not m._meta.proxy and not est_commun(m._meta.app_label, m._meta.model_name)]


@lru_cache(maxsize=1)
def reference():
    """Schéma attendu par le code (calculé une fois par processus)."""
    from django.db.backends.sqlite3.base import DatabaseWrapper

    c = DatabaseWrapper({"NAME": ":memory:", "ENGINE": "django.db.backends.sqlite3", "OPTIONS": {}, "TIME_ZONE": None,
                         "CONN_MAX_AGE": 0, "CONN_HEALTH_CHECKS": False, "AUTOCOMMIT": True, "ATOMIC_REQUESTS": False,
                         "USER": "", "PASSWORD": "", "HOST": "", "PORT": "", "TEST": {}}, alias="__schema_reference__")
    try:
        c.ensure_connection()
        with c.schema_editor(atomic=False) as editeur:
            for m in modeles_d_espace():
                if not m._meta.auto_created:
                    editeur.create_model(m)  # crée aussi les tables plusieurs-à-plusieurs
        return schema(c.connection), structure(c.connection)
    finally:
        c.close()


def objets_interdits(connexion):
    """Nombre d'objets que l'outil ne crée jamais et qui agiraient après la restauration : déclencheurs, vues, tables
    virtuelles (type comparé sans tenir compte de la casse) et colonnes cachées ou calculées."""
    # type réécrit (« writable_schema ») : seul le texte compte au VACUUM suivant, qui recrée l'objet d'après lui
    n = connexion.execute(
        "SELECT count(*) FROM sqlite_master WHERE type NOT IN ('table', 'index') "
        "OR (type = 'table' AND (upper(ltrim(sql)) NOT LIKE 'CREATE TABLE%' OR upper(ltrim(sql)) LIKE 'CREATE VIRTUAL%')) "
        "OR (type = 'index' AND sql IS NOT NULL AND upper(ltrim(sql)) NOT LIKE 'CREATE INDEX%' "
        "AND upper(ltrim(sql)) NOT LIKE 'CREATE UNIQUE INDEX%')").fetchone()[0]
    for (table,) in connexion.execute("SELECT name FROM sqlite_master WHERE lower(trim(type)) = 'table'").fetchall():
        nom = table.replace('"', '""')
        try:
            if any(c[6] for c in connexion.execute(f'PRAGMA table_xinfo("{nom}")')):
                n += 1
        except sqlite3.Error:
            n += 1
    return n


def ecarts(connexion):
    """Écarts entre le schéma d'une connexion sqlite3 et celui que le code attend : [texte court], vide si conforme."""
    (attendu, attendue), reel, reelle = reference(), schema(connexion), structure(connexion)
    sortie = []
    for table, (elements, index) in sorted(attendu.items()):
        if table not in reel:
            sortie.append(f"{table}: missing")
            continue
        e, i = reel[table]
        if e != elements:
            sortie.append(f"{table}: " + "; ".join(sorted(e ^ elements))[:300])
        if i != index:
            sortie.append(f"{table}: indexes " + "; ".join(sorted(i ^ index))[:300])
        # structure comprise par SQLite : colonnes, index, clés étrangères, CHECK (guillemets gardés)
        for nom, a, r in zip(("columns", "indexes", "foreign keys", "checks"), attendue[table], reelle[table]):
            if a != r:
                sortie.append(f"{table}: {nom} " + "; ".join(sorted(map(str, a ^ r)))[:300])
    return sortie
