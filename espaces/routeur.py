"""Routeur des bases : le registre (comptes, espaces, sessions, connexion d'entreprise) dans « commun », tout le reste dans
la base de l'espace courant. Un objet lu dans une base y reste ; une relation entre deux bases est refusée."""
from .contexte import COMMUN, alias_courant

MODELES_COMMUNS = {"espaces.installation", "espaces.espace", "espaces.compte", "espaces.accesespace", "espaces.serveurenvoi",
                   "espaces.reglagealertes", "espaces.etatalertes", "espaces.problemesignale",  # alertes : toute l'installation
                   "espaces.destinationcopie", "espaces.etatcopie",  # copie externe des sauvegardes : toute l'installation
                   "sessions.session",
                   # connexion par le compte d'entreprise : réglage de l'installation, liens des comptes (docs/single_sign_on.md)
                   "connexion_entreprise.reglageentreprise", "connexion_entreprise.lienentreprise"}
APPLICATIONS_COMMUNES = {"sessions", "connexion_entreprise"}  # toutes leurs tables dans le registre commun


def est_commun(app_label, model_name=None):
    if app_label in APPLICATIONS_COMMUNES:
        return True
    return app_label == "espaces" and model_name is not None and f"espaces.{model_name}" in MODELES_COMMUNS


class Routeur:
    def db_for_read(self, model, **hints):
        if model._meta.label_lower in MODELES_COMMUNS:
            return COMMUN
        inst = hints.get("instance")
        if inst is not None and getattr(inst, "_state", None) is not None and inst._state.db:
            return inst._state.db
        return alias_courant()

    db_for_write = db_for_read

    def allow_relation(self, a, b, **hints):
        if a._state.db and b._state.db:
            return a._state.db == b._state.db
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if est_commun(app_label, model_name):
            return db == COMMUN
        return db != COMMUN
