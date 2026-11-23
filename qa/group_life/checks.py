"""Checks played after each reporting year of the scenario (``scenario.py``).

after_year     data check (``check_data``), recalculation through the "Recalculate" button identical to the stored values,
               each total equal to the sum of its detail, expected consistency alerts, completion rates consistent
               between Data entry, Dashboard and Reminders, rights by role, export then import of the file without any
               difference
after_closure  data check, nobody writes in a closed campaign
second_space   a second space with its own group: entry, official workbook export, nothing visible from one to the other
backup_restore backup from the Hosting page, a change, restore from the Hosting page: everything back as saved
"""
import re
from decimal import Decimal

from espaces import contexte as E

from .actors import Actor, text_of

D = Decimal
# Error log lines that the scenario causes on purpose (none for now: every error line is reported).
EXPECTED_LOG_ERRORS = ()


def short(html, n=300):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html or "", flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    for marker in ("À vérifier", "To check", "Erreur", "error", "refus"):
        i = t.find(marker)
        if i >= 0:
            return t[max(0, i - 40):i + n]
    return t[:n]


# ---------------------------------------------------------------------------------------------------- data check
def data_check(g, label):
    from collecte import controle_donnees as CD

    with g.db():
        res = CD.controler()
    for p in res["problems"]:
        if p["severity"] == CD.ERREUR and p["count"]:
            g.log.anomaly(f"check_data:{p['check']}", f"{label}: {p['message']} — " + " | ".join(p["examples"][:4]))
    return res


# ---------------------------------------------------------------------------------------------------- recalculation
CALC = ("calcul", "agregation", "cumul")


def snapshot(g, period_ids):
    from collecte.models import Reponse

    with g.db():
        return {(r.periode_id, r.kpi_id, r.organisation_id): (r.valeur, r.texte, r.non_applicable, r.statut, r.origine)
                for r in Reponse.objects.filter(periode_id__in=period_ids)}


def recalculation_identical(g, campaigns):
    from collecte.models import Campagne

    with g.db():
        cs = list(Campagne.objects.filter(pk__in=campaigns).exclude(statut="cloturee"))
        periods = {c.periode_id for c in cs}
    if not cs:
        return
    before = snapshot(g, periods)
    for c in cs:
        g.admin.admin_panel("collecte:admin_campagne", c.pk, data={"action": "recalculer"})
    after = snapshot(g, periods)
    diffs = [f"{k[1]}@{k[2]} p{k[0]}: {before.get(k)} -> {after.get(k)}" for k in set(before) | set(after)
             if before.get(k) != after.get(k) and (before.get(k) is None or before[k][4] in CALC or after.get(k) is None or after[k][4] in CALC)]
    if diffs:
        g.log.anomaly("recalculation_changes_values", f"{len(diffs)} cell(s) change with « Recalculate »: " + " | ".join(sorted(diffs)[:6]))


