"""Measure every main page and export for a given role: SQL queries, server CPU time, size of the page.

    DATA_DIR=/folder/of/the/database python3 qa/load/measure_pages.py [--filter TEXT] [--reps 3] [--out result.json]
        [--skip-exports] [--max-cpu-ms N] [--max-queries N]

Runs in the process of Django (test client, no network): the time measured is the CPU time of the server code
(``time.process_time``), without the network and without the browser. Works on the plain demo (``load_demo``) as well as
on the big database built by ``qa/load/make_big_data.py``: the accounts ``contrib001`` and ``valid000`` of that database
are used when they exist, the demo accounts otherwise.

For each (page, role) the page is called once to warm up, once with the queries counted, then ``--reps`` times for the
CPU time (median). Columns of the table:

  queries   number of SQL queries of one call
  sql ms    time the database took for them
  cpu ms    median CPU time of the whole call (SQL included)
  kB        size of the page; gz kB  size after compression (what travels)

A status other than 200 is shown in the table as it is (a redirect, a refusal): look at it before trusting the line.
Read only: nothing is written (the pages are GET; exports are downloaded, not saved; the MCP lines, measured last, run
inside a transaction rolled back at the end, since a call creates a token and is logged). "wall ms" is the elapsed time
of the call: under PostgreSQL the time of the database server is in it, not in "cpu ms". With --max-cpu-ms or
--max-queries, exit code 1 if a page goes beyond (a budget to give to the measurement of a release).
"""
import argparse
import contextlib
import gzip
import json
import os
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.db import connection, transaction
from django.test import Client
from django.test.utils import CaptureQueriesContext

from collecte import exports as E
from collecte.models import Campagne, ReglageExport, VueVisu
from referentiel.models import KPI, Attribution, Niveau, Organisation, Utilisateur


