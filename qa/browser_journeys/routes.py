"""List the routes of the tool, with a real example address for each, and the access each role must have.

    DATA_DIR=/folder/of/the/demo python3 qa/browser_journeys/routes.py > routes.json

Nothing is typed by hand: the routes come from the URL configuration (``config/urls.py`` and the three ``urls.py`` of
the apps), the example identifiers (campaign, KPI, organisation, account, view...) come from the demo database named by
``DATA_DIR`` (or ``DATABASE_URL``), exactly as ``manage.py`` reads them, and the access of the two read-only roles comes
from ``collecte/lecture_seule.py`` (the sets of pages the reader and the auditor may open). Run it again after a change
of routes or of demo; ``crawl.js`` and ``readonly_writes.js`` read its output.

Output (JSON): {"routes": [{"name", "route", "url", "readonly"}], "skipped": [{"route", "reason"}]}
  name      URL name (``collecte:saisie``...) ; route  the pattern ; url  an address that exists in this demo
  readonly  "reader" and "auditor": true if that role may open the page, false if the role must get a 403
  get_status  only on a page that answers to POST only (/mcp/): the status a GET gets, for every role (405)
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.urls import URLPattern, URLResolver, get_resolver

from collecte import lecture_seule as LS
from collecte.models import Alerte, Campagne, Preuve, ReglageExport, RegleCoherence, TableauVisu, TacheExport, TacheImport, VueVisu
from referentiel.models import KPI, Attribution, Organisation, Referentiel, Theme, Utilisateur

# Pages open to a visitor who is not signed in, besides the ones lecture_seule.py frees: the privacy page (linked from
# the sign-in page) and the sign-in page of the expert mode (Django admin), where /admin/ sends a visitor.
PUBLIC = {"confidentialite"}

# Routes that answer to POST only (a token, no session): a GET is not a page, so the expected answer is 405 for every role and
# for a visitor. ``crawl.js`` reads it from "get_status".
POST_ONLY = {"point": 405}  # /mcp/ : the assistants (MCP) endpoint

# Routes that must not be visited by a crawl: they end the session or need a file name that only the machine knows.
IGNORED = {
    "logout": "ends the session",
    "sauvegarde_telecharger": "needs the name of a backup file",
    "sauvegarde_restaurer": "restores a backup (writes)",
    "paquet_fourni": "needs the name of a provided package file",
    "installer_kpi": "needs the code of a library model",
    "installer_resume": "needs the code of a library model",
    "aide_image": "needs the language and the name of a guide screenshot",
}


def first(model, **filtre):
    o = model.objects.filter(**filtre).order_by("pk").first()
    return o.pk if o else None


def echantillons():
    """Example value of each URL parameter, per URL name: {(url name, parameter): value or None}."""
    camp = Campagne.objects.order_by("-pk").first()
    kpi = KPI.objects.order_by("pk").first()
    ref = Referentiel.objects.order_by("pk").first()
    admin = Utilisateur.objects.filter(username="admin").first() or Utilisateur.objects.order_by("pk").first()
    # A cell (KPI + organisation) must be a valid pair: the organisation has the level of the KPI. A group with a site KPI
    # answers 403 (the panel does not exist), which a crawl would report as an anomaly. First choice: an assignment of the demo.
    attribution = Attribution.objects.select_related("kpi", "organisation").order_by("pk").first()
    case_kpi, case_org = (attribution.kpi.code, attribution.organisation.pk) if attribution else (None, None)
    if case_kpi is None and kpi is not None:
        org_du_niveau = Organisation.objects.filter(niveau_id=kpi.granularite_id).order_by("pk").first()
        case_kpi, case_org = (kpi.code, org_du_niveau.pk) if org_du_niveau else (None, None)
    return {
        "campagne_id": camp.pk if camp else None,
        "kpi_id": {"cellule": case_kpi, "": kpi.code if kpi else None},
        "org_id": {"cellule": case_org, "": first(Organisation)},
        "user_id": admin.pk if admin else None,
        "etape": 1,
        "guide": "administrator",
        "type_": "kpi",
        "pk": {  # the meaning of ``pk`` depends on the page
            "choisir_campagne": camp.pk if camp else None,
            "admin_campagne": camp.pk if camp else None,
            "visu_theme": first(Theme),
            "visu_tableau": first(TableauVisu), "visu_tableau_modifier": first(TableauVisu),
            "visu_vue": first(VueVisu), "visu_vue_donnees": first(VueVisu), "visu_vue_enregistrer": first(VueVisu),
            "visu_vue_dupliquer": first(VueVisu), "visu_vue_supprimer": first(VueVisu), "visu_vue_partage": first(VueVisu),
            "visu_vue_preferee": first(VueVisu), "visu_vue_excel": first(VueVisu),
            "preuve": first(Preuve),
            "alerte": first(Alerte),
            "regle": first(RegleCoherence), "regle_basculer": first(RegleCoherence),
            "echanges_supprimer_reglage": first(ReglageExport),
            "echanges_tache_etat": first(TacheImport), "echanges_tache_arreter": first(TacheImport),
            "echanges_export_etat": first(TacheExport), "echanges_export_fichier": first(TacheExport),
            "corbeille_restaurer": 1,
        },
        "code": {  # a ``code`` is a framework code, a KPI code or a language code
            "referentiel": ref.code if ref else None,
            "paquet_exporter": ref.code if ref else None,
            "traductions": "en",
            "visu_kpi": kpi.code if kpi else None,
        },
    }


def parcourir(patterns, prefixe=""):
    for p in patterns:
        route = prefixe + str(p.pattern)
        if isinstance(p, URLResolver):
            yield from parcourir(p.url_patterns, route)
        elif isinstance(p, URLPattern):
            yield route, p


def valeur(ech, nom_url, param):
    v = ech.get(param)
    if isinstance(v, dict):
        # exact URL name first, then the longest name that starts like it (referentiel_contenu, referentiel_reglages...)
        if nom_url in v:
            return v[nom_url]
        for cle in sorted(v, key=len, reverse=True):
            if cle and nom_url.startswith(cle):
                return v[cle]
        return v.get("")  # the example for every other page
    return v


def main():
    ech = echantillons()
    routes, ignorees = [], []
    for route, p in parcourir(get_resolver().url_patterns):
        nom = p.name or ""
        if route.startswith("admin/") and route != "admin/":
            continue  # the expert mode (Django admin, read-only): its home page is enough
        if nom in IGNORED:
            ignorees.append({"route": route, "reason": IGNORED[nom]})
            continue
        url, manque = "/" + route, None
        for param in re.findall(r"<(?:\w+:)?(\w+)>", route):
            v = valeur(ech, nom, param)
            if v is None:
                manque = f"no example of <{param}> in this demo"
                break
            url = re.sub(r"<(?:\w+:)?" + param + ">", str(v), url)
        if manque:
            ignorees.append({"route": route, "reason": manque})
            continue
        libre = nom in LS.LIBRES or nom in LS.PARAMETRES_LIBRES or nom in PUBLIC
        routes.append({
            "name": nom, "route": route, "url": url,
            "readonly": {"reader": libre or nom in LS.PAGES_LECTEUR, "auditor": libre or nom in LS.PAGES_AUDITEUR},
            "free": libre or route == "admin/",  # open even without signing in (sign-in page, language, logo, health, privacy)
            "write_allowed": nom in LS.ECRITURES_PERMISES or libre,  # a read-only role may post here (own preferences, downloads)
            **({"get_status": POST_ONLY[nom]} if nom in POST_ONLY else {}),
        })
    json.dump({"routes": routes, "skipped": ignorees}, sys.stdout, indent=1, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
