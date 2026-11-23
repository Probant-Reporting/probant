"""Démarrage de l'outil (image Docker, à chaque lancement) : dossiers des données, attente de la base, reprise après un
arrêt brutal (restes d'une sauvegarde effacés, restauration interrompue terminée), contrôle d'intégrité des bases SQLite,
sauvegarde automatique avant une mise à jour qui modifie une base, migrations de toutes les bases (espace principal,
registre commun, autres espaces), contrôle de chaque espace, résumé lisible dans le journal.

Base abîmée (contrôle d'intégrité en échec, fichier illisible) : aucune migration n'y est faite, le défaut est écrit
dans le journal avec la marche à suivre (restaurer la dernière bonne sauvegarde) et signalé par /sante/ ; l'outil
démarre quand même, pour que l'IT puisse lancer la restauration (« docker compose exec web … »).

Sur une base vide, l'outil s'ouvre ensuite sur l'assistant « Mise en place ». Un espace supplémentaire en défaut (base
injoignable, base d'un autre espace) est marqué indisponible sans bloquer les autres (docs/spaces.md).
"""
import os
import time
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.db.migrations.executor import MigrationExecutor
from django.db.utils import DatabaseError, OperationalError

from espaces import contexte as ESP
from parametres import sauvegardes as SV


def migrations_en_attente(alias):
    """Migrations à appliquer, plus les migrations renommées que la base ne note que sous leur ancien nom : ``migrate``
    y ajoutera le nom actuel, c'est une écriture dans la base, donc précédée de la sauvegarde automatique."""
    from espaces.migrations_renommees import a_harmoniser

    renommees = a_harmoniser(connections[alias])  # déjà appliquées sous l'ancien nom : pas comptées deux fois
    deja = set(renommees)
    ex = MigrationExecutor(connections[alias])
    plan = ex.migration_plan(ex.loader.graph.leaf_nodes())
    return [p for p in plan if (p[0].app_label, p[0].name) not in deja] + renommees


