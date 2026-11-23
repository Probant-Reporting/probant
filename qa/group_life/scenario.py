"""The life of the fictitious group over three reporting years, played through the pages of the tool.

``play(size, seed)`` builds the starting state (``world.build``), then plays the years one after the other. Each year
ends with the checks of ``checks.py``. Every anomaly goes to the returned ``Log``; the scenario never stops on one.

Timeline (detail in README.md):

year 1  campaign created and opened by the administrator; consistency rule created; entries with mistakes and
        corrections, ambiguous separator, N/A with and without a comment, evidence, table answers; import with rejected
        lines; blocking rule refused then corrected; validator validates; administrator clears, puts back to draft, the
        contributor validates again; review, closure.
year 2  monthly framework switched on; annual and 12 monthly campaigns; KPI added, formula changed, assignments; a site
        closes in June, a site opens, an entity moves to another country; monthly values imported, cumulated in the year;
        variance above the threshold justified; forced value asked and accepted; reminders; closure of the months and the
        year; correction imported in the closed year; reopening and closing again.
year 3  KPI made inactive, KPI added; library template installed then updated; table answers; reminders; an assistant
        (MCP server) reads and changes a cell like the entry panel; closure.
second space: its own administrator, framework and campaign; nothing of one space is visible in the other.
"""
import datetime
from decimal import Decimal

from django.utils import timezone

from espaces import contexte as E

from . import checks as CK
from . import world as W
from .actors import Actor, Log, text_of, xlsx_bytes

D = Decimal


# ---------------------------------------------------------------------------------------------------- values
def base_value(w, kpi, org_id, year, month=None):
    """Value of a cell, deterministic (seed, KPI, organisation, period)."""
    r = w.rng("v", kpi, org_id)
    size = r.uniform(0.5, 3)
    growth = 1 + (year - 2023) * r.uniform(-0.05, 0.08)
    base = {"ELEC": 120000, "GAS": 80000, "WATER": 900, "WASTE": 40, "ACC": 2, "HEAD": 150, "WOMEN": 60, "TRAIN": 2000,
            "RENEW": 30000, "FE": 0.052, "REV": 250}.get(kpi, 100)
    v = base * size * growth
    if month is not None:
        v = v / 12 * (1.25 if month in (1, 2, 12) else 0.85 if month in (6, 7, 8) else 1)
    if kpi in ("ACC", "HEAD", "WOMEN"):
        return D(int(round(v)))
    if kpi == "FE":
        return D("0.052") + D(year - 2023) * D("0.001")
    return D(str(round(v, 1 if kpi in ("WASTE", "REV") else 0)))


def _empty(v):
    """Field left empty in a form (0 is a value, False an unchecked box)."""
    return v is None or v is False or (isinstance(v, str) and v == "")


def fr(v):
    """Number written as a French contributor types it ("1234,5")."""
    return format(v, "f").replace(".", ",")


