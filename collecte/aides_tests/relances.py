"""Aides des tests des relances : réglages SMTP et date figée."""
import datetime
from unittest import mock

from django.test import override_settings



# Les envois se testent avec un serveur d'envoi réglé (EMAIL_HOST), sans dépendre du poste : le test garde la boîte
# d'envoi en mémoire de Django. Sans SMTP (EMAIL_HOST="") : rien ne part ni n'est noté.
AVEC_SMTP = override_settings(EMAIL_HOST="smtp.exemple.test")


SANS_SMTP = override_settings(EMAIL_HOST="")


JOUR = datetime.date(2026, 6, 15)  # date figée : les retards dépendent du jour (rythme attendu)


def figer_la_date(test):
    """Fige « aujourd'hui » pendant tout le test (préparation comprise)."""
    patch = mock.patch("django.utils.timezone.localdate", return_value=JOUR)
    patch.start()
    test.addCleanup(patch.stop)