# ---------------------------------------------------------------------------------------------------- totals
def totals_equal_detail(g, campaigns):
    """For each "Sum" KPI, each stored total = sum of the children open during the period (independent check)."""
    from django.db.models import Q

    from collecte.calcul import ouverte
    from collecte.models import Campagne, Reponse
    from parametres import niveaux as N
    from referentiel.models import KPI, Organisation

    with g.db():
        rangs = N.rangs()
        orgs = {o.pk: o for o in Organisation.objects.all()}
        kids = {}
        for o in orgs.values():
            kids.setdefault(o.parent_id, []).append(o)
        sums = {k.code: k for k in KPI.objects.filter(methode_agregation="Somme", actif=True)}

        def has_level(o, level):
            """An organisation without any organisation of the KPI's level below it does not make a total incomplete
            (README: « a country just created, or sites attached directly »)."""
            return o.niveau_id == level or any(has_level(x, level) for x in kids.get(o.pk, []))
        bad = []
        for c in Campagne.objects.filter(pk__in=campaigns).select_related("periode"):
            p = c.periode
            cells = {(r.kpi_id, r.organisation_id): r for r in Reponse.objects.filter(periode=p, kpi_id__in=sums)}
            # a closed organisation without any value in the period does not count (README, "Aggregation in the tree")
            with_values = set(Reponse.objects.filter(periode=p).filter(Q(valeur__isnull=False) | Q(non_applicable=True) | ~Q(texte=""))
                              .values_list("organisation_id", flat=True))
            for (kpi, org_id), r in cells.items():
                k = sums[kpi]
                o = orgs[org_id]
                if r.origine != "agregation" or r.statut != "calcule" or k.na_compte_zero:
                    continue
                ch = [x for x in kids.get(org_id, []) if ouverte(x, p) and rangs.get(x.niveau_id, 0) <= rangs.get(k.granularite_id, 0)
                      and (x.actif or x.pk in with_values) and has_level(x, k.granularite_id)]
                vals = [cells.get((kpi, x.pk)) for x in ch]
                if any(v is None or (v.valeur is None and not v.non_applicable) for v in vals):
                    bad.append(f"{kpi}@{o.nom} {p}: total {r.valeur} although a child has no value")
                    continue
                expected = sum((v.valeur for v in vals if not v.non_applicable), D(0))
                if r.valeur is None or abs(r.valeur - expected) > D("0.0001") * max(D(1), abs(expected)):
                    bad.append(f"{kpi}@{o.nom} {p}: total {r.valeur}, sum of the detail {expected}")
    if bad:
        g.log.anomaly("total_not_sum_of_detail", f"{len(bad)} total(s): " + " | ".join(bad[:6]))


# ---------------------------------------------------------------------------------------------------- alerts
def expected_alerts(g, campaigns):
    from collecte.models import Alerte

    with g.db():
        for c, kpi, org, control in g.planted:
            if c not in campaigns:
                continue
            if not Alerte.objects.filter(campagne_id=c, kpi_id=kpi, organisation_id=org, controle__startswith=control).exists():
                g.log.anomaly("expected_alert_missing", f"{kpi}@{org} campaign {c}: no « {control} » alert")


# ---------------------------------------------------------------------------------------------------- completion rates
def completion_consistent(g, campaign_id):
    """For each contributor: what is left to do is the same on Data entry (« For me »), the Dashboard and Reminders;
    for the administrator: the same on Data entry and the Dashboard."""
    adm = g.admin
    d = adm.get(adm.url("collecte:tableau_de_bord"), campagne=campaign_id)
    e = adm.get(adm.url("collecte:saisie"), campagne=campaign_id)
    if d.context and e.context and "total" in d.context and e.context.get("etat") is not None:
        t, et = d.context["total"], e.context["etat"]  # banner of Data entry: the whole scope of the person (S.Reste)
        if (et.total, et.valide) != (t.total, t.valide):
            g.log.anomaly("completion_mismatch", f"administrator campaign {campaign_id}: Data entry banner {et.valide}/{et.total} "
                          f"validated, dashboard {t.valide}/{t.total}")
    r = adm.get(adm.url("collecte:relances"), campagne=campaign_id)
    remind = {af.personne.username: (af.nb_a_saisir if hasattr(af, "nb_a_saisir") else None, af) for af in (r.context.get("liste") or [])} \
        if r.context else {}
    for e, username in sorted(g.w.contributor_of.items())[:6]:
        a = g.a(username)
        d = a.get(a.url("collecte:tableau_de_bord"), campagne=campaign_id)
        if not d.context or "total" not in d.context:
            continue
        t = d.context["total"]
        left_dashboard = t.a_saisir + t.brouillon
        af = remind.get(username, (None, None))[1]
        left_remind = sum(len(ls) for camp, ls in af.campagnes if camp.pk == campaign_id) if af is not None else 0
        e = a.get(a.url("collecte:pour_moi"), campagne=campaign_id)
        et = e.context.get("etat") if e.context else None
        if et is not None and e.context["campagne"].pk == campaign_id and (et.total, et.valide) != (t.total, t.valide):
            g.log.anomaly("completion_mismatch", f"{username} campaign {campaign_id}: Data entry banner {et.valide}/{et.total} "
                          f"validated, dashboard {t.valide}/{t.total}")
        if left_dashboard != left_remind and d.context["campagne"].pk == campaign_id:
            g.log.anomaly("completion_mismatch", f"{username} campaign {campaign_id}: dashboard {t.a_saisir} to fill + "
                          f"{t.brouillon} drafts, reminders {left_remind} line(s)")


