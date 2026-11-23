"""Restaure une sauvegarde (base + preuves + logo). L'état actuel est d'abord sauvegardé (« avant-restauration »).

    python manage.py restauration sauvegarde-20261026-023000-auto.zip      (nom dans SAUVEGARDES_DIR, ou chemin)
    python manage.py restauration /chemin/vers/archive.zip --oui           sans confirmation

Avec Docker : « docker compose exec web python manage.py restauration <nom> », puis « docker compose restart web ».
"""
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from parametres import sauvegardes as SV


def texte_sans_mot_de_passe(n):
    """Message pour l'IT : comptes restaurés sans mot de passe (les archives d'un espace n'en contiennent pas)."""
    return (f"{n} account(s) of this space have no password on this server. Backups of a space hold no password: the "
            "tool reads them from the shared registry, and this registry does not know these accounts (backup restored "
            "on another server, or accounts deleted since the backup). To fix it, do one of these: restore the backup "
            "of the shared registry made at the same time (folder backups/shared: python manage.py restore --shared "
            "<registry-….zip> --yes); or give new passwords: python manage.py changepassword <username> for one "
            "administrator, who then gives the others a temporary password in Administration › Accounts. "
            "See docs/installation.md, \"Restore a backup\".")


class Command(BaseCommand):
    help = "Restores a backup of the tool (replaces the database and uploaded files)."

    def add_arguments(self, parser):
        parser.add_argument("archive", help="Name of an archive in the backups folder, or path of a .zip file.")
        parser.add_argument("--yes", "--oui", dest="oui", action="store_true", help="Do not ask for confirmation.")
        parser.add_argument("--no-backup-before", "--sans-sauvegarde-avant", dest="sans_sauvegarde_avant", action="store_true", help="Do not back up the current state first.")
        parser.add_argument("--other-space", "--autre-espace", dest="autre_espace", action="store_true",
                            help="IT: restore into this space (SPACE=<code>) the archive of another space or of another installation.")
        parser.add_argument("--rebuild", "--reconstruire", dest="reconstruire", action="store_true",
                            help="IT, PostgreSQL: going back to the version that made this archive, after an update. "
                                 "Drops the tables of this space, creates them again with the migrations of the "
                                 "installed version, then loads the archive (all or nothing).")
        parser.add_argument("--unsigned", dest="non_signee", action="store_true",
                            help="IT: restore an archive without a valid signature of this installation (made by a "
                                 "version that did not sign archives, by another server, or after a change of the "
                                 "secret key). Only for an archive that you trust.")
        parser.add_argument("--shared", "--commun", dest="commun", action="store_true",
                            help="IT: restore the shared registry (accounts, spaces) from an archive of backups/shared.")

    def handle(self, *args, **o):
        from parametres import langues as L

        with L.activer_interface("en"):  # messages pour l'IT en anglais (erreurs, tailles), interface inchangée
            return self._handle(*args, **o)

    def _handle(self, *args, **o):
        if o["commun"]:
            from espaces import contexte as ESP

            chemin = Path(o["archive"])
            if not chemin.is_file():
                chemin = ESP.dossier_sauvegardes_commun() / o["archive"]
            if not chemin.is_file():
                raise CommandError(f"Registry archive not found: {o['archive']}.")
            if not o["oui"] and input("The shared registry (accounts, spaces) will be replaced. Continue? [yes/no] ").strip().lower() not in ("o", "oui", "y", "yes"):
                raise CommandError("Restore cancelled.")
            try:
                SV.restaurer_registre(chemin)
            except SV.ErreurSauvegarde as e:
                raise CommandError(str(e)) from e
            self.stdout.write(self.style.SUCCESS("Shared registry restored and brought back in line with the spaces."))
            return
        chemin = Path(o["archive"])
        if not chemin.is_file():
            chemin = SV.dossier() / o["archive"]
        if not chemin.is_file():
            raise CommandError(f"Archive not found: {o['archive']} (see \"python manage.py backup --list\").")
        try:
            d = SV.lire_descriptif(chemin)
        except SV.ErreurSauvegarde as e:
            raise CommandError(str(e)) from e
        self.stdout.write(f"Backup of {d['date'][:16].replace('T', ' at ')} – \"{d.get('installation', '')}\", "
                          f"version {d.get('version')}, {d.get('fichiers', 0)} uploaded file(s).")
        if d.get("contenu_base") == "json" and SV.ESP.connexion().vendor == "postgresql" \
                and sorted(map(list, d.get("migrations") or [])) != SV.migrations_comparables():
            self._structure_differente(d, o)
        elif o["reconstruire"]:
            self.stdout.write("--rebuild is not needed: the database has the same migrations as the archive (ordinary restore).")
        if not SV.signature_valide(chemin):
            if not o["non_signee"]:
                raise CommandError(
                    "This archive has no valid signature of this installation. Either it was made by a version "
                    "that did not sign archives, or by another server, or after a change of the secret key, or it was "
                    "changed after it was made. Nothing was changed. If you trust this archive, run the same command "
                    "again with --unsigned. See docs/installation.md, \"Restore a backup\".")
            self.stdout.write("Archive without a valid signature of this installation: restored because of --unsigned.")
        if not o["oui"]:
            reponse = input("The current database and uploaded files will be replaced. Continue? [yes/no] ")
            if reponse.strip().lower() not in ("o", "oui", "y", "yes"):
                raise CommandError("Restore cancelled.")
        try:
            d = SV.restaurer(chemin, sauvegarder_avant=not o["sans_sauvegarde_avant"], autre_espace=o["autre_espace"],
                             reconstruire=o["reconstruire"])
        except SV.ErreurSauvegarde as e:
            raise CommandError(str(e)) from e
        self.stdout.write(self.style.SUCCESS("Restore complete. Restart the tool so that it reads the restored data (with Docker: docker compose restart web)."))
        if d.get("comptes_sans_mot_de_passe"):
            self.stdout.write(self.style.WARNING(texte_sans_mot_de_passe(d["comptes_sans_mot_de_passe"])))

    def _structure_differente(self, d, o):
        """Archive JSON (PostgreSQL) faite avec d'autres migrations que celles de la base : ce qui est possible, et
        comment, en clair pour l'IT (docs/installation.md, « Going back to the previous version »)."""
        espace = "" if SV.ESP.est_principal() else f"SPACE={SV.ESP.code_courant()} "
        guide = "See docs/installation.md, \"Going back to the previous version\"."
        if not SV.reconstruction_possible(d):
            raise CommandError(
                f"This PostgreSQL backup (version {d.get('version')}) was made with other database migrations than "
                "the installed version of the tool. A PostgreSQL backup restores only with the version of the tool "
                "that made it: install that version first, then run this command again (with --rebuild if the "
                f"database was already updated). Nothing was changed. {guide}")
        if not o["reconstruire"]:
            etat = ("The database of this space is empty (no tables)." if SV.base_vide() else
                    "The database was updated by a more recent version of the tool (it has migrations that this backup, "
                    f"version {d.get('version')}, does not have).")
            raise CommandError(
                f"{etat} Nothing was changed. To go back to the state of the backup, "
                f"run: {espace}python manage.py restore {Path(o['archive']).name} --rebuild. This drops the tables of "
                f"this space and creates them again for this version, then loads the backup (all or nothing). {guide}")
        self.stdout.write("Rebuild: the tables of this space will be dropped, created again for this version of the "
                          "tool, then filled with the backup (all or nothing).")
