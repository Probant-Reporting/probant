"""« grant_admin » : rend l'accès administrateur à un compte (secours de l'IT).

L'outil refuse de laisser une installation sans administrateur actif (Administration › Comptes). Si cela arrive quand
même (restauration d'une ancienne sauvegarde, base modifiée à la main), l'IT rend l'accès à un compte existant :

    python3 manage.py grant_admin admin@exemple.test

Le compte (identifiant ou e-mail) devient administrateur et actif ; le changement est inscrit dans l'historique.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from collecte.models import Journal
from referentiel.models import Utilisateur


class Command(BaseCommand):
    help = "Rend le rôle d'administrateur (et l'accès) à un compte existant : identifiant ou e-mail."

    def add_arguments(self, parser):
        parser.add_argument("compte", help="identifiant ou e-mail du compte")

    def handle(self, *args, **options):
        cle = options["compte"].strip()
        comptes = list(Utilisateur.objects.filter(Q(username__iexact=cle) | Q(email__iexact=cle))[:2])
        if not comptes:
            raise CommandError(f"Aucun compte « {cle} ».")
        if len(comptes) > 1:
            raise CommandError(f"Plusieurs comptes correspondent à « {cle} » : donnez l'identifiant exact.")
        u = comptes[0]
        avant = u.get_role_display()
        u.role, u.is_active, u.is_staff, u.is_superuser = Utilisateur.Role.ADMIN, True, True, True
        u.save(update_fields=["role", "is_active", "is_staff", "is_superuser"])
        Journal.ecrire(None, "reglage_compte", u, "rôle", avant, u.get_role_display())
        self.stdout.write(self.style.SUCCESS(f"{u.username} est administrateur."))