# ---------------------------------------------------------------------------------------------------- rights
ADMIN_ONLY = ["collecte:admin_campagnes", "collecte:admin_organisations", "collecte:admin_comptes", "collecte:admin_journal",
              "collecte:referentiel_kpi_nouveau", "parametres:hebergement"]


def rights(g, campaign_id):
    """Pages reserved for the administrator; writes refused to the reader, the auditor and to people out of scope."""
    w = g.w
    seen_roles = set()
    for username, role in sorted(w.users.items()):
        if role == "admin" or (getattr(g, "quick", False) and role in seen_roles):
            continue
        seen_roles.add(role)
        a = g.a(username)
        for name in ADMIN_ONLY:
            r = a.client.get(a.url(name))
            if r.status_code >= 500:
                g.log.anomaly("http_500", f"{username} GET {name}")
            elif r.status_code == 200:
                g.log.anomaly("admin_page_open", f"{username} ({role}) opens {name}")
        for name in ("collecte:saisie", "collecte:tableau_de_bord", "collecte:coherence", "collecte:echanges", "collecte:visu",
                     "collecte:pour_moi", "collecte:consolidation", "collecte:historique", "collecte:referentiel"):
            r = a.client.get(a.url(name))
            if r.status_code >= 500:
                g.log.anomaly("http_500", f"{username} GET {name} -> {r.status_code}")
    if campaign_id is None:
        return
    site = w.sites[0]
    entity = w.entities[-1]
    before = g.answer(campaign_id, "WATER", site)
    for username in (f"{w.prefix}reader", f"{w.prefix}auditor", w.contributor_of[entity]):
        ok, html, st = g.a(username).enter(campaign_id, "WATER", site, "777", validate=True)
        after = g.answer(campaign_id, "WATER", site)
        if ok or (after and after.valeur == D(777)):
            g.log.anomaly("write_out_of_rights", f"{username} wrote WATER@{site} ({st})")
    after = g.answer(campaign_id, "WATER", site)
    if (before and before.valeur) != (after and after.valeur):
        g.log.anomaly("write_out_of_rights", f"WATER@{site} changed {before and before.valeur} -> {after and after.valeur}")
    # validator of another country
    country_of_site = g.org(site).parent_id
    while country_of_site and g.org(country_of_site).niveau_id != "Country":  # a level may have been inserted (year 4)
        country_of_site = g.org(country_of_site).parent_id
    other = next((v for c, v in w.validator_of.items() if c != country_of_site), None)
    if other:
        ok, html, st = g.a(other).enter(campaign_id, "WATER", site, "778")
        if ok:
            g.log.anomaly("write_out_of_rights", f"validator {other} wrote outside their countries")