def cas(o):
    """The list of (page, role, request) to measure, built from the content of the database."""
    camp = Campagne.objects.filter(exercice=2026).order_by("pk").first() or Campagne.objects.order_by("-pk").first()
    if camp is None:
        sys.exit("No campaign in this database: load the demo first (manage.py load_demo).")
    orgs = Organisation.objects.all()
    site = orgs.filter(niveau_id=Niveau.SITE, actif=True).order_by("pk").first()
    groupe = orgs.filter(niveau_id=Niveau.GROUP).first()
    kpi = KPI.objects.filter(granularite_id=Niveau.SITE, type_saisie_id="Saisi", actif=True).order_by("code").first()
    contrib = "contrib001" if Utilisateur.objects.filter(username="contrib001").exists() else "contributeur"
    valid = "valid000" if Utilisateur.objects.filter(username="valid000").exists() else "validateur"
    attr = Attribution.objects.filter(utilisateur__username=contrib, role="contributeur", kpi__granularite_id="Site").first()

    def g(path):
        return ("GET", path)

    liste = [
        ("Entry panel (own cell)", contrib, g(f"/saisie/{camp.pk}/{attr.kpi_id}/{attr.organisation_id}/")) if attr else None,
        ("Data entry", contrib, g("/saisie/")),
        ("For me", contrib, g("/pour-moi/")),
        ("Dashboard", contrib, g("/tableau-de-bord/")),
        ("Data entry", valid, g("/saisie/")),
        ("For me", valid, g("/pour-moi/")),
        ("For me, rest of the list (?reste=1)", valid, g("/pour-moi/?reste=1")),
        ("For me by theme", valid, g("/pour-moi/?groupe=theme")),
        ("For me by theme, rest (?reste=1)", valid, g("/pour-moi/?groupe=theme&reste=1")),
        ("Dashboard", valid, g("/tableau-de-bord/")),
        ("Consistency", valid, g("/coherence/")),
        ("History (admin) filter q", "admin", g("/administration/journal/?q=1234")),
        ("History (admin) year 2025", "admin", g("/administration/journal/?exercice=2025")),
        ("History (admin) objet=Reponse", "admin", g("/administration/journal/?objet=Reponse")),
        ("History (admin) one organisation", "admin", g(f"/administration/journal/?org={site.pk}")),
        ("History (admin) year 2025 + organisation", "admin", g(f"/administration/journal/?exercice=2025&org={site.pk}")),
        ("Home /", "admin", g("/")),
        ("Data entry (one site)", "admin", g(f"/saisie/?org={site.pk}")),
        ("Data entry (group)", "admin", g(f"/saisie/?org={groupe.pk}")),
        ("Data entry (one site, +calculated)", "admin", g(f"/saisie/?org={site.pk}&calc=1")),
        ("Data entry (one site)", "validateur", g(f"/saisie/?org={site.pk}")),
        ("Data entry (one site)", "auditeur", g(f"/saisie/?org={site.pk}")),
        ("For me", "admin", g("/pour-moi/")),
        ("For me, rest of the list (?reste=1)", "admin", g("/pour-moi/?reste=1")),
        ("For me by theme", "admin", g("/pour-moi/?groupe=theme")),
        ("Entry panel", "admin", g(f"/saisie/{camp.pk}/{kpi.code}/{site.pk}/")),
        ("Dashboard", "admin", g("/tableau-de-bord/")),
        ("Dashboard", "lecteur", g("/tableau-de-bord/")),
        ("Consolidation", "admin", g("/tableau-de-bord/consolidation/")),
        ("Consolidation", "lecteur", g("/tableau-de-bord/consolidation/")),
        ("Consolidation Excel", "admin", g("/tableau-de-bord/consolidation/excel/")),
        ("Consistency", "admin", g("/coherence/")),
        ("Reminders", "admin", g("/tableau-de-bord/relances/")),
        ("History (auditor)", "auditeur", g("/historique/")),
        ("History (auditor) year 2025", "auditeur", g("/historique/?exercice=2025")),
        ("History (restricted auditor)", "audit000", g("/historique/")),
        ("History (restricted auditor) year 2025", "audit000", g("/historique/?exercice=2025")),
        ("History (admin)", "admin", g("/administration/journal/")),
        ("KPI catalogue", "admin", g("/referentiel/")),
        ("KPI catalogue JSON", "admin", g("/referentiel/kpis.json")),
        ("KPI sheet", "admin", g(f"/referentiel/kpi/{kpi.code}/")),
        ("Organisations", "admin", g("/administration/organisations/")),
        ("Accounts", "admin", g("/administration/comptes/")),
        ("Assignments", "admin", g("/administration/attributions/")),
        ("Assignments (one KPI)", "admin", g(f"/administration/attributions/?kpi={kpi.code}")),
        ("Campaigns", "admin", g("/administration/campagnes/")),
        ("Administration home", "admin", g("/administration/")),
        ("Forced values", "admin", g("/valeurs-forcees/")),
        ("Visualisation home", "admin", g("/visualisation/")),
        ("Visualisation home", "lecteur", g("/visualisation/")),
        ("Visualisation catalogue JSON", "admin", g("/visualisation/donnees/catalogue/")),
        ("Import / Export (my exports)", "admin", g("/import-export/")),
        ("Import / Export (my exports)", contrib, g("/import-export/")),
        ("Import (page)", contrib, g("/import-export/importer/")),
        ("Help", contrib, g("/aide/")),
        ("Help", "admin", g("/aide/")),
        ("My account", contrib, g("/mon-compte/")),
        ("My account", "admin", g("/mon-compte/")),
        ("Evidence to delete", "admin", g("/administration/preuves/")),
        ("Settings > Assistants", "admin", g("/administration/parametres/assistants/")),
        ("Settings > AI assistant", "admin", g("/administration/parametres/ia/")),
        ("File to fill in (xlsx)", "admin", g(f"/import-export/modele/?campagne={camp.pk}")),
        ("File to fill in (xlsx)", contrib, g(f"/import-export/modele/?campagne={camp.pk}")),
        ("File to fill in (xlsx, blank)", "admin", g(f"/import-export/modele/?campagne={camp.pk}&vierge=1")),
    ]
    for v in list(VueVisu.objects.order_by("pk")[:4]):
        liste += [(f"Visualisation view {v.pk} (page)", "admin", g(f"/visualisation/vues/{v.pk}/")),
                  (f"Visualisation view {v.pk} data JSON", "admin", g(f"/visualisation/vues/{v.pk}/donnees/")),
                  (f"Visualisation view {v.pk} data JSON", "lecteur", g(f"/visualisation/vues/{v.pk}/donnees/"))]
    if not o.skip_exports:
        liste += [(f"Export {nom}", "admin", ("EXPORT", nom)) for nom, _, _ in E.PRESETS.values()]
    # MCP: run last, inside a transaction rolled back at the end (a token is created, each call is logged)
    case_mcp = {"campaign_id": camp.pk, "kpi_code": kpi.code, "organisation_id": site.pk}
    liste += [("MCP tools/list", "admin", ("MCP", "tools/list", {})),
              ("MCP get_value", "admin", ("MCP", "tools/call", {"name": "get_value", "arguments": case_mcp})),
              ("MCP get_value", valid, ("MCP", "tools/call", {"name": "get_value", "arguments": case_mcp}))]
    if attr:
        liste.append(("MCP get_value (own cell)", contrib, ("MCP", "tools/call", {"name": "get_value", "arguments": {
            "campaign_id": camp.pk, "kpi_code": attr.kpi_id, "organisation_id": attr.organisation_id}})))
    return [c for c in liste if c]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--filter", default="", help="measure only the lines whose page or role contains this text")
    ap.add_argument("--reps", type=int, default=3, help="calls for the CPU time (median), default 3")
    ap.add_argument("--out", default="", help="write the figures in this JSON file")
    ap.add_argument("--skip-exports", action="store_true", help="do not measure the exports (the slowest)")
    ap.add_argument("--max-cpu-ms", type=int, help="exit code 1 if a page takes more CPU time than this")
    ap.add_argument("--max-queries", type=int, help="exit code 1 if a page runs more SQL queries than this")
    o = ap.parse_args()
    if not (os.environ.get("DATA_DIR") or os.environ.get("DATABASE_URL") or os.environ.get("SQLITE_FILE")):
        sys.exit("Set DATA_DIR (the folder of a demo or of the big database) or DATABASE_URL.")
    users = {u.username: u for u in Utilisateur.objects.all() if u.username in
             {"admin", "validateur", "contributeur", "lecteur", "auditeur", "contrib001", "valid000", "audit000"}}
    clients = {}

    def client(role):
        if role not in clients:
            c = Client(SERVER_NAME="localhost", HTTP_ACCEPT_ENCODING="gzip")
            c.force_login(users[role])
            clients[role] = c
        return clients[role]

    jetons = {}
    mcp = Client(SERVER_NAME="localhost")

    def appeler(role, spec):
        if spec[0] == "MCP":
            if role not in jetons:
                from serveur_mcp import jetons as JT
                jetons[role] = JT.creer(users[role], "measure", JT.durees_proposees()[0])[0]
            corps = json.dumps({"jsonrpc": "2.0", "id": 1, "method": spec[1], "params": spec[2]})
            r = mcp.post("/mcp/", corps, content_type="application/json", secure=True,
                         HTTP_AUTHORIZATION=f"Bearer {jetons[role]}")
            if r.status_code == 200 and "error" in r.json():
                raise RuntimeError(r.json()["error"])
            return r
        c = client(role)
        if spec[0] == "EXPORT":
            m = ReglageExport.objects.get(nom=spec[1])
            return c.get(f"/import-export/exporter/?modele={m.pk}&telecharger=1", secure=True)
        return c.get(spec[1], secure=True)

    res = []
    pile, mcp_ouvert = contextlib.ExitStack(), False
    print(f"{'page':44} {'role':12} {'status':>6} {'queries':>8} {'sql ms':>7} {'cpu ms':>7} {'wall ms':>7} {'kB':>6} {'gz kB':>6}")
    for nom, role, spec in cas(o):
        if o.filter and o.filter.lower() not in (nom + role).lower():
            continue
        if role not in users:
            continue
        if spec[0] == "MCP" and not mcp_ouvert:
            mcp_ouvert = True
            for alias in ("default", "commun"):  # tout ce que les appels MCP écrivent est annulé à la fin
                pile.enter_context(transaction.atomic(using=alias))
                pile.callback(transaction.set_rollback, True, using=alias)
            from serveur_mcp.models import ReglageMCP
            ReglageMCP.objects.update_or_create(pk=1, defaults={"actif": True, "appels_minute": 30000})
        try:
            r = appeler(role, spec)  # warm up (caches, compiled templates)
            status = r.status_code
            with CaptureQueriesContext(connection) as ctx:
                r = appeler(role, spec)
            nq = len(ctx.captured_queries)
            tq = sum(float(q["time"]) for q in ctx.captured_queries)
            cpus, murs = [], []
            for _ in range(o.reps):
                t, m = time.process_time(), time.perf_counter()
                r = appeler(role, spec)
                cpus.append(time.process_time() - t)
                murs.append(time.perf_counter() - m)
            corps = b"".join(r.streaming_content) if getattr(r, "streaming", False) else r.content
            zippe = r.get("Content-Encoding") == "gzip"
            brut = len(gzip.decompress(corps)) if zippe else len(corps)
            gz = len(corps) if zippe else len(gzip.compress(corps, 6))
            ligne = dict(page=nom, role=role, status=status, queries=nq, sql_ms=round(tq * 1000),
                         cpu_ms=round(statistics.median(cpus) * 1000),
                         wall_ms=round(statistics.median(murs) * 1000), kb=round(brut / 1024), gz_kb=round(gz / 1024))
            print(f"{nom:44} {role:12} {status:>6} {nq:>8} {ligne['sql_ms']:>7} {ligne['cpu_ms']:>7} {ligne['wall_ms']:>7} {ligne['kb']:>6} {ligne['gz_kb']:>6}", flush=True)
        except Exception as e:  # a line that fails must not stop the others
            ligne = dict(page=nom, role=role, status="ERROR " + repr(e)[:80])
            print(f"{nom:44} {role:12} {ligne['status']}", flush=True)
        res.append(ligne)
    pile.close()
    if o.out:
        with open(o.out, "w") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
    lourdes = [x for x in res if isinstance(x.get("status"), str)
               or (o.max_cpu_ms and x.get("cpu_ms", 0) > o.max_cpu_ms) or (o.max_queries and x.get("queries", 0) > o.max_queries)]
    for x in lourdes:
        print("BEYOND THE BUDGET OR IN ERROR:", x)
    sys.exit(1 if lourdes else 0)


if __name__ == "__main__":
    main()