class Command(BaseCommand):
    help = "Prepares the installation at startup: folders, backup before migrating, migrations of all databases."

    def add_arguments(self, parser):
        parser.add_argument("--wait", "--attente", dest="attente", type=int, default=60, metavar="SECONDS",
                            help="How long to wait for the database (PostgreSQL starting up), in seconds.")

    def handle(self, *args, **o):
        from parametres import langues as L

        with L.activer_interface("en"):  # messages pour l'IT en anglais (erreurs de sauvegarde, tailles)
            return self._handle(*args, **o)

    def _handle(self, *args, **o):
        from parametres import rangement as RG

        RG.ranger_racine(settings.MEDIA_ROOT)  # anciens dossiers « media », « fichiers » de l'espace principal : deviennent « files »
        for d in (Path(settings.DOSSIER_DONNEES), Path(settings.MEDIA_ROOT), Path(settings.SAUVEGARDES_DIR),
                  Path(settings.ESPACES_DOSSIER)):
            d.mkdir(parents=True, exist_ok=True)
            if not os.access(d, os.W_OK):
                raise CommandError(f"The folder {d} is not writable by the tool (user {os.getuid()}): "
                                   "check the data volume (see docs/installation.md, \"Troubleshooting\").")
        from parametres import droits_fichiers

        n = droits_fichiers.resserrer()  # fichiers d'une version antérieure : 0600 / 0700, comme tout ce que l'outil crée
        if n:
            self.stdout.write(f"File rights: {n} file(s) or folder(s) made readable by the tool's user only.")
        self._attendre_base(o["attente"])
        from espaces.models import Espace

        commun_pret = Espace._meta.db_table in connections[ESP.COMMUN].introspection.table_names()
        autres = list(Espace.objects.exclude(code=ESP.PRINCIPAL).values_list("code", flat=True)) if commun_pret else []
        for code in autres:  # contrôlé de nouveau ci-dessous
            ESP.marquer_indisponible(code, "")
        codes = [ESP.PRINCIPAL] + autres
        en_attente = {}
        abimees = {}
        for code in codes:  # reprise après un arrêt brutal, contrôle, sauvegarde avant migration, espace par espace
            try:
                with ESP.activer(code):
                    self._reprendre(code)
                    defaut = SV.controler_base()
                    if defaut != "ok":
                        abimees[code] = defaut
                        self._signaler_abimee(code, defaut)
                        continue
                    en_attente[code] = migrations_en_attente(ESP.alias_courant())
                    if en_attente[code] and not SV.base_vide():
                        self.stdout.write(f"Updating space \"{code}\" ({len(en_attente[code])} migration(s)): "
                                          "automatic backup before.")
                        self.stdout.write(f"  {SV.creer('before-update').chemin}")
            except SV.ErreurSauvegarde as e:  # disque plein… : pas de mise à jour sans sauvegarde
                if code == ESP.PRINCIPAL:
                    raise CommandError(f"Space \"{code}\": backup before the update failed, the update was not applied "
                                       f"(the database is unchanged). {e}") from e
                self.stderr.write(f"Space \"{code}\": backup before the update failed ({e}).")
                ESP.marquer_indisponible(code, f"backup before the update failed ({e})")
            except Exception as e:
                if code == ESP.PRINCIPAL:
                    raise
                self.stderr.write(f"Space \"{code}\": backup before the update failed ({e}).")
                ESP.marquer_indisponible(code, f"database unreachable before the update ({e})")
        for code in abimees:
            if code != ESP.PRINCIPAL:
                ESP.marquer_indisponible(code, f"damaged database: {abimees[code][:200]}")
        if commun_pret and migrations_en_attente(ESP.COMMUN):
            self.stdout.write(f"  shared registry: {SV.creer_registre('before-update')}")
        if ESP.PRINCIPAL in abimees:  # aucune migration sur une base abîmée ; l'outil démarre pour la restauration
            call_command("migrate", database=ESP.COMMUN, interactive=False, verbosity=0)
            self.stderr.write("The tool starts WITHOUT updating its database (damaged): /sante/ reports it.")
            return
        call_command("migrate", interactive=False, verbosity=0)
        RG.ecrire_lisez_moi(settings.DOSSIER_DONNEES)  # README.txt : plan du dossier des données, pour l'IT
        from parametres.models import Instance
        from espaces.models import Compte

        b = connections["default"].settings_dict
        vendor = connections["default"].vendor
        base = f"SQLite ({b['NAME']})" if vendor == "sqlite" else f"PostgreSQL ({b.get('HOST')}/{b.get('NAME')})"
        i = Instance.courante()
        nb = Compte.objects.count()
        etat = ("empty: the \"Setup\" wizard will be shown" if not nb
                else "setup in progress" if not i.mise_en_place_terminee else f"\"{i.nom}\", {nb} account(s)")
        lignes = [
            f"Probant, version {settings.VERSION}{' (' + settings.VERSION_COMMIT[:12] + ')' if settings.VERSION_COMMIT else ''}",
            f"Database: {base}, {len(en_attente.get(ESP.PRINCIPAL, []))} migration(s) applied; installation {etat}",
            f"Data: {settings.DOSSIER_DONNEES}; backups: {settings.SAUVEGARDES_DIR} ({len(SV.archives())} archive(s))",
            f"Address(es): {', '.join(settings.ALLOWED_HOSTS)}; HTTPS: {'yes' if settings.HTTPS else 'no'}",
            f"E-mails: {'SMTP ' + settings.EMAIL_HOST + ':' + str(settings.EMAIL_PORT) if settings.EMAIL_HOST else 'not configured (SMTP_HOST empty)'}",
        ]
        lignes += [f"Space \"{e}" for e in self._controler_espaces()]
        for l in lignes:
            self.stdout.write(l)
        try:  # corbeille (collecte/corbeille.py) : ce qui y est depuis plus que le délai réglé est effacé ; jamais bloquant
            call_command("purge_deleted", stdout=self.stdout)
        except Exception as e:  # noqa: BLE001
            self.stderr.write(f"Purge of deleted items skipped ({e}).")
        try:  # sessions terminées (registre commun) : aussi chaque nuit (check_data --schedule) ; jamais bloquant
            from collecte.controle_donnees import effacer_sessions_expirees

            n = effacer_sessions_expirees([c for c in codes if c not in abimees and not ESP.indisponible(c)])
            self.stdout.write(f"Sessions: {n} expired session(s) erased.")
        except Exception as e:  # noqa: BLE001
            self.stderr.write(f"Erasing of expired sessions skipped ({e}).")

    def _reprendre(self, code):
        """Restes d'un arrêt brutal pour l'espace courant : fichiers temporaires d'une sauvegarde effacés, restauration
        interrompue terminée depuis son archive."""
        n = SV.nettoyer_restes() + SV.nettoyer_depots_partiels()
        if n:
            self.stdout.write(f"Space \"{code}\": {n} leftover(s) of an interrupted backup or upload deleted.")
        r = SV.reprendre_restauration()
        if r is None:
            return
        nom, erreur = r
        if not erreur:
            self.stdout.write(f"Space \"{code}\": the restore of {nom}, interrupted, has been finished.")
        else:
            self.stderr.write(
                f"Space \"{code}\": the restore of {nom} was interrupted and could not be finished ({erreur}). "
                "The tool may be inconsistent: restore the archive again (python manage.py restore <name> --yes), "
                "or the \"before-restore\" archive to go back (docs/installation.md, \"Troubleshooting\").")

    def _signaler_abimee(self, code, defaut):
        a = SV.derniere_archive_saine()
        conseil = (f"restore the last good backup: python manage.py restore {a.nom} --yes (with Docker: "
                   f"docker compose exec web python manage.py restore {a.nom} --yes), then restart the tool"
                   if a else "no good backup found in this folder: use the external copy of the backups")
        espace = "" if code == ESP.PRINCIPAL else f"SPACE={code} "
        self.stderr.write(
            f"DAMAGED DATABASE (space \"{code}\"): {defaut[:300]}\n"
            f"  Nothing has been changed in it and it has not been updated. To repair: {espace}{conseil}. "
            "The damaged state is kept by the restore (\"before-restore-damaged\" archive, or the file renamed "
            "\".damaged-<date>\" when it cannot be opened). See docs/installation.md, \"Troubleshooting\".")

    def _controler_espaces(self):
        """Chaque espace supplémentaire : base joignable et marquée à son nom (et à celui de l'installation). En défaut :
        marqué indisponible (page 503), les autres espaces continuent."""
        from espaces import comptes as EC
        from espaces.models import Espace, MarqueEspace

        inst = EC.installation()
        sortie = []
        for e in Espace.objects.filter(etat=Espace.Etat.CREATION):
            sortie.append(f"{e.nom}\" ({e.code}): creation interrupted, to be resumed by a manager (Spaces page, "
                          "\"Resume\")")
        for e in Espace.objects.filter(etat=Espace.Etat.ACTIF).exclude(code=ESP.PRINCIPAL):
            if ESP.indisponible(e.code):  # migrations impossibles (journal ci-dessus)
                sortie.append(f"{e.nom}\" ({e.code}): UNAVAILABLE, {ESP.fichier_indisponible(e.code).read_text(encoding='utf-8')}")
                continue
            motif = ""
            try:
                with ESP.activer(e.code):
                    m = MarqueEspace.objects.first()
                    if m is None or m.code != e.code or (inst and m.installation != inst.identifiant):
                        motif = "the database is not the one of this space (different mark)"
            except Exception as x:
                motif = f"database unreachable ({x})"
            if motif:
                ESP.marquer_indisponible(e.code, motif)
            sortie.append(f"{e.nom}\" ({e.code}): {'UNAVAILABLE, ' + motif if motif else 'ready'}")
        return sortie

    def _attendre_base(self, secondes):
        fin = time.monotonic() + secondes
        while True:
            try:
                connections["default"].ensure_connection()
                connections[ESP.COMMUN].ensure_connection()
                return
            except DatabaseError as e:
                if not isinstance(e, OperationalError) or "disk" in str(e) or "not a database" in str(e):
                    return  # fichier SQLite abîmé, disque : contrôlé et expliqué plus loin
                if time.monotonic() > fin:
                    raise CommandError(f"Database unreachable: {e}") from e
                self.stdout.write("Database not ready yet, retrying in 2 s…")
                time.sleep(2)