class Game:
    def __init__(self, w, log, space="principal"):
        self.w, self.log, self.space = w, log, space
        self.actors = {}
        self.planted = []  # expected alerts: (campaign id, kpi, org id, control)
        self.formula_changed = set()
        self.quick = False  # KPIs whose formula (or a source formula) changed during the life

    def a(self, username):
        if username not in self.actors:
            self.actors[username] = Actor(username, self.log, self.space)
        return self.actors[username]

    @property
    def admin(self):
        return self.a(f"{self.w.prefix}admin")

    def db(self):
        return E.activer(self.space)

    # -------------------------------------------------------------- read-only lookups (planning and verification)
    def campaign(self, ref, year, month=None):
        from collecte.models import Campagne

        with self.db():
            start = datetime.date(year, month or 1, 1)
            c = Campagne.objects.filter(referentiel_id=ref, periode__debut=start,
                                        periode__type="mois" if month else "annee").first()
            return c.pk if c else None

    def answer(self, campaign_id, kpi, org_id):
        from collecte.models import Campagne, Reponse

        with self.db():
            c = Campagne.objects.get(pk=campaign_id)
            return Reponse.objects.filter(periode_id=c.periode_id, kpi_id=kpi, organisation_id=org_id).first()

    def org(self, pk):
        from referentiel.models import Organisation

        with self.db():
            return Organisation.objects.get(pk=pk)

    def children(self, pk, active_only=True):
        from referentiel.models import Organisation

        with self.db():
            qs = Organisation.objects.filter(parent_id=pk)
            if active_only:
                qs = qs.filter(actif=True)
            return list(qs.order_by("rang", "pk").values_list("pk", flat=True))

    def owner(self, kpi, org_id):
        from referentiel.models import Attribution

        with self.db():
            a = Attribution.objects.filter(kpi_id=kpi, organisation_id=org_id, role="contributeur").select_related("utilisateur").first()
            return a.utilisateur.username if a else None

    def cells_of(self, username, campaign_id):
        """(kpi, org id) the person has to enter in the campaign (``saisie.cellules``, read only)."""
        from collecte import saisie as S
        from collecte.models import Campagne
        from referentiel.models import Utilisateur

        with self.db():
            u = Utilisateur.objects.get(username=username)
            c = Campagne.objects.select_related("referentiel", "periode").get(pk=campaign_id)
            return sorted(((k.code, o.pk) for k, o in S.cellules(u, personnel=True, campagne=c)), key=lambda x: (x[1], x[0]))

    # -------------------------------------------------------------- administrator actions
    def create_campaign(self, ref, year, all_periods=False, threshold="20"):
        today = timezone.localdate()
        data = {"action": "enregistrer", "referentiel": ref, "exercice": str(year), "rang": "1", "seuil_pct": threshold,
                "seuil_historique": "2", "date_ouverture": (today - datetime.timedelta(days=5)).isoformat(),
                "date_fin_saisie": (today + datetime.timedelta(days=40)).isoformat()}
        if all_periods:
            data["toutes"] = "on"
        r, html = self.admin.admin_panel("collecte:admin_campagne_nouvelle", data=data)
        ids = []
        for m in (range(1, 13) if all_periods else [None]):
            pk = self.campaign(ref, year, m)
            if pk is None:
                self.log.anomaly("campaign_not_created", f"{ref} {year} {m}: {html[:300]}")
            ids.append(pk)
        self.log.event(f"campaign(s) {ref} {year} created: {len(ids)}")
        return ids if all_periods else ids[0]

    def campaign_action(self, campaign_id, action, expect_status=None, **extra):
        """Administration › Campaigns: a status button. ``extra``: other fields of the form (``reouverture`` =
        "garder" or "recalculer" when a closed year is reopened; the page keeps the figures
        when nothing is sent)."""
        from collecte.models import Campagne

        r, html = self.admin.admin_panel("collecte:admin_campagne", campaign_id, data={"action": action, **extra})
        with self.db():
            st = Campagne.objects.get(pk=campaign_id).statut
        if expect_status and st != expect_status:
            self.log.anomaly("campaign_status", f"{action} on {campaign_id}: status {st}, expected {expect_status}")
        return st

    def set_end_date(self, campaign_id, days):
        """Administration › Campaigns: move the end date of the entry (days from today, negative: in the past)."""
        from collecte.models import Campagne

        with self.db():
            c = Campagne.objects.get(pk=campaign_id)
        end = timezone.localdate() + datetime.timedelta(days=days)
        start = min(c.date_ouverture or timezone.localdate() - datetime.timedelta(days=5), end - datetime.timedelta(days=1))
        self.admin.admin_panel("collecte:admin_campagne", campaign_id, data={
            "action": "enregistrer", "date_ouverture": start.isoformat(), "date_fin_saisie": end.isoformat(),
            "seuil_pct": str(int((c.seuil_ecart or 0) * 100)) if c.seuil_ecart is not None else "", "seuil_historique": "2"})

    def kpi_sheet(self, kpi_code, new=False, **changes):
        code = kpi_code
        """KPI sheet (catalogue): the form as the page shows it, with ``changes``. Returns True if saved."""
        from collecte import reglages as R
        from referentiel.models import KPI

        with self.db():
            form = R.KPIForm(instance=KPI() if new else KPI.objects.get(pk=code))
            data = {}
            for name in form.fields:
                v = form[name].value()
                if not _empty(v):
                    data[name] = v
            if not new:
                data["version"] = R.version_kpi(KPI.objects.get(pk=code))
        data.update(changes)
        data = {k: v for k, v in data.items() if not _empty(v)}
        url = self.admin.url("collecte:referentiel_kpi_nouveau") if new else self.admin.url("collecte:referentiel_kpi", code)
        r = self.admin.post(url, data)
        try:
            ok = r.json().get("ok")
        except ValueError:
            ok = False
        if not ok and "confirmer" not in data:  # changes that touch values: the sheet asks to confirm
            r = self.admin.post(url, {**data, "confirmer": "on"})
            try:
                ok = r.json().get("ok")
            except ValueError:
                ok = False
        if not ok:
            self.log.anomaly("kpi_sheet_refused", f"{code} {changes}: {CK.short(text_of(r))}")
        return ok

    def org_form(self, org_id=None, **changes):
        """Organisation form (Administration › Organisations). Returns the organisation id."""
        from collecte.administration import OrganisationForm
        from referentiel.models import Organisation

        with self.db():
            o = Organisation.objects.get(pk=org_id) if org_id else Organisation()
            form = OrganisationForm(instance=o)
            data = {}
            for name in form.fields:
                v = form[name].value()
                if not _empty(v):
                    data[name] = v.isoformat() if hasattr(v, "isoformat") else v
        data.update(changes)
        data = {k: v for k, v in data.items() if not _empty(v)}
        data["action"] = "enregistrer"
        url = self.admin.url("collecte:admin_organisation", org_id) if org_id else self.admin.url("collecte:admin_organisation_nouvelle")
        r = self.admin.post(url, data)
        with self.db():
            if org_id:
                return org_id
            o = Organisation.objects.filter(nom=changes.get("nom")).first()
        if o is None:
            self.log.anomaly("org_not_created", f"{changes}: {CK.short(text_of(r))}")
            return None
        return o.pk

    def assign(self, kpi_org_pairs, username, campaign_id, role="contributeur"):
        """Administration › Assignments: "Assign to…" on these cells, as contributor or (choice "Validators") as validator."""
        from referentiel.models import Utilisateur

        with self.db():
            u = Utilisateur.objects.get(username=username)
        r = self.admin.post_json(self.admin.url("collecte:attribuer"), {
            "cles": [f"{k}|{o}" for k, o in kpi_org_pairs], "utilisateur": u.pk, "campagne": campaign_id, "role": role,
            **({"format": "cellule"} if role != "contributeur" else {})})
        if r.status_code != 200 or not r.json().get("ok"):
            self.log.anomaly("assign_failed", f"{username} ({role}) {kpi_org_pairs[:3]}: {r.status_code}")
        return r.status_code == 200

    # -------------------------------------------------------------- entry by people
    def fill(self, username, campaign_id, value_of, validate=True, panel_share=1.0, year=None, salt=""):
        """A contributor fills their cells: part in the entry panel, the rest with one import file."""
        from referentiel.models import KPI

        actor = self.a(username)
        R = self.w.rng("fill", username, campaign_id, salt)
        with self.db():
            kinds = {k.code: k for k in KPI.objects.select_related("type_reponse")}
        cells = self.cells_of(username, campaign_id)
        by_import = []
        for kpi, org in cells:
            v = value_of(kpi, org)
            if v is None:
                continue
            if R.random() < panel_share or not kinds[kpi].est_numerique or kinds[kpi].preuve_obligatoire:
                self.enter_one(actor, campaign_id, kpi, org, v, validate, kinds[kpi])
            else:
                by_import.append((kpi, org, v))
        if by_import:
            self.import_values(actor, campaign_id, by_import, validate=validate)
        return len(cells)

    def enter_one(self, actor, campaign_id, kpi, org, v, validate, k):
        """One cell in the panel, with what a careful person does: evidence first when required, comment when the
        panel asks for it (variance with N-1 above the threshold)."""
        text = v if isinstance(v, str) else fr(v)
        if k.preuve_obligatoire:
            r = self.answer(campaign_id, kpi, org)
            if r is None or not r.preuves.exists():
                actor.enter(campaign_id, kpi, org, text)
                if not actor.evidence(campaign_id, kpi, org):
                    self.log.anomaly("evidence_refused", f"{actor} {kpi} {org}")
        ok, html, st = actor.enter(campaign_id, kpi, org, text, validate=validate)
        if not ok and validate and st == 200:
            # validation refused: the panel says why; the usual reason is the variance with N-1 (comment required)
            ok, html, st = actor.enter(campaign_id, kpi, org, text, comment="Activity change, checked with the site.", validate=True)
        if not ok:
            self.log.anomaly("entry_refused", f"{actor} {kpi} org {org} value {text!r}: {CK.short(html)}",
                             cell=(campaign_id, kpi, org))
        return ok

    def import_values(self, actor, campaign_id, rows, validate=False, extra=(), expect_rejects=0, period=None):
        """Import file "KPI ID / Organisation code / Period / Value / Comment" (one per row)."""
        from referentiel.models import Organisation

        with self.db():
            codes = dict(Organisation.objects.values_list("pk", "code"))
            names = dict(Organisation.objects.values_list("pk", "nom"))
        lines = [["KPI ID", "Organisation code", "Organisation", "Period", "Value", "Comment"]]
        for kpi, org, v, *rest in rows:
            row_period = rest[1] if len(rest) > 1 else period or ""
            lines.append([kpi, codes.get(org, org), names.get(org, org), row_period, v if isinstance(v, str) else float(v),
                          rest[0] if rest else ""])
        lines += [list(x) for x in extra]
        preview, result, written = actor.import_file(xlsx_bytes(lines), campaign_id=campaign_id, validate=validate)
        if result is None and preview is None:
            return 0
        a = result or preview
        rejects = [l for l in a.lignes if l.action == "rejet"]
        if expect_rejects is not None and len(rejects) != expect_rejects:
            self.log.anomaly("import_rejects", f"{actor}: {len(rejects)} rejected line(s), expected {expect_rejects}: "
                             + "; ".join(f"{l.kpi_id if hasattr(l, 'kpi_id') else ''} {getattr(l, 'motif', '')}" for l in rejects[:5]))
        self.log.event(f"{actor} imported {written} value(s), {len(rejects)} rejected")
        return written


