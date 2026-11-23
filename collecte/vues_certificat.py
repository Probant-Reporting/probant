"""Certificat de clôture d'une campagne clôturée (``certificat_cloture.py``) : une page de l'outil faite pour être imprimée
(feuille de style d'impression, pas de PDF fabriqué par le serveur). Lecture seule, administrateur et auditeur ; un auditeur
limité à des organisations reçoit un certificat partiel, marqué comme tel, sur ses seules organisations."""
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.cache import never_cache

from . import certificat_cloture as CE
from . import dates_courtes as DC
from .models import Campagne


@never_cache
@login_required
def certificat(request, pk):
    CE.exiger(request.user)  # les droits d'abord : une personne sans droit n'apprend pas si la campagne existe
    c = get_object_or_404(Campagne.objects.select_related("referentiel", "periode"), pk=pk)
    if c.statut != Campagne.Statut.CLOTUREE:
        raise Http404
    contexte = CE.construire(request.user, c)
    contexte.update({"page": "certificat", "edite_le": DC.date_heure_courte(timezone.now()), "auditeur": not request.user.est_admin})
    return render(request, "collecte/certificat/certificat.html", contexte)
