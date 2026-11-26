"""A few actions of a person in the tool, made on a demo database with the code of an OLD version.

Used by qa/update_from_published.py (check "an installation of any published version updates directly to the current
version"): run in the folder of the code of the old version, with its settings (DATA_DIR, DATABASE_URL), after
``load_demo``:

    python /path/to/qa/update_gestures.py

It only uses what every version has had since the first public one (the models of answers, evidence and log), so it
runs on any published version. Gestures: one value entered in the open campaign and validated (the calculations that
cite it are redone by the tool itself, as for a person), one evidence file attached to it (a real file in the evidence
folder), one line written to the log. Fictitious data only.
"""
import os
import sys

sys.path.insert(0, os.getcwd())
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django  # noqa: E402

django.setup()

from django.core.files.base import ContentFile  # noqa: E402
from django.utils import timezone  # noqa: E402

from collecte.models import Campagne, Journal, Preuve, Reponse  # noqa: E402
from referentiel.models import Utilisateur  # noqa: E402

VALEUR = 4242  # reconnaissable dans une extraction
PDF = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"


def main():
    admin = Utilisateur.objects.get(username="admin")
    ouvertes = Campagne.objects.filter(statut=Campagne.Statut.OUVERTE).order_by("-exercice")
    if not ouvertes:
        raise SystemExit("No open campaign in the demo: nothing to do the gestures on.")
    reponse = (Reponse.objects.filter(periode__in=[c.periode for c in ouvertes], origine=Reponse.Origine.SAISIE,
                                      statut=Reponse.Statut.BROUILLON, valeur__isnull=False, non_applicable=False)
               .exclude(preuves__isnull=False).order_by("pk").first())
    if reponse is None:
        raise SystemExit("No draft number in the open campaign: nothing to do the gestures on.")
    avant = reponse.valeur
    reponse.valeur = VALEUR
    reponse.statut = Reponse.Statut.VALIDE
    reponse.saisi_par = admin
    reponse.valide_par = admin
    reponse.date_validation = timezone.now()
    reponse.save()
    Journal.ecrire(admin, "valeur", reponse, "valeur", avant, VALEUR)
    preuve = Preuve(reponse=reponse, depose_par=admin)
    preuve.fichier.save("preuve-mise-a-jour.pdf", ContentFile(PDF), save=False)
    preuve.save()
    print(f"gestures done: 1 value validated, 1 evidence file ({os.path.basename(preuve.fichier.name)}), 1 log line")


if __name__ == "__main__":
    main()
