"""Commande lue par la tâche de mise à jour automatique de la machine (``auto-update.sh``) et par ``install.sh`` : elle ne
fait que lire l'état de l'outil ou écrire le choix de l'administrateur ; elle n'appelle jamais l'extérieur.

    python manage.py auto_update --busy                         « idle », ou la raison (busy_restore, busy_backup…) ; code 3 si occupé
    python manage.py auto_update --fingerprint                  empreinte des migrations notées dans chaque base
    python manage.py auto_update --set-choice automatic --if-unset   choix d'une installation neuve faite en une commande

Guide : docs/installation.md, « Automatic updates »."""
from django.core.management.base import BaseCommand, CommandError

from parametres import mise_a_jour_auto as MA


class Command(BaseCommand):
    help = "Automatic updates (read by auto-update.sh on the server): busy state, fingerprint of the migrations, choice."

    def add_arguments(self, parser):
        groupe = parser.add_mutually_exclusive_group(required=True)
        groupe.add_argument("--busy", action="store_true",
                            help="Print \"idle\", or the reason why an update must wait (exit code 3): restore, backup, "
                                 "import or large export in progress.")
        groupe.add_argument("--fingerprint", action="store_true",
                            help="Print one line per database (shared registry, each space) with a fingerprint of its "
                                 "applied migrations.")
        groupe.add_argument("--set-choice", choices=MA.MODES, metavar="MODE",
                            help="Set the choice of the administrator: automatic, notify or off.")
        parser.add_argument("--delay", type=int, choices=MA.DELAIS, default=MA.DELAI_DEFAUT,
                            help="With --set-choice: days to wait after the publication of a version.")
        parser.add_argument("--if-unset", action="store_true", help="With --set-choice: only if no choice is saved yet.")

    def handle(self, *args, **o):
        if o["busy"]:
            raison = MA.occupe()
            self.stdout.write(raison or "idle")
            if raison:
                raise SystemExit(3)
            return
        if o["fingerprint"]:
            for partie, empreinte in MA.empreintes():
                self.stdout.write(f"{partie} {empreinte}")
            return
        try:
            changements = MA.ecrire_choix(o["set_choice"], o["delay"], seulement_si_absent=o["if_unset"])
        except (OSError, ValueError) as e:
            raise CommandError(f"The choice could not be saved: {e}") from e
        choix = MA.lire_choix()
        etat = "saved" if changements else "unchanged"
        self.stdout.write(f"Automatic updates: {choix['mode']}, delay {choix['delai']} day(s) ({etat}).")
