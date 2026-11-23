"""Aides communes aux démos (``charger_demo`` : Exemplia, espace « Achats » ; jeu d'essai à trois niveaux des tests) :
comptes de démo, unités et types de réponse ajoutés. Le nom commence par « _ » : Django n'en fait pas une commande."""
from parametres.models import TypeReponse, Unite
from referentiel.models import Utilisateur


def compte(ident, prenom, nom, role, mot_de_passe, **champs):
    """Compte de démo « ident » créé ou remis à jour (actif, mot de passe connu, sans changement imposé). Un compte créé
    reçoit l'e-mail « ident@exemple.test » ; ``champs`` (e-mail, équipe, langue…) sont écrits dans tous les cas."""
    u = Utilisateur.objects.filter(username=ident).first() or Utilisateur(username=ident, email=f"{ident}@exemple.test")
    u.first_name, u.last_name, u.role, u.is_active, u.doit_changer_mdp = prenom, nom, role, True, False
    u.is_staff = u.is_superuser = role == Utilisateur.Role.ADMIN
    for champ, valeur in champs.items():
        setattr(u, champ, valeur)
    u.set_password(mot_de_passe)
    u.save()
    return u


def unites_et_types(unites, types_reponse):
    """Unités (code, symbole, libellé, nombre entier, décimales, famille) ajoutées si absentes, à la suite des autres ;
    types de réponse (code, libellé, format, valeurs) créés ou remis à jour, rangés à partir de 10."""
    for code, symbole, libelle, entier, decimales, famille in unites:
        Unite.objects.get_or_create(code=code, defaults=dict(symbole=symbole, libelle=libelle, entier=entier, decimales=decimales,
                                                             famille=famille, ordre=Unite.objects.count() + 1))
    for i, (code, libelle, fmt, valeurs) in enumerate(types_reponse, start=10):
        TypeReponse.objects.update_or_create(code=code, defaults=dict(libelle=libelle, format=fmt, valeurs=valeurs, ordre=i))
