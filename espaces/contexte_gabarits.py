"""Contexte des gabarits : espaces de la personne connectée (sélecteur « Espace » de la barre du haut)."""
from django.utils.functional import SimpleLazyObject

from . import contexte as E


def role(code):
    """Nom du rôle dans la langue de l'interface (Administrateur, Validateur…)."""
    from parametres.libelles import choix_valeur

    return choix_valeur("utilisateur", "role", code)


class MenuEspaces:
    def __init__(self, request):
        from .models import Compte
        from .vues import espaces_de

        u = getattr(request, "user", None)
        self.liste, self.gestionnaire, self.courant = [], False, None
        if u is None or not u.is_authenticated:
            return
        code = E.code_courant()
        for e, r in espaces_de(u.pk):
            self.liste.append({"code": e.code, "nom": e.nom, "role": role(r), "url": E.url_espace(e.code),
                               "courant": e.code == code})
            if e.code == code:
                self.courant = e
        self.gestionnaire = Compte.objects.filter(pk=u.pk, gestionnaire=True, actif=True).exists()

    @property
    def plusieurs(self):
        return len(self.liste) > 1


def espaces(request):
    return {"espaces_menu": SimpleLazyObject(lambda: MenuEspaces(request))}
