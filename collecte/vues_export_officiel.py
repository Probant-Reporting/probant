"""Import / Export › Formats officiels : remplir le classeur officiel d'une norme (VS de l'EFRAG) avec les valeurs d'un
exercice. « Vérifier » montre ce qui sera rempli et ce qui manque ; « Télécharger » produit le classeur. Réservé aux
administrateurs (le classeur contient toutes les données de l'entreprise)."""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from parametres import langues as L
from parametres.libelles import libelle

from . import export_officiel as X
from .models import Periode
from .vues_echanges import identifiant

TYPE_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@login_required
def export_officiel(request):
    if not request.user.est_admin:
        raise PermissionDenied(libelle("suivi.officiel.reserve_admin"))
    formats = X.formats_disponibles()
    organisations = X.organisations_exportables()
    langue_interface = L.interface()
    noms_langues = {"en": libelle("suivi.officiel.langue_en"), "fr": libelle("suivi.officiel.langue_fr"),
                    "es": libelle("suivi.officiel.langue_es")}
    contexte = {"rubrique": "officiel", "formats": [], "organisations": organisations,
                "langues": [(lg, noms_langues.get(lg, lg)) for lg in X.FO.vs_efrag.LANGUES],
                "choix": {"langue": langue_interface if langue_interface in X.FO.vs_efrag.LANGUES else "en"}}
    for f in formats:
        contexte["formats"].append({"code": f.CODE, "nom": f.NOM.get(langue_interface) or f.NOM["en"], "version": f.VERSION,
                                    "periodes": X.periodes_exportables(f)})
    if formats:
        contexte["choix"].update(format=formats[0].CODE, organisation=organisations[0].pk if organisations else None,
                                 periode=contexte["formats"][0]["periodes"][0].pk if contexte["formats"][0]["periodes"] else None)
    if request.method == "POST" and formats:
        fmt = next((f for f in formats if f.CODE == request.POST.get("format")), formats[0])
        org = get_object_or_404(X.Organisation, pk=identifiant(request.POST.get("organisation")))
        periode = get_object_or_404(Periode, pk=identifiant(request.POST.get("periode")))
        langue = request.POST.get("langue") if request.POST.get("langue") in fmt.LANGUES else "en"
        contexte["choix"] = {"format": fmt.CODE, "organisation": org.pk, "periode": periode.pk, "langue": langue}
        if request.POST.get("action") == "telecharger":
            donnees, _ = X.exporter(fmt.CODE, org, periode, langue, request.user)
            reponse = HttpResponse(donnees, content_type=TYPE_XLSX)
            reponse["Content-Disposition"] = f'attachment; filename="{X.nom_fichier(fmt, org, periode)}"'
            return reponse
        _, rapport = X.exporter(fmt.CODE, org, periode, langue)
        contexte["rapport"] = rapport
    return render(request, "collecte/echanges/officiel.html", contexte)
