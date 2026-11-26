"""Sauvegarde de l'installation (base + preuves + logo) dans une archive datée, avec rotation.

    python manage.py sauvegarde                  une archive maintenant, puis rotation
    python manage.py sauvegarde --motif avant-mise-a-jour
    python manage.py sauvegarde --liste          archives présentes
    python manage.py sauvegarde --planifier      selon les réglages de Paramètres › Hébergement (lancé par l'image Docker)
    python manage.py sauvegarde --copie          copie externe tout de suite (ce qui n'est pas encore copié)

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
        parser.add_argument("--copy", "--copie", dest="copie", action="store_true",
                            help="Copy now to the external destination (Settings > Hosting) the archives not copied yet.")
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
        if o["copie"]:
            return self._copier()
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
        # registre commun (comptes, réglages de l'installation) : comme le planificateur, une archive par jour au plus,
        # avec sa rotation ; sans quoi un hébergement sans tâche de fond (tâches planifiées « cron ») ne l'archivait
        # jamais. Plusieurs espaces sauvegardés l'un après l'autre : une seule archive du registre ce jour-là.
        try:
            SV.registre_du_jour()
        except Exception as e:  # noqa: BLE001 - l'archive de l'espace est faite : l'échec du registre est dit à part
            raise CommandError(f"Backup of the shared registry failed: {e}") from e

    def _copier(self):
        from parametres import copie_externe as CE

        if not CE.disponible():
            raise CommandError("External copy of the backups: not available in this version of the tool.")
        if not CE.reglage().configure:
            raise CommandError("No external destination is set (Administration > Settings > Hosting > External copy).")
        nb = CE.passage(forcer=True)
        s = CE.resume_etat()
        vie = CE.occupee() if nb is None else None
        if vie:  # un autre processus copie en ce moment (planificateur, autre instance) : pas une réussite
            raise CommandError(f"External copy: a copy is already running (last sign of life {vie:%Y-%m-%d %H:%M} UTC); "
                               f"{s['attente']} archive(s) waiting. Try again when it has finished.")
        if s["etat"] == "echec":
            raise CommandError(f"External copy failed ({s['echec']} {s['echec_resume']}): {s['attente']} archive(s) waiting.")
        if s["etat"] == "a_confirmer":
            raise CommandError("The key of the SFTP server must be confirmed first: Settings > Hosting > External copy.")
        self.stdout.write(self.style.SUCCESS(f"External copy: {nb or 0} archive(s) copied, {s['attente']} waiting."))