# ---------------------------------------------------------------------------------------------------- export, import
def export_reimport(g, campaign_id, year):
    """The administrator exports the year ("Database" layout), then imports the file as it is: nothing to change."""
    from collecte.models import Campagne

    with g.db():
        c = Campagne.objects.select_related("referentiel").get(pk=campaign_id)
    data = g.admin.export(presentation="base", format="xlsx", exercices=[str(year)], periodes=["annee"], referentiel=c.referentiel_id,
                          contenus=["valide", "brouillon", "a_saisir", "calcule"],
                          niveaux=["Group", "Country", "Entity", "Site"], types=["saisie", "herite", "calcul"])
    if not data:
        return
    from django.core.files.uploadedfile import SimpleUploadedFile

    a = g.admin
    r = a.post(a.url("collecte:echanges_importer"), {"action": "verifier", "fichier": SimpleUploadedFile("export.xlsx", data),
                                                     "campagne": str(campaign_id)}, fetch=False)
    preview = r.context.get("analyse") if r.context else None
    if preview is None:
        g.log.anomaly("reimport_no_preview", f"{year}: {short(text_of(r))}")
        return
    a.post(a.url("collecte:echanges_importer"), {"action": "annuler"}, fetch=False)
    changes = [l for l in preview.lignes if l.action in ("creer", "modifier")]
    rejects = [l for l in preview.lignes if l.action == "rejet"]
    if changes:
        g.log.anomaly("reimport_changes", f"{year}: re-importing the export would change {len(changes)} value(s): "
                      + " | ".join(_line(l) for l in changes[:5]))
    if rejects:
        g.log.anomaly("reimport_rejects", f"{year}: {len(rejects)} line(s) of the export rejected on import: "
                      + " | ".join(_line(l) for l in rejects[:5]))
    g.log.event(f"export {year} re-imported: {len(preview.lignes)} line(s), {len(changes)} change(s), {len(rejects)} reject(s)")


def _line(l):
    return " ".join(str(getattr(l, x, "")) for x in ("kpi_id", "kpi", "organisation", "periode", "valeur", "motif") if getattr(l, x, ""))[:160]


# ---------------------------------------------------------------------------------------------------- after a year
def after_year(g, year, campaigns, label="", light=False):
    """All the checks; ``light`` (version of the test suite, years other than the second): data check and totals."""
    step = g.log.step
    g.log.step = f"{year} checks{' ' + label if label else ''}"
    data_check(g, f"{year} {label}")
    totals_equal_detail(g, campaigns)
    if not light:
        recalculation_identical(g, campaigns)
        data_check(g, f"{year} after Recalculate")
        expected_alerts(g, campaigns)
        completion_consistent(g, campaigns[0])
        rights(g, campaigns[0])
        export_reimport(g, campaigns[0], year)
    g.log.step = step


def after_closure(g, year, campaigns):
    step = g.log.step
    g.log.step = f"{year} closed"
    data_check(g, f"{year} closed")
    w = g.w
    site = w.sites[0]
    before = g.answer(campaigns[0], "WATER", site)
    ok, html, st = g.a(w.contributor_of[w.entities[0]]).enter(campaigns[0], "WATER", site, "999")
    ok2, html2, st2 = g.admin.enter(campaigns[0], "WATER", site, "998")
    after = g.answer(campaigns[0], "WATER", site)
    if ok or ok2 or (before and before.valeur) != (after and after.valeur):
        g.log.anomaly("write_in_closed_campaign", f"WATER@{site}: {before and before.valeur} -> {after and after.valeur}")
    totals_equal_detail(g, campaigns)
    g.log.step = step