# ---------------------------------------------------------------------------------------------------- the years
def year_values(g, year):
    w = g.w

    def value_of(kpi, org):
        if kpi == "CERT":
            return "Oui" if w.rng("cert", org, year).random() < 0.6 else "Non"
        if kpi == "WTAB":
            mass = base_value(w, "WASTE", org, year)
            return f"| Paper | {fr(round(mass * D('0.6'), 1))} | |\n| Plastic | {fr(round(mass * D('0.4'), 1))} | sorted |"
        if kpi == "WOMEN":
            return min(base_value(w, kpi, org, year), base_value(w, "HEAD", org, year))
        return base_value(w, kpi, org, year)
    return value_of


def year1(g):
    w, log = g.w, g.log
    log.step = "2023"
    c = g.create_campaign(W.ANNUAL, 2023)
    g.campaign_action(c, "ouvrir", "ouverte")
    # consistency rule created by the administrator (Consistency › Rules)
    from parametres.models import NiveauHierarchique  # noqa: F401  (level codes are those of world.py)

    g.admin.admin_panel("collecte:regle_nouvelle", data={
        "nom": "Women at most headcount", "description": "Women cannot exceed the headcount.", "gauche": "[WOMEN]",
        "operateur": "<=", "droite": "[HEAD]", "tolerance": "0", "niveau": "Entity", "bloquante": "on", "actif": "on"})
    from collecte.models import RegleCoherence

    with g.db():
        if not RegleCoherence.objects.filter(gauche="[WOMEN]").exists():
            log.anomaly("rule_not_created", "rule WOMEN <= HEAD")
    values = year_values(g, 2023)
    group = g.a(f"{w.prefix}group")
    for kpi in ("FE", "REV"):
        g.enter_one(group, c, kpi, w.group, values(kpi, w.group), True, _kpi(g, kpi))

    first_entity = w.entities[0]
    con = w.contributor_of[first_entity]
    actor = g.a(con)
    site = g.children(first_entity)[0]
    # mistakes and corrections ----------------------------------------------------------------------------------
    ok, html, _ = actor.enter(c, "WATER", site, "12,5")  # typing mistake (decimal comma for a whole volume)
    r = g.answer(c, "WATER", site)
    if r is None or r.valeur != D("12.5"):
        log.anomaly("decimal_comma", f"'12,5' stored as {r and r.valeur}")
    actor.enter(c, "WATER", site, "1234")  # correction
    ok, html, _ = actor.enter(c, "ACC", site, "", na=True, validate=True)  # N/A without a comment: refused
    if ok:
        log.anomaly("na_without_comment_validated", f"ACC {site}")
    actor.enter(c, "ACC", site, "", na=True, comment="Site without staff on duty this year.", validate=True)
    ok, html, _ = actor.enter(c, "ELEC", site, fr(values("ELEC", site)), validate=True)  # no evidence yet: refused
    if ok:
        log.anomaly("validated_without_evidence", f"ELEC {site}")
    ok, html, _ = actor.enter(c, "WATER", site, "abc")  # not a number
    if ok:
        log.anomaly("text_accepted_as_number", "WATER 'abc'")
    # blocking rule: women above headcount refused, then corrected
    head = values("HEAD", first_entity)
    actor.enter(c, "HEAD", first_entity, fr(head), validate=True)
    ok, html, _ = actor.enter(c, "WOMEN", first_entity, fr(head + 10), validate=True)
    if ok:
        log.anomaly("blocking_rule_not_applied", f"WOMEN {head + 10} > HEAD {head} validated")
    # table answer with a wrong list value, then corrected
    ok, html, _ = actor.enter(c, "WTAB", site, "| Glass | 2 | |", validate=True)
    if ok:
        log.anomaly("table_unknown_list_value_accepted", "Glass")
    # everyone fills their cells: half in the panel, half by import (tiny: all in the panel)
    share = 1.0 if w.size in ("micro", "tiny") else 0.5 if w.size == "small" else 0.1
    for e in w.entities:
        g.fill(w.contributor_of[e], c, values, panel_share=share, salt="y1")
    # import with rejected lines (unknown organisation, unknown KPI, calculated KPI, text in a number, other's cell)
    other_site = g.children(w.entities[1])[0]
    extra = [["NOPE", "", g.org(site).nom, "", 5, ""], ["WATER", "", "Unknown site", "", 5, ""],
             ["GAS", "", g.org(site).nom, "", "twelve", ""], ["WATER", "", g.org(other_site).nom, "", 5, ""]]
    # a calculated KPI in the file: a contributor cannot override a calculated result, so the line is rejected with a
    # message (README, "Import values"; before, it was ignored)
    extra.append(["CO2", "", g.org(site).nom, "", 5, ""])
    g.import_values(actor, c, [("WATER", site, values("WATER", site))], extra=extra, expect_rejects=len(extra))
    # validator validates drafts in their scope; administrator corrections
    for country, vname in w.validator_of.items():
        validate_drafts(g, vname, c)
    adm = g.admin
    ok, html, _ = adm.cell(c, "WATER", site, "a_saisir")  # clear the value
    if g.answer(c, "WATER", site).valeur is not None:
        log.anomaly("clear_value", "WATER still has a value after « Clear the value »")
    g.enter_one(actor, c, "WATER", site, values("WATER", site), True, _kpi(g, "WATER"))
    adm.cell(c, "GAS", site, "brouillon")  # back to draft by the administrator
    g.enter_one(actor, c, "GAS", site, values("GAS", site), True, _kpi(g, "GAS"))
    validate_drafts(g, f"{w.prefix}admin", c)
    CK.after_year(g, 2023, [c], light=g.quick)
    g.campaign_action(c, "revue", "revue")
    g.campaign_action(c, "cloturer", "cloturee")
    CK.after_closure(g, 2023, [c])
    return c


