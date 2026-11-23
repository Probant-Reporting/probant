"""Session commune à tous les espaces (on se connecte une fois), mais les clés de l'outil (campagne choisie, filtres…)
sont propres à chaque espace : hors espace principal, elles sont préfixées « espace:<code>: ». Les clés de Django
(« _auth_user_id », « _messages »…) et la langue de l'interface (choix de la personne, pas de l'espace) restent
communes."""
from parametres.langues import CLE_SESSION as LANGUE

from . import contexte as E

COMMUNES = {LANGUE}  # clés de l'outil partagées par tous les espaces


class SessionEspace:
    def __init__(self, session, code):
        object.__setattr__(self, "_s", session)
        object.__setattr__(self, "_p", f"espace:{code}:")

    def _k(self, k):
        return k if str(k).startswith("_") or k in COMMUNES else self._p + k

    def __getitem__(self, k):
        return self._s[self._k(k)]

    def __setitem__(self, k, v):
        self._s[self._k(k)] = v

    def __delitem__(self, k):
        del self._s[self._k(k)]

    def __contains__(self, k):
        return self._k(k) in self._s

    def get(self, k, defaut=None):
        return self._s.get(self._k(k), defaut)

    def pop(self, k, *defaut):
        return self._s.pop(self._k(k), *defaut)

    def setdefault(self, k, defaut=None):
        return self._s.setdefault(self._k(k), defaut)

    def keys(self):
        return [k[len(self._p):] if k.startswith(self._p) else k for k in self._s.keys()
                if k.startswith(self._p) or k.startswith("_") or k in COMMUNES]

    def __iter__(self):
        return iter(self.keys())

    def items(self):
        return [(k, self[k]) for k in self.keys()]

    def values(self):
        return [v for _, v in self.items()]

    def __getattr__(self, nom):
        return getattr(self._s, nom)

    def __setattr__(self, nom, valeur):
        setattr(self._s, nom, valeur)


class SessionEspaceMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        code = E.code_courant()
        if code != E.PRINCIPAL and hasattr(request, "session"):
            request.session = SessionEspace(request.session, code)
        return self.get_response(request)
