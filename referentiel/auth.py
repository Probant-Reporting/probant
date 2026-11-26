"""Connexion par e-mail (ou identifiant), sans tenir compte des majuscules. Comptes créés par l'administrateur.

Connexion d'entreprise allumée (connexion_entreprise/regles.py) : le mot de passe ne sert plus qu'aux comptes de secours
(gestionnaires des espaces), sauf si le réglage le laisse à tous ; un bon mot de passe d'un autre compte est refusé
(``request.connexion_entreprise_exigee``) ; la page donne alors le même message que pour un mauvais mot de passe.

Comptes communs à tous les espaces (docs/spaces.md) : le mot de passe est vérifié dans le registre commun ; la personne
reçoit la copie de son compte dans l'espace demandé (avec le rôle de cet espace)."""
import logging

from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.hashers import check_password, make_password

from .models import Utilisateur

journal = logging.getLogger("referentiel.connexion")


def copie_active(compte, alias):
    """Copie active du compte dans l'espace ``alias``, avec le mot de passe du registre (en mémoire), ou None."""
    u = Utilisateur._default_manager.using(alias).filter(pk=compte.pk, is_active=True).first()
    if u is None or (u.email or "").lower() != (compte.email or "").lower():
        return None
    u.password = compte.password
    return u


class EmailOuIdentifiant(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None
        from espaces import comptes as EC
        from espaces import contexte as E
        from espaces.models import Compte

        from .connexion import bloquee

        if bloquee(username, request):  # trop d'échecs récents : le mot de passe n'est même pas vérifié
            return None
        ident = username.strip()
        # l'e-mail d'abord, puis l'identifiant exact, puis sans majuscules : un identifiant qui ressemble à l'e-mail
        # d'une autre personne (base d'un espace restaurée) ne prend jamais sa place à la connexion
        c = (Compte.objects.filter(email__iexact=ident).order_by("pk").first()
             or Compte.objects.filter(username=ident).order_by("pk").first()
             or Compte.objects.filter(username__iexact=ident).order_by("pk").first())
        if c is None:
            make_password(password)  # même durée de réponse qu'un compte existant
            return None

        def mettre_a_jour(brut):  # empreinte d'un algorithme plus récent : registre puis copies
            from serveur_mcp.jetons import suivre_hachage

            ancien, c.password = c.password, make_password(brut)
            Compte.objects.filter(pk=c.pk).update(password=c.password)
            with E.toutes_les_bases():
                for code in EC.codes_ouverts():
                    alias = E.declarer(code)
                    Utilisateur._default_manager.using(alias).filter(pk=c.pk).update(password=c.password)
                    # même mot de passe : ses jetons MCP restent valides (``update`` n'envoie aucun signal)
                    suivre_hachage(alias, c.pk, ancien, c.password)

        if not (check_password(password, c.password, mettre_a_jour) and c.actif):
            return None
        from connexion_entreprise.regles import mot_de_passe_permis

        if not mot_de_passe_permis(c.pk):  # bon mot de passe, mais ce compte se connecte par son compte d'entreprise
            if request is not None:
                request.connexion_entreprise_exigee = True
            return None
        u = copie_active(c, E.alias_courant())
        if u is not None:
            return u if self.user_can_authenticate(u) else None
        # pas de copie active ici : la page de connexion propose l'espace où la personne a accès
        with E.toutes_les_bases():
            codes = EC.codes_ouverts()
            ordre = ([c.dernier_espace] if c.dernier_espace in codes else []) + codes
            for code in ordre:
                autre = copie_active(c, E.declarer(code))
                if autre is not None and request is not None:
                    request.espaces_connexion_ailleurs = (code, autre)
                    break
        return None

    def get_user(self, user_id):
        from espaces.models import Compte

        u = Utilisateur._default_manager.filter(pk=user_id, is_active=True).first()
        if u is None:
            return None
        c = Compte.objects.filter(pk=user_id).first()
        if c is None or not c.actif:
            return None
        if (c.email or "").lower() != (u.email or "").lower():
            journal.error("Account no. %s: e-mail %s in this space, %s in the shared registry; access refused (to reconcile).",
                          user_id, u.email, c.email)
            return None
        u.password = c.password  # empreinte de la session : toujours celle du registre
        return u