def validate_drafts(g, username, campaign_id):
    """The person validates every draft they can see (validator: their countries; administrator: everything)."""
    from collecte import saisie as S
    from collecte.models import Campagne, Reponse
    from referentiel.models import Utilisateur

    with g.db():
        u = Utilisateur.objects.get(username=username)
        c = Campagne.objects.select_related("referentiel", "periode").get(pk=campaign_id)
        cells = [(k.code, o.pk) for k, o in S.cellules(u, campagne=c)]
        drafts = set(Reponse.objects.filter(periode=c.periode, statut=Reponse.Statut.BROUILLON).values_list("kpi_id", "organisation_id"))
    actor = g.a(username)
    for kpi, org in cells:
        if (kpi, org) in drafts:
            ok, html, _ = actor.cell(campaign_id, kpi, org, "valider", valeur=_current(g, campaign_id, kpi, org),
                                     commentaire=_comment(g, campaign_id, kpi, org) or "Checked by the validator.",
                                     **({"non_applicable": "on"} if _na(g, campaign_id, kpi, org) else {}))
            if not ok:
                g.log.anomaly("validation_refused", f"{username} {kpi} {org}: {CK.short(html)}")


def _current(g, c, kpi, org):
    from collecte import saisie as S

    r = g.answer(c, kpi, org)
    with g.db():
        return S.valeur_pour_saisie(r, _kpi(g, kpi)) if r else ""


def _comment(g, c, kpi, org):
    r = g.answer(c, kpi, org)
    return r.commentaire if r else ""


def _na(g, c, kpi, org):
    r = g.answer(c, kpi, org)
    return bool(r and r.non_applicable)


def _kpi(g, code):
    from referentiel.models import KPI

    with g.db():
        return KPI.objects.select_related("type_reponse").get(pk=code)


