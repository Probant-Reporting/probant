"""Espaces en ligne de commande (IT) : liste, réconciliation du registre, gestionnaires, archivage."""
from django.core.management.base import BaseCommand, CommandError

from espaces import comptes
from espaces import contexte as E

ETATS_EN = {"creation": "being created", "actif": "active", "archive": "archived"}  # états d'un espace, pour l'IT


class Command(BaseCommand):
    help = "Spaces of the installation: --list, --reconcile, --manager <email>, --archive <code>, --reactivate <code>."

    def add_arguments(self, parser):
        # noms anglais ; les anciens noms français restent acceptés
        parser.add_argument("--list", "--liste", dest="liste", action="store_true", help="List the spaces (default).")
        parser.add_argument("--reconcile", "--reconcilier", dest="reconcilier", action="store_true",
                            help="Bring the account registry and the spaces back in line.")
        parser.add_argument("--manager", "--gestionnaire", dest="gestionnaire", metavar="EMAIL",
                            help="Give this account the right to create and manage spaces.")
        parser.add_argument("--remove-manager", "--retirer-gestionnaire", dest="retirer_gestionnaire", metavar="EMAIL",
                            help="Take that right away from this account.")
        parser.add_argument("--archive", "--archiver", dest="archiver", metavar="CODE", help="Hide a space (archived).")
        parser.add_argument("--reactivate", "--reactiver", dest="reactiver", metavar="CODE", help="Show an archived space again.")

    def handle(self, *args, **o):
        from espaces.models import Compte, Espace

        if o["reconcilier"]:
            conflits = comptes.reconcilier()
            self.stdout.write(f"Reconciliation done: {len(conflits)} conflict(s).")
            for code, pk, email, motif in conflits:
                self.stdout.write(f"  space \"{code}\", account no. {pk} ({email}): {motif}")
        for cle, valeur in (("gestionnaire", True), ("retirer_gestionnaire", False)):
            if o[cle]:
                n = Compte.objects.filter(email__iexact=o[cle].strip()).update(gestionnaire=valeur)
                if not n:
                    raise CommandError(f"No account with the e-mail {o[cle]}.")
                self.stdout.write(f"{o[cle]}: space manager = {'yes' if valeur else 'no'}.")
        for cle, etat in (("archiver", Espace.Etat.ARCHIVE), ("reactiver", Espace.Etat.ACTIF)):
            if o[cle]:
                if o[cle] == E.PRINCIPAL:
                    raise CommandError("The main space cannot be archived.")
                if not Espace.objects.filter(code=o[cle]).update(etat=etat):
                    raise CommandError(f"Unknown space \"{o[cle]}\".")
                if etat == Espace.Etat.ACTIF:
                    comptes.reconcilier([o[cle]])
                self.stdout.write(f"Space \"{o[cle]}\": {ETATS_EN[etat]}.")
        # commande de l'IT (secours) : nommer, retirer et archiver restent permis sans les règles de l'outil (seul un
        # administrateur actif de l'espace principal, jamais sans gestionnaire capable d'agir) ; elle le dit
        if any(o[k] for k in ("retirer_gestionnaire", "archiver", "gestionnaire")) and not comptes.gestionnaires_capables():
            self.stdout.write("Warning: no space manager can act now. Appoint an active administrator of the main space "
                              "with --manager EMAIL.")
        if o["liste"] or not any(o[k] for k in ("reconcilier", "gestionnaire", "retirer_gestionnaire", "archiver", "reactiver")):
            for e in Espace.objects.all():
                n = e.acces.filter(actif=True).count()
                adresse = "/" if e.principal else f"/espace/{e.code}/"
                self.stdout.write(f"{e.code:<20} {e.nom:<30} {adresse:<24} {ETATS_EN.get(e.etat, e.etat):<12} {n} account(s)")
