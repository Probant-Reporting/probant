"""Relances par e-mail automatiques (réglées dans Tableau de bord › Relances) :

    python manage.py relances --auto            relances du jour, si activées (une fois par jour et par personne au plus ;
                                                la journée est réservée par espace : un second lancement le même jour,
                                                d'ici ou d'une autre instance, n'envoie rien)
    python manage.py relances --auto --simulation   qui serait relancé aujourd'hui, sans rien envoyer
    python manage.py relances --planifier       chaque jour à RELANCE_HEURE (lancé par l'image Docker)

Sans serveur d'envoi (SMTP_HOTE vide), les relances sont sautées : rien n'est envoyé ni noté comme envoyé.

Hors Docker, planifier avec cron, ex. « 0 9 * * * cd /opt/reporting && python manage.py relances --auto ».
"""
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connections
from django.utils import timezone

from collecte import relances as R
from espaces import contexte as ESP
from parametres import sauvegardes as SV


class Command(BaseCommand):
    help = "Automatic reminder emails (people who still have something to enter before the end of data entry)."

    def add_arguments(self, parser):
        parser.add_argument("--auto", action="store_true", help="Send today's reminders (if enabled in the tool).")
        parser.add_argument("--simulation", action="store_true", help="With --auto: list who would be reminded, without sending anything.")
        parser.add_argument("--schedule", "--planifier", dest="planifier", action="store_true", help="Run forever: every day at REMINDER_TIME.")

    def handle(self, *args, **o):
        if o["planifier"]:
            R.journal.info("Automatic reminders checked every day at %s", settings.RELANCE_HEURE)
            from parametres import taches_fond

            taches_fond.demarrer("reminders")  # signe de vie (page Santé, alertes par e-mail)
            while True:
                echeance = SV.prochaine(settings.RELANCE_HEURE)
                while (reste := (echeance - timezone.localtime()).total_seconds()) > 0:
                    time.sleep(min(reste, 300))
                # chaque espace avec ses réglages, son identité, ses liens ; un échec : on réessaiera le lendemain
                ESP.pour_chaque_espace(lambda: SV.base_vide() or R.relancer_automatiquement(), R.journal,
                                       "Automatic reminders failed (space \"%s\")")
                connections.close_all()
        if not o["auto"]:
            self.stdout.write("Specify --auto (today's reminders) or --schedule.")
            return
        if not R.envoi_actif() and not o["simulation"]:
            self.stdout.write("E-mails not enabled (no SMTP server set): no reminder sent or recorded. Set the sending server "
                              "in Administration > Settings > Hosting, or SMTP_HOST in the settings file; \"--simulation\" "
                              "shows who would be reminded.")
            R.relancer_automatiquement()  # avertissement dans le journal du serveur, rien n'est envoyé
            return
        liste = []
        for _ in ESP.chaque_espace():  # tous les espaces actifs (ESPACE=<code> : un seul)
            liste += R.relancer_automatiquement(simulation=o["simulation"])
        verbe = "would be reminded" if o["simulation"] else "reminded"
        self.stdout.write(f"{len(liste)} person(s) {verbe} today."
                          + ("" if R.envoi_actif() else " (E-mails not enabled: nothing would be sent for now.)"))
        for af in liste:
            self.stdout.write(f"  {af.personne.email}: {af.nombre} indicator(s)")