def year2(g, closed_prev):
    """2024: monthly framework, tree changes, new KPI, changed formula, forced value, reminders, correction by import."""
    w, log = g.w, g.log
    log.step = "2024"
    adm = g.admin
    adm.post(adm.url("parametres:referentiels"), {"action": "reactiver", "code": W.MONTHLY}, fetch=False)
    c = g.create_campaign(W.ANNUAL, 2024)
    months = g.create_campaign(W.MONTHLY, 2024, all_periods=True)
    for m in [c] + months:
        g.set_end_date(m, 40)
        g.campaign_action(m, "ouvrir", "ouverte")
    # catalogue changes between two years
    g.kpi_sheet("RENEW", new=True, code="RENEW", libelle="Renewable electricity", type_saisie="Saisi", granularite="Site",
                methode_agregation="Somme", type_reponse="Numérique", unite=_unit(g, "kWh"), decimales="0",
                ajout_place=f"{W.ANNUAL}|{_theme(g, W.ANNUAL, 'Energy')}")
    g.kpi_sheet("CO2", formule="[ELEC] * [FE] + [GAS] * 0.2")
    g.formula_changed |= {"CO2", "INTENS"}
    # tree changes: a site closes in June, a site opens, an entity moves to another country
    closing = g.children(w.entities[-1])[-1]
    g.org_form(closing, actif=False, date_desactivation="2024-06-30")
    g.closing_site = closing
    host = w.entities[0]
    # the new site opens on 1 January 2024: it counts from 2024 only ("Open since")
    new_site = g.org_form(None, nom=f"{w.prefix}New site 2024", niveau="Site", parent=str(host), type_site="autre", actif="on",
                          date_ouverture="2024-01-01")
    moved = w.entities[1]
    target = next(x for x in reversed(w.countries) if x != g.org(moved).parent_id)
    g.moved = (moved, g.org(moved).parent_id, target)  # entity, former country, new country
    g.org_form(moved, parent=str(target))
    con = w.contributor_of[host]
    if new_site:
        g.assign([(k, new_site) for k in ("ELEC", "GAS", "WATER", "WASTE", "ACC", "CERT", "WTAB", "RENEW")], con, c)
    for e in w.entities:
        sites = g.children(e)
        g.assign([("RENEW", s) for s in sites], w.contributor_of[e], c)
    values = year_values(g, 2024)

    # monthly values (ELEC, GAS): each contributor imports one file with the 12 months (Period column)
    monthly_import(g, months, 2024)
    # annual: the rest of the cells (ELEC and GAS are cumulated from the months: not asked any more)
    group = g.a(f"{w.prefix}group")
    for kpi in ("FE", "REV"):
        g.enter_one(group, c, kpi, w.group, values(kpi, w.group), True, _kpi(g, kpi))
    share = 1.0 if w.size in ("micro", "tiny") else 0.5 if w.size == "small" else 0.1
    # a variance above the threshold of the campaign: the panel asks for a comment (enter_one gives it)
    jump_site = g.children(w.entities[0])[0]

    def values_with_jump(kpi, org):
        v = values(kpi, org)
        if kpi == "WATER" and org == jump_site and v is not None:
            g.planted.append((c, "WATER", org, "ecart"))
            return v * 2
        return v
    for e in w.entities:
        g.fill(w.contributor_of[e], c, values_with_jump, panel_share=share, salt="y2")
    # forced value on a calculated KPI: asked by the contributor, accepted by the validator
    site = g.children(w.entities[0])[1] if len(g.children(w.entities[0])) > 1 else jump_site
    actor = g.a(con)
    g.assign([("CO2", site)], con, c)  # the contributor answers for the result of the calculated KPI on their site
    ok, html, _ = actor.cell(c, "CO2", site, "forcer", valeur_forcee="1000", justification="Meter replaced in March.")
    from collecte.forcage import en_attente
    from collecte.models import Campagne

    with g.db():
        d = en_attente(Campagne.objects.get(pk=c).periode, _kpi(g, "CO2"), g.org(site))
    if d is None:
        log.anomaly("forced_value_not_asked", f"CO2 {site}: {CK.short(html)}")
    else:
        country = g.org(g.org(site).parent_id).parent_id
        ok, html, _ = g.a(w.validator_of[country]).cell(c, "CO2", site, "accepter_forcage", demande=str(d.pk))
        r = g.answer(c, "CO2", site)
        if not ok or r is None or r.origine != "forcee" or r.valeur != D(1000):
            log.anomaly("forced_value_not_applied", f"CO2 {site}: {r and (r.origine, r.valeur)} {CK.short(html)}")
    # the site closed on 30/06 still owes its first half-year: the administrator tries to enter it
    ok, html, st = adm.enter(c, "WATER", closing, "150", comment="First half-year before the closure.")
    if not ok:
        log.anomaly("closed_site_last_year_not_enterable", f"site closed on 30/06/2024, campaign 2024: the administrator cannot "
                    f"enter its first half-year ({st}): {CK.short(html)}", rule=True)
    # the validators follow the moved entity: the new country's validator writes there, the former one no longer does
    old_country = next(x for x in w.countries if x != target)
    site_moved = g.children(moved)[0]
    ok_new, html_new, _ = g.a(w.validator_of[target]).enter(c, "WATER", site_moved, fr(values("WATER", site_moved)))
    ok_old, html_old, _ = g.a(w.validator_of[old_country]).enter(c, "WATER", site_moved, "1")
    if not ok_new:
        log.anomaly("moved_entity_validator", f"validator of the new country cannot write in the moved entity: {CK.short(html_new)}")
    if ok_old:
        log.anomaly("moved_entity_validator", "validator of the former country still writes in the moved entity")
    # reminders before the end of the entry: some cells left to fill on purpose
    reminders(g, c, closed_sites=[closing])
    for country, vname in w.validator_of.items():
        validate_drafts(g, vname, c)
    validate_drafts(g, f"{w.prefix}admin", c)
    CK.after_year(g, 2024, [c] + months)
    for m in months + [c]:
        g.campaign_action(m, "cloturer", "cloturee")
    CK.after_closure(g, 2024, [c] + months)
    # correction after the closure (an error found by the auditor):
    # 1. imported into the closed year: a value entered in the tool is never replaced (README, "Import values")
    log.step = "2024-correction"
    fix_site = g.children(w.entities[0])[0]
    before = g.answer(c, "WATER", fix_site)
    g.import_values(adm, c, [("WATER", fix_site, D(4321), "Corrected after the audit.")], expect_rejects=None)
    after = g.answer(c, "WATER", fix_site)
    if (after and after.valeur) != (before and before.valeur):
        log.anomaly("closed_import_replaced_entry", f"WATER {fix_site}: {before and before.valeur} -> {after and after.valeur}")
    # 2. so the administrator reopens the year for review, imports the correction, and closes again
    g.campaign_action(c, "rouvrir", "revue")
    g.import_values(adm, c, [("WATER", fix_site, D(4321), "Corrected after the audit.")], validate=True)
    after = g.answer(c, "WATER", fix_site)
    if after is None or after.valeur != D(4321):
        log.anomaly("review_correction_not_written", f"WATER {fix_site}: {before and before.valeur} -> {after and after.valeur}")
    entity_total = g.answer(c, "WATER", w.entities[0])
    CK.after_year(g, 2024, [c] + months, label="reopened", light=g.quick)
    g.campaign_action(c, "cloturer", "cloturee")
    log.event(f"correction: WATER of entity {entity_total and entity_total.valeur}")
    return c, months


def monthly_import(g, months, year):
    """Each contributor imports one file with their monthly values of the year: one row per KPI, site and month, the
    month in the Period column (« 2024-03 »), validated on import."""
    w = g.w
    for e in w.entities:
        con_e = w.contributor_of[e]
        rows = []
        for i, mc in enumerate(months, start=1):
            rows += [(kpi, s, base_value(w, kpi, s, year, i), "", f"{year}-{i:02d}") for kpi, s in g.cells_of(con_e, mc)]
        if rows:
            g.import_values(g.a(con_e), None, rows, validate=True)


def reminders(g, campaign_id, closed_sites=()):
    """Dashboard › Reminders: the administrator sends a reminder to everybody who still has cells to fill. A closed
    site is never in a reminder."""
    from django.core import mail

    adm = g.admin
    r = adm.get(adm.url("collecte:relances"), campagne=campaign_id)
    people = [af.personne.pk for af in (r.context.get("liste") or [])] if r.context else []
    for af in (r.context.get("liste") or []) if r.context else []:
        closed = [l for l in af.lignes if l.organisation.pk in closed_sites]
        if closed:
            g.log.anomaly("reminder_for_closed_site", f"{af.personne}: {len(closed)} line(s) of a closed site in the reminder")
    if not people:
        g.log.event("reminders: nobody to remind")
        return 0
    n0 = len(mail.outbox)
    adm.post(adm.url("collecte:relances"), {"action": "envoyer", "personnes": [str(p) for p in people]}, fetch=False)
    sent = len(mail.outbox) - n0
    if sent != len(people):
        g.log.anomaly("reminders_not_sent", f"{sent} e-mail(s) for {len(people)} person(s)")
    g.log.event(f"reminders sent: {sent}")
    return sent


def _unit(g, code):
    from parametres.models import Unite

    with g.db():
        u = Unite.objects.filter(code=code).first()
        return u.pk if u else ""


def _theme(g, ref, name):
    from referentiel.models import Theme

    with g.db():
        t = Theme.objects.filter(referentiel_id=ref, nom=name).first()
        return t.pk if t else ""


