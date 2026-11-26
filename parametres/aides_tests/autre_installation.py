"""Aides des tests de la restauration d'une sauvegarde d'une autre installation : archive « d'ailleurs » fabriquée à partir
d'une archive de l'outil, avec les comptes voulus, signée par le secret d'un autre serveur (jamais valide ici), et au
besoin trafiquée (empreinte de mot de passe connue, jeton d'assistant, déclencheur SQLite…)."""
import copy
import json
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from django.contrib.auth.hashers import make_password

from parametres import sauvegardes as SV

AUTRE_SECRET = "secret-d-un-autre-serveur-" + "z" * 40
AUTRE_IDENTIFIANT = "f" * 32
ORIGINE = "Installation d'origine"


def refaire_table(table, ancien, nouveau):
    """Fonction pour ``traiter_sqlite`` : refait ``table`` (CREATE, INSERT SELECT, DROP, RENAME, sans « writable_schema »)
    avec ``ancien`` remplacé par ``nouveau`` dans son texte, par exemple un type écrit entre guillemets."""
    def traiter(c):
        sql = c.execute("SELECT sql FROM sqlite_master WHERE name = ?", [table]).fetchone()[0]
        assert ancien in sql, ancien
        c.execute(sql.replace(ancien, nouveau, 1).replace(f'"{table}"', f'"{table}__n"', 1))
        c.execute(f'INSERT INTO "{table}__n" SELECT * FROM "{table}"')
        c.execute(f'DROP TABLE "{table}"')
        c.execute(f'ALTER TABLE "{table}__n" RENAME TO "{table}"')
        c.commit()
    return traiter


def compte(pk, email, role="contributeur", actif=True, mot_de_passe=None, username=None):
    """Compte d'une archive d'ailleurs ; ``mot_de_passe`` : empreinte d'un mot de passe connu écrite dans l'archive (forgée)."""
    return {"pk": pk, "email": email, "username": username or email, "role": role, "is_superuser": role == "admin",
            "is_staff": role == "admin", "is_active": actif,
            "password": make_password(mot_de_passe) if mot_de_passe else SV.MOT_DE_PASSE_RETIRE}


def _signer(descriptif, z, secret=AUTRE_SECRET):
    descriptif = {k: v for k, v in descriptif.items() if k != SV.SIGNATURE}
    descriptif[SV.SIGNATURE] = {"algorithme": SV.ALGORITHME_SIGNATURE,
                                "valeur": SV._signer(descriptif, SV._empreintes(z), secret)}
    return descriptif


def archive_d_ailleurs(cible, comptes, format_base="json", objets_en_plus=(), sql_en_plus=(), descriptif=None,
                       fichiers=None, modifier_objets=None, traiter_sqlite=None, secret=None):
    """Écrit dans ``cible`` (chemin .zip) une archive faite « par une autre installation » : celle de l'espace courant
    (``SV.creer``), comptes remplacés par ``comptes`` (``compte``), descriptif d'une autre installation, signée par un autre
    secret. ``objets_en_plus`` : objets JSON ajoutés ; ``sql_en_plus`` : requêtes jouées dans la copie SQLite ;
    ``descriptif`` : champs du descriptif remplacés ; ``fichiers`` : {nom dans l'archive: octets} ajoutés."""
    modele = SV.creer("modele", format_base)
    try:
        with zipfile.ZipFile(modele.chemin) as src:
            d = json.loads(src.read(SV.DESCRIPTIF))
            contenu = {n: src.read(n) for n in src.namelist() if n != SV.DESCRIPTIF}
    finally:
        modele.chemin.unlink()
    # comptes=None : comptes de l'espace gardés tels quels (changement de serveur : mêmes personnes)
    if format_base == "json" and comptes is None:
        if modifier_objets:
            objets = json.loads(contenu[SV.BASE_JSON])
            modifier_objets(objets)
            contenu[SV.BASE_JSON] = json.dumps(objets).encode()
    elif format_base == "json":
        objets = json.loads(contenu[SV.BASE_JSON])
        gabarit = next(o for o in objets if o["model"] == "referentiel.utilisateur")
        retires = [[o["fields"]["username"]] for o in objets if o["model"] == "referentiel.utilisateur"]
        # lignes qui citent un compte retiré par sa clé naturelle (historique des connexions, journal…) : retirées aussi
        objets = [o for o in objets if o["model"] != "referentiel.utilisateur"
                  and not any(v in retires for v in o["fields"].values())]
        for c in comptes:
            o = copy.deepcopy(gabarit)
            o["pk"] = c["pk"]
            o["fields"].update({k: v for k, v in c.items() if k != "pk"}, last_login=None, groups=[], user_permissions=[])
            objets.insert(0, o)
        objets += list(objets_en_plus)
        if modifier_objets:  # objets de l'archive trafiqués (liste modifiée sur place)
            modifier_objets(objets)
        contenu[SV.BASE_JSON] = json.dumps(objets).encode()
    else:
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / SV.BASE_SQLITE
            f.write_bytes(contenu[SV.BASE_SQLITE])
            c = sqlite3.connect(f)
            table = SV._table_comptes()
            curseur = c.execute(f'SELECT * FROM "{table}" LIMIT 1')
            colonnes = [x[0] for x in curseur.description]
            gabarit = dict(zip(colonnes, curseur.fetchone()))
            if comptes is not None:
                c.execute(f'DELETE FROM "{table}"')
            for compte_ in comptes or []:
                ligne = {**gabarit, **{k: v for k, v in compte_.items() if k in colonnes}, "id": compte_["pk"],
                         "last_login": None}
                c.execute(f'INSERT INTO "{table}" ({", ".join(colonnes)}) VALUES ({", ".join("?" * len(colonnes))})',
                          [ligne[x] for x in colonnes])
            for sql in sql_en_plus:
                c.executescript(sql)
            if traiter_sqlite:  # copie trafiquée par une fonction (connexion sqlite3)
                traiter_sqlite(c)
            c.commit()
            c.close()
            contenu[SV.BASE_SQLITE] = f.read_bytes()
    d.update({"identifiant_installation": AUTRE_IDENTIFIANT, "installation": ORIGINE, **(descriptif or {})})
    contenu.update(fichiers or {})
    Path(cible).parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(cible, "w", zipfile.ZIP_DEFLATED) as z:
        for n, data in contenu.items():
            z.writestr(n, data)
    with zipfile.ZipFile(cible, "a") as z:
        z.writestr(SV.DESCRIPTIF, json.dumps(_signer(d, z, secret or AUTRE_SECRET)))  # secret : celui d'ici possible
    return Path(cible)
