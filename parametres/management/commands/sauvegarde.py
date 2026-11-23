"""Sauvegarde de l'installation (base + preuves + logo) dans une archive datée, avec rotation.

    python manage.py sauvegarde                  une archive maintenant, puis rotation
    python manage.py sauvegarde --motif avant-mise-a-jour
    python manage.py sauvegarde --liste          archives présentes
    python manage.py sauvegarde --planifier      selon les réglages de Paramètres › Hébergement (lancé par l'image Docker)

Hors Docker, planifier avec cron, ex. « 30 2 * * * cd /opt/reporting && python manage.py sauvegarde ».
"""
from django.core.management.base import BaseCommand, CommandError

from parametres import sauvegardes as SV


class Command(BaseCommand):
    help = "Backs up the database and uploaded files into a dated archive (BACKUPS_DIR folder), with rotation."

    def add_arguments(self, parser):
        parser.add_argument("--reason", "--motif", dest="motif", default="", metavar="REASON", help="Word added to the archive name (e.g. before-update).")
        parser.add_argument("--keep", "--conserver", dest="conserver", type=int, default=None, metavar="NUMBER",
                            help="Number of archives kept (default: the number set in the tool).")
        parser.add_argument("--json", action="store_true", help="Database as Django JSON (portable) rather than a SQLite copy.")
        parser.add_argument("--list", "--liste", dest="liste", action="store_true", help="List the existing archives.")
        parser.add_argument("--schedule", "--planifier", dest="planifier", action="store_true", help="Run forever: backups according to the tool settings (frequency, time, number kept).")
        parser.add_argument("--time", "--heure", dest="heure", default=None, metavar="HH:MM", help="With --schedule: force the start time HH:MM (default: the one set in the tool).")

    def handle(self, *args, **o):
        from parametres import langues as L

        with L.activer_interface("en"):  # messages pour l'IT en anglais (erreurs, tailles), interface inchangée
            return self._handle(*args, **o)

    def _handle(self, *args, **o):
        if o["liste"]:
            liste = SV.archives()
            for a in liste:
                self.stdout.write(f"{a.nom}  {SV.taille_lisible(a.taille)}")
            self.stdout.write(f"{len(liste)} backup(s) in {SV.dossier()}")
            return
        if o["planifier"]:
            SV.planifier(o["heure"])
            return
        if SV.base_vide():
            self.stdout.write("Empty database (first start): nothing to back up.")
            return
        try:
            a = SV.creer(o["motif"], "json" if o["json"] else None)
        except SV.ErreurSauvegarde as e:
            raise CommandError(str(e)) from e
        supprimees = SV.tourner(o["conserver"])
        self.stdout.write(self.style.SUCCESS(f"Backup created: {a.chemin} ({SV.taille_lisible(a.taille)})"))
        if supprimees:
            self.stdout.write(f"Rotation: {len(supprimees)} old archive(s) deleted.")