def year3(g):
    """2025: KPI made inactive, months, library template installed then updated, closure."""
    w, log = g.w, g.log
    log.step = "2025"
    c = g.create_campaign(W.ANNUAL, 2025)
    months = g.create_campaign(W.MONTHLY, 2025, all_periods=True)
    g.kpi_sheet("WASTE", actif=False)
    for m in [c] + months:
        g.set_end_date(m, 40)
        g.campaign_action(m, "ouvrir", "ouverte")
    library_template(g)
    requested_since_previous_year(g, c)
    values = year_values(g, 2025)
    monthly_import(g, months, 2025)
    group = g.a(f"{w.prefix}group")
    for kpi in ("FE", "REV"):
        g.enter_one(group, c, kpi, w.group, values(kpi, w.group), True, _kpi(g, kpi))
    share = 1.0 if w.size in ("micro", "tiny") else 0.5 if w.size == "small" else 0.1
    for e in w.entities:
        g.fill(w.contributor_of[e], c, values, panel_share=share, salt="y3")
    reminders(g, c)
    assistant_same_as_page(g, c)
    validate_drafts(g, f"{w.prefix}admin", c)
    # history after the KPI was made inactive: the 2024 export still has its values
    data = g.admin.export(presentation="base", format="csv", csv="intl", exercices=["2024"], periodes=["annee"], referentiel=W.ANNUAL,
                          contenus=["valide", "brouillon", "calcule"], niveaux=["Group", "Country", "Entity", "Site"],
                          types=["saisie", "herite", "calcul"])
    if data is not None and b"WASTE" not in data:
        log.anomaly("inactive_kpi_missing_from_history", "WASTE (made inactive in 2025) is no longer in the 2024 export", rule=True)
    CK.after_year(g, 2025, [c] + months, light=g.quick)
    for m in months + [c]:
        g.campaign_action(m, "cloturer", "cloturee")
    CK.after_closure(g, 2025, [c] + months)
    history_probes(g)
    return c, months