# ---------------------------------------------------------------------------------------------------- second space
def second_space(g, code):
    """Second space: its own group (another prefix), a campaign opened from the page, entries, the official workbook
    export; nothing of the main space is visible from it, and the other way round."""
    from django.urls import reverse

    from espaces.models import Espace

    from . import scenario as SC
    from . import world as W

    with E.toutes_les_bases():
        exists = Espace.objects.filter(code=code).exists()
    if not exists:
        r = g.admin.client.post("/administration/espaces/nouveau/", {"nom": "Second division", "code": code, "identite": "on"})
        if r.status_code >= 500:
            g.log.anomaly("http_500", f"space creation -> {r.status_code}")
        with E.toutes_les_bases():
            if not Espace.objects.filter(code=code).exists():
                g.log.anomaly("space_not_created", short(text_of(r)))
                return
    quick = getattr(g, "quick", False)
    with E.activer(code):
        w2 = W.build("micro", g.w.seed + 1, prefix="s2-", group_name="Second division group")
        if not quick:  # VS template of the library, for the official workbook
            from collecte import paquets as PQ

            a = PQ.analyser(PQ.fourni("vs_base.json").paquet, fourni=True)
            PQ.appliquer(None, a)
    g2 = SC.Game(w2, g.log, space=code)
    c = g2.create_campaign(W.ANNUAL, 2025)
    g2.campaign_action(c, "ouvrir", "ouverte")
    values = SC.year_values(g2, 2025)
    for e in w2.entities:
        g2.fill(w2.contributor_of[e], c, values, salt="s2")
    # official workbook (Import / Export › Official formats)
    from collecte.models import Campagne

    with E.activer(code):
        p = Campagne.objects.get(pk=c).periode_id
        from collecte import export_officiel as XO

        formats = XO.formats_disponibles()
        fmt = formats[0].CODE if formats else None
    adm2 = g2.admin
    url = adm2.url("collecte:export_officiel")
    adm2.get(url)
    if quick:
        pass
    elif not fmt:
        g.log.anomaly("official_format_missing", "no official format offered although the VS template is installed")
    else:
        r = adm2.post(url, {"format": fmt, "organisation": w2.group, "periode": p, "langue": "fr", "action": "telecharger"},
                      fetch=False, expect=(200,))
        if "spreadsheetml" not in r.get("Content-Type", ""):
            g.log.anomaly("official_export_no_file", short(text_of(r)))
    # isolation: pages of each space show nothing of the other
    main_names = [g.org(g.w.group).nom, g.org(g.w.entities[0]).nom]
    for name in ("collecte:saisie", "collecte:tableau_de_bord", "collecte:admin_organisations"):
        html = text_of(adm2.get(adm2.url(name), expect=None))
        for n in main_names:
            if n in html:
                g.log.anomaly("space_leak", f"« {n} » of the main space visible on {name} of space {code}")
        html = text_of(g.admin.get(g.admin.url(name), expect=None))
        if "Second division group" in html:
            g.log.anomaly("space_leak", f"second space visible on {name} of the main space")
    with E.activer(code):
        from collecte.models import Reponse

        n2 = Reponse.objects.count()
    g.log.event(f"second space {code}: {n2} answer(s)")
    g2.quick = quick
    after_year(g2, 2025, [c], label="second space", light=quick)
    del reverse


# ---------------------------------------------------------------------------------------------------- backup, restore
def backup_restore(g):
    """Hosting: « Back up now », a change, then restore that backup from the page: everything back as it was."""
    from collecte.models import Journal, Reponse
    from parametres import sauvegardes as SV

    adm = g.admin
    with g.db():
        before = snapshot(g, list(Reponse.objects.values_list("periode_id", flat=True).distinct()))
        n_before = Reponse.objects.count()
    r = adm.post(adm.url("parametres:hebergement"), {"action": "sauvegarder"}, fetch=False)
    with g.db():
        archives = SV.archives()
    if not archives:
        g.log.anomaly("backup_not_created", short(text_of(r)))
        return
    name = archives[0].nom
    with g.db():
        Journal.objects.create(action="essai", objet="essai", objet_id="0")  # a change after the backup (any table)
        Reponse.objects.filter(pk=Reponse.objects.order_by("pk").values_list("pk", flat=True).first()).delete()
    from parametres.vues_hebergement import mot_confirmation

    with g.db():
        word = mot_confirmation()
    r = adm.post(adm.url("parametres:sauvegarde_restaurer", name), {"confirmation": word, "compris": "on"}, fetch=False)
    if r.status_code >= 500:
        g.log.anomaly("http_500", f"restore -> {r.status_code}")
    from django.db import connections

    for c in connections.all():
        c.close()
    with g.db():
        after = snapshot(g, list(Reponse.objects.values_list("periode_id", flat=True).distinct()))
        n_after = Reponse.objects.count()
    if before != after or n_before != n_after:
        diff = [k for k in set(before) | set(after) if before.get(k) != after.get(k)]
        g.log.anomaly("restore_differs", f"{n_before} answers before, {n_after} after; {len(diff)} differ: {diff[:4]}")
    g.log.event(f"backup {name} restored: {n_after} answers")
    Actor  # noqa: B018 (re-sign-in after a restore is done by the next request)
