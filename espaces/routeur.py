"""Routeur des bases : le registre (comptes, espaces, sessions) dans « commun », tout le reste dans la base de l'espace
courant. Un objet lu dans une base y reste ; une relation entre deux bases est refusée."""
from .contexte import COMMUN, alias_courant

MODELES_COMMUNS = {"espaces.installation", "espaces.espace", "espaces.compte", "espaces.accesespace", "sessions.session"}


def est_commun(app_label, model_name=None):
    if app_label == "sessions":
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