def _mcp_call(g, token, tool, arguments):
    """One call of an assistant tool on the MCP endpoint (token only, no session). Returns (HTTP status, data, error)."""
    import json

    from django.test import Client

    with g.db():
        from django.urls import reverse

        url = reverse("serveur_mcp:point")
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": arguments}})
    r = Client(raise_request_exception=False).post(url, body, content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {token}")
    if r.status_code >= 500:
        g.log.anomaly("http_500", f"MCP {tool} -> {r.status_code}")
        return r.status_code, None, "500"
    try:
        result = r.json().get("result") or {}
        data = json.loads(result["content"][0]["text"]) if result.get("content") else None
    except (ValueError, KeyError, IndexError) as e:
        return r.status_code, None, f"unreadable answer: {e} {r.content[:200]!r}"
    return r.status_code, data, (str(data)[:300] if result.get("isError") else "")


mcp_call = _mcp_call  # public name (qa/group_life/year4.py)


def assistant_same_as_page(g, campaign_id):
    """Year 3: the administrator allows assistants (Settings › Assistants), creates a token (My account), reads a cell
    with ``get_value`` and changes it with ``save_value``. The same change made in the entry panel must give the same log
    line, the same cell and the same totals (docs/mcp.md: each tool calls the functions of its page)."""
    from collecte.models import Campagne, Journal
    from serveur_mcp.models import JournalMCP

    w, log, adm = g.w, g.log, g.admin
    step = log.step
    log.step = f"{step} assistant"
    try:
        r, html = adm.admin_panel("serveur_mcp:reglages", data={"actif": "on", "ecriture": "on", "appels_minute": "120",
                                                                 "duree_max_jours": "90"})
        r = adm.post(adm.url("collecte:mon_compte"), {"action": "jeton_creer", "nom": "Group life", "jours": "30"}, fetch=False)
        r = adm.get(adm.url("collecte:mon_compte"))
        token = ((r.context.get("mcp") or {}).get("nouveau") or {}).get("jeton") if r.context else None
        if not token:
            log.anomaly("mcp_no_token", f"no token shown on My account after its creation ({r.status_code})")
            return
        with g.db():
            c = Campagne.objects.get(pk=campaign_id)
            period = c.periode_id
        site = next((s for s in w.sites if g.org(s).actif and g.answer(campaign_id, "WATER", s) is not None
                     and g.answer(campaign_id, "WATER", s).valeur is not None), None)
        if site is None:
            log.anomaly("mcp_no_cell", "no active site with a water value to change")
            return
        cell = {"campaign_id": campaign_id, "kpi_code": "WATER", "organisation_id": site}
        st, data, err = _mcp_call(g, token, "get_value", cell)
        start = g.answer(campaign_id, "WATER", site)
        if err or data is None or D(str(data.get("value"))) != start.valeur:
            log.anomaly("mcp_read_differs", f"get_value WATER@{site}: {err or data} (in the database: {start.valeur})")
            return
        v0, v1, comment = start.valeur, start.valeur + 1, start.commentaire

        def state():
            snap = CK.snapshot(g, [period])
            with g.db():
                rows = list(Journal.objects.filter(pk__gt=mark[0]).order_by("pk").values_list(
                    "pk", "utilisateur_id", "action", "objet", "objet_id", "champ", "avant", "apres"))
                mark[0] = Journal.objects.order_by("-pk").values_list("pk", flat=True).first() or 0
                data_rows = [x for x in rows if x[2] not in ("appel_mcp", "appels_mcp")]  # the assistants' own lines
                via = set(JournalMCP.objects.filter(journal_id__in=[x[0] for x in data_rows]).values_list("journal_id", flat=True))
                calls.append(sum(1 for x in rows if x[2] == "appel_mcp"))
                linked.append(len(via) == len(data_rows) > 0)
            r_ = g.answer(campaign_id, "WATER", site)
            return [x[1:] for x in data_rows], snap, (r_.valeur, r_.statut, r_.origine, r_.saisi_par_id, r_.commentaire)

        calls, linked = [], []
        with g.db():
            mark = [Journal.objects.order_by("-pk").values_list("pk", flat=True).first() or 0]
        ok, html, st_ = adm.enter(campaign_id, "WATER", site, fr(v1), comment=comment)
        by_page = state()
        # the page puts the cell back as it was (value, then status): these lines are not compared
        adm.enter(campaign_id, "WATER", site, fr(v0), comment=comment, validate=start.statut == "valide")
        state()
        again = g.answer(campaign_id, "WATER", site)
        if (again.valeur, again.statut, again.commentaire) != (start.valeur, start.statut, start.commentaire):
            log.anomaly("mcp_no_comparison", f"WATER@{site}: the panel did not put the cell back "
                        f"({again.valeur}, {again.statut}) instead of ({start.valeur}, {start.statut})")
            return
        st, data, err = _mcp_call(g, token, "get_value", cell)
        st, data, err = _mcp_call(g, token, "save_value", {**cell, "value": format(v1, "f"), "version": (data or {}).get("version", "")})
        by_mcp = state()
        if not ok or err or not (data or {}).get("saved"):
            log.anomaly("mcp_write_failed", f"page ok={ok} ({st_}); save_value: {err or data}")
            return
        for what, a_, b_ in (("log lines", by_page[0], by_mcp[0]), ("totals", by_page[1], by_mcp[1]), ("cell", by_page[2], by_mcp[2])):
            if a_ != b_:
                diff = a_ if not isinstance(a_, dict) else {k: (a_.get(k), b_.get(k)) for k in set(a_) | set(b_) if a_.get(k) != b_.get(k)}
                log.anomaly("mcp_differs_from_page", f"WATER@{site} {fr(v0)} -> {fr(v1)}: {what} differ: page {str(diff)[:500]} "
                            f"| assistant {str(b_ if not isinstance(b_, dict) else '')[:400]}")
        if calls[-1] != 1 or not linked[-1] or linked[0]:
            log.anomaly("mcp_call_not_logged", f"save_value: {calls[-1]} 'appel_mcp' line(s) in the log, data lines shown "
                        f"'via MCP': {linked[-1]} (entry panel: {linked[0]})")
        log.event(f"assistant: get_value and save_value on WATER@{g.org(site).nom}, {len(by_mcp[0])} log line(s), "
                  f"{len(by_mcp[1])} cell(s) compared with the same entry in the panel")
    finally:
        log.step = step


def requested_since_previous_year(g, c2025):
    """Project rule: a KPI created in 2025 on its KPI sheet, with « Add it to previous years too? »
    set to 2024 (closed). While 2024 is closed nothing moves (no cell offered, same completion rate); it enters 2024 when
    the year is reopened (``history_probes``), in both modes; 2025 asks for it at once."""
    from collecte import saisie as S
    from collecte.models import Campagne

    log = g.log
    c2024 = g.campaign(W.ANNUAL, 2024)
    with g.db():
        debut_2024 = Campagne.objects.get(pk=c2024).periode.debut.isoformat()
    saved = g.kpi_sheet("SINCE", new=True, code="SINCE", libelle="Requested since 2024", type_saisie="Saisi", granularite="Site",
                        methode_agregation="Somme", type_reponse="Numérique", unite=_unit(g, "kWh"), decimales="0",
                        ajout_place=f"{W.ANNUAL}|{_theme(g, W.ANNUAL, 'Energy')}",
                        **{f"ajout_depuis__{W.ANNUAL}": debut_2024})
    if not saved:
        return
    g.since_added = {"SINCE"}
    with g.db():
        dans = {y: "SINCE" in (S.codes_campagne(Campagne.objects.select_related("referentiel", "periode").get(pk=x))[1])
                for y, x in ((2024, c2024), (2025, c2025))}
    if dans != {2024: False, 2025: True}:
        log.anomaly("requested_since", f"SINCE (asked since 2024) offered in {dans}; expected 2024 closed: no, 2025: yes", rule=True)
    else:
        log.event("SINCE created in 2025, asked since 2024: not in 2024 while it is closed, in 2025 at once")


def history_probes(g):
    """Two years later, the past is reopened (an audit asks for it): what changes in the published figures?

    2023 is reopened after an entity moved to another country, a site opened (with its opening date), a site closed and a
    formula changed; 2024 after a KPI was made inactive. : each year is reopened twice, first
    keeping the figures of the time (the default of the page: nothing may change), then recalculating with today's
    organisation (README, "Recalculation": only the formulas changed since and the totals above the moved entity may
    change; no new cell, no total that becomes incomplete). (tree kept at each closure): in 2023
    kept with the figures of the time, a site of the moved entity is corrected (+1): the totals of its parents of the
    time (the entity, its former country, the group) grow by exactly 1, the new country does not change
    (``kept_year_correction``)."""
    from collecte.models import Campagne

    log = g.log
    moved, old_parent, new_parent = getattr(g, "moved", (None, None, None))
    around_move = set()
    for o in (old_parent, new_parent):  # the two countries of the moved entity and their ancestors
        while o:
            around_move.add(o)
            o = g.org(o).parent_id
    for year in (2023, 2024):
        c = g.campaign(W.ANNUAL, year)
        with g.db():
            p = Campagne.objects.get(pk=c).periode_id
        for mode in ("garder", "recalculer"):
            log.step = f"reopen {year} ({mode})"
            before = CK.snapshot(g, [p])
            g.campaign_action(c, "rouvrir", "revue", **({"reouverture": mode} if mode == "recalculer" else {}))
            after = CK.snapshot(g, [p])
            changed = {k: (before.get(k), after.get(k)) for k in set(before) | set(after) if before.get(k) != after.get(k)}
            if mode == "garder" and year == 2023 and moved is not None:
                kept_year_correction(g, c, p, moved, old_parent, new_parent)
            kinds = {"past_year_gets_new_cells": [], "past_total_becomes_incomplete": [], "past_figure_changes": []}
            since = getattr(g, "since_added", set())
            if since and year == 2024:  # asked since 2024 on purpose: offered once the year is reopened
                from collecte import saisie as S

                with g.db():
                    offert = since <= (S.codes_campagne(Campagne.objects.select_related("referentiel", "periode").get(pk=c))[1] or set())
                if not offert:
                    log.anomaly("requested_since", f"{sorted(since)} not offered in 2024 reopened ({mode})", rule=True)
            for (pp, kpi, org), (b, a) in sorted(changed.items()):
                line = f"{kpi}@{g.org(org).nom}: {b and (b[0], b[3])} -> {a and (a[0], a[3])}"
                if b is None and kpi in since and year == 2024:
                    log.event(f"{year} reopened: {line} (asked since 2024 on purpose: enters at the reopening, chosen)")
                elif b is None:
                    kinds["past_year_gets_new_cells"].append(line)
                elif (a is not None and a[3] == "incomplet" and b[3] != "incomplet" and mode == "recalculer"
                      and org in around_move and not g.children(org)):
                    # micro size: the former country had only the moved entity; in today's tree it has nothing left
                    log.event(f"{year} reopened: {line} (entity moved since: nothing left under it in today's tree, chosen)")
                elif a is not None and a[3] == "incomplet" and b[3] != "incomplet":
                    kinds["past_total_becomes_incomplete"].append(line)
                elif mode == "recalculer" and kpi in g.formula_changed:
                    log.event(f"{year} reopened: {line} (formula changed since: recalculated, README « Recalculation »)")
                elif mode == "recalculer" and org in around_move:
                    log.event(f"{year} reopened: {line} (entity moved since: recalculated with today's tree, chosen)")
                else:
                    kinds["past_figure_changes"].append(line)
            for code, lines in kinds.items():
                if lines:
                    log.anomaly(code, f"{year} reopened ({mode}): {len(lines)} cell(s): " + " | ".join(lines[:6]), rule=True,
                                year=year, kpis=sorted({x.split("@")[0] for x in lines}))
            CK.data_check(g, f"{year} reopened ({mode})")
            g.campaign_action(c, "cloturer", "cloturee")
            CK.data_check(g, f"{year} closed again")


def kept_year_correction(g, c, p, moved, old_parent, new_parent):
    """Year reopened with the figures of the time, after an entity moved to another country: a site of the moved entity
    is corrected (+1); the totals of its parents of the time grow by exactly 1, the new country does not change."""
    site = next(iter(g.children(moved, active_only=False)), None)
    r = g.answer(c, "WATER", site) if site else None
    if r is None or r.valeur is None:
        g.log.event("kept year correction: no WATER value on a site of the moved entity (skipped)")
        return
    totals = [moved, old_parent, g.w.group, new_parent]
    before = {o: (g.answer(c, "WATER", o) or r).valeur for o in totals}
    ok, html, st = g.admin.enter(c, "WATER", site, fr(r.valeur + 1), comment="Audit correction.")
    if not ok:
        g.log.anomaly("kept_year_correction", f"correction refused ({st}): {CK.short(html)}")
        return
    after = {o: (g.answer(c, "WATER", o) or r).valeur for o in totals}
    expected = {moved: 1, old_parent: 1, g.w.group: 1, new_parent: 0}
    wrong = [f"{g.org(o).nom}: {before[o]} -> {after[o]} (expected +{expected[o]})" for o in totals
             if before[o] is None or after[o] is None or after[o] - before[o] != expected[o]]
    if wrong:
        g.log.anomaly("kept_year_correction", "2023 kept with the figures of the time, site of the moved entity +1: "
                      + " | ".join(wrong), rule=True)
    else:
        g.log.event(f"2023 kept: {g.org(site).nom} +1 -> group WATER {before[g.w.group]} -> {after[g.w.group]} "
                    "(tree of the closure: the moved entity counts once, under its former country)")


def library_template(g, code="VS_BASE"):
    """Settings › Frameworks › Library: install a provided template (choose the KPIs, then install), then install it
    again as a new version (the path of a yearly update)."""
    from referentiel.models import Referentiel

    adm = g.admin
    with g.db():
        from collecte import paquets as PQ  # noqa: F401
        from parametres import vues_installation as VI

        f = VI.modele_fourni(code)
        codes = [k["code"] for k in f.paquet.kpis]
    r = adm.post(adm.url("parametres:installer_kpi", code), {"action": "continuer", "kpi": codes}, fetch=False)
    r = adm.post(adm.url("parametres:installer_resume", code), {"action": "installer", "nom": "VS base", "frequence": "annee",
                                                                 "mois_debut": "1", "code": "VSB"}, fetch=False)
    with g.db():
        ok = Referentiel.objects.filter(code="VSB").exists()
    if not ok:
        g.log.anomaly("library_install_failed", f"{code}: {r.status_code} {CK.short(text_of(r))}")
        return
    g.log.event(f"library template {code} installed ({len(codes)} KPIs)")
    r = adm.get(adm.url("parametres:installer_kpi", code, query="version=1"))
    r = adm.post(adm.url("parametres:installer_kpi", code), {"action": "continuer", "kpi": codes}, fetch=False)
    r = adm.post(adm.url("parametres:installer_resume", code), {"action": "installer", "nom": "VS base", "frequence": "annee",
                                                                 "mois_debut": "1", "code": "VSB"}, fetch=False)
    if r.status_code not in (200, 302):
        g.log.anomaly("library_update_failed", f"{code}: {r.status_code}")


# ---------------------------------------------------------------------------------------------------- entry point
def play(size="small", seed=1, years=3, spaces=True, echo=None, standalone=False, second_space="essai", quick=False,
         export_threshold=None):
    """Builds the group and plays its life. Returns the ``Log`` (anomalies, events). ``quick``: version of the test suite
    (every event, the full checks after the second year only, a second space without the VS template).
    ``export_threshold``: cells above which an export is made in the background (Settings › Hosting); lowered to play
    the large exports on a small group."""
    import logging

    from .actors import ErrorRecorder

    log = Log(echo)
    rec = ErrorRecorder()
    root = logging.getLogger()
    root.addHandler(rec)
    try:
        log.step = "build"
        w = W.build(size, seed)
        if export_threshold is not None:
            from parametres.models import Instance

            Instance.objects.filter(pk=Instance.courante().pk).update(exports_fond_cellules=export_threshold)
        log.event(f"{len(w.sites)} sites, {len(w.entities)} entities, {len(w.countries)} countries, {len(w.users)} accounts")
        g = Game(w, log)
        g.standalone = standalone
        g.quick = quick
        CK.rights(g, None)
        c1 = year1(g)
        if years >= 2:
            year2(g, c1)
        if years >= 3:
            year3(g)
        if spaces:
            log.step = "spaces"
            CK.second_space(g, second_space)
        if standalone:
            log.step = "backup"
            CK.backup_restore(g)
    except Exception as e:  # noqa: BLE001 - a crash of the scenario is an anomaly of the scenario, said as such
        import traceback

        log.anomaly("scenario_crashed", f"{e.__class__.__name__}: {e}\n{traceback.format_exc()[-1500:]}")
    finally:
        root.removeHandler(rec)
        log.step = "end"
    expected = CK.EXPECTED_LOG_ERRORS
    for msg in rec.records:
        if not any(x in msg for x in expected):
            log.anomaly("error_logged", msg)
    return log
