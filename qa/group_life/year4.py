"""A fourth reporting year (2026) and events placed between the years: what the first three years do not play.

``play4(size, seed)`` plays the first years (``scenario.py``, as many as asked), the second space, then the events
below, each one through the pages of the tool (forms, imports, IT commands), each one followed by its checks. An
event that crashes is an anomaly of its own (``event_crashed:<name>``); the next events still play. ``Log.played``
says, for each event, whether it was played and what came out (the report table).

people         a contributor leaves (drafts, validated values, evidence, assistant token, saved export, personal view)
               and is replaced (« Replace a person… »); a validator becomes a reader; the last administrator cannot be
               demoted; a person with accounts in two spaces; e-mail changed; temporary password
organisations  site renamed and recoded; level « Region » inserted between Country and Entity, an entity moved under it
               while the campaign is open; two sites merged (one closed in June with its values); an entity sold with
               its sites; a closed site reopened
framework      unit of a KPI changed between two years; answer format changed (refused); KPI removed from the framework
               and put back; KPI made optional; formula changed while the campaign is open; sensitive KPI past its
               retention period (evidence deleted); list value used in a table removed; table column changed
campaigns      fiscal year April to March next to the calendar year; quarterly next to monthly and annual on the same
               KPI; two years open at the same time; dates changed after opening; closing with drafts left
installation   « startup » in the middle of a campaign; default language changed; space archived then reactivated
languages      the same campaign entered in French, English, German and Portuguese; files filled in those languages;
               reminders in the language of each person; export read in another language and imported again

Commentaires en anglais, comme le reste de qa/ (outil de recette).
"""
import datetime
import json
import re
from decimal import Decimal

from django.utils import timezone

from . import checks as CK
from . import scenario as SC
from . import world as W
from .actors import Actor, text_of, xlsx_bytes

D = Decimal
YEAR = 2026


# ---------------------------------------------------------------------------------------------------- helpers
def empty(v):
    """Field left empty in a form (0 is a value, False an unchecked box)."""
    return v is None or v is False or (isinstance(v, str) and v == "")


def kpi_of(g, code):
    from referentiel.models import KPI

    with g.db():
        return KPI.objects.select_related("type_reponse").get(pk=code)


def current_of(g, c, kpi, org):
    """Value of a cell as the entry field shows it."""
    from collecte import saisie as S

    r = g.answer(c, kpi, org)
    with g.db():
        return S.valeur_pour_saisie(r, kpi_of(g, kpi)) if r else ""


def comment_of(g, c, kpi, org):
    r = g.answer(c, kpi, org)
    return r.commentaire if r else ""


def unit_pk(g, code):
    from parametres.models import Unite

    with g.db():
        u = Unite.objects.filter(code=code).first()
        return u.pk if u else ""


def theme_pk(g, ref, name):
    from referentiel.models import Theme

    with g.db():
        t = Theme.objects.filter(referentiel_id=ref, nom=name).first()
        return t.pk if t else ""


def line_text(l):
    return " ".join(str(getattr(l, x, "")) for x in ("kpi_id", "organisation", "periode", "valeur", "motif") if getattr(l, x, ""))[:160]


def _played(g, name, status, detail=""):
    g.log.played.append({"event": name, "status": status, "detail": str(detail)[:300]})
    g.log.event(f"{name}: {status} {detail}"[:300])


def guarded(name):
    """Runs an event; a crash becomes the anomaly ``event_crashed:<name>`` and the next events still play."""
    def wrap(fn):
        def run(g, *a, **k):
            step = g.log.step
            g.log.step = f"{YEAR} {name}"
            try:
                return fn(g, *a, **k)
            except Exception as e:  # noqa: BLE001
                import traceback

                g.log.anomaly(f"event_crashed:{name}", f"{e.__class__.__name__}: {e}\n{traceback.format_exc()[-1200:]}")
                _played(g, name, "crashed", e)
            finally:
                g.log.step = step
        run.__name__ = fn.__name__
        return run
    return wrap


def closed_snapshot(g):
    """Every answer of every period whose campaigns are all closed: nothing may change there (except by a reopening)."""
    from collecte.models import Campagne

    with g.db():
        open_periods = set(Campagne.objects.exclude(statut="cloturee").values_list("periode_id", flat=True))
        closed = set(Campagne.objects.filter(statut="cloturee").values_list("periode_id", flat=True)) - open_periods
    return CK.snapshot(g, closed)


def closed_unchanged(g, before, what):
    """Anomaly ``closed_year_changed`` if a cell of the periods of ``before`` (``closed_snapshot``) changed."""
    periods = {k[0] for k in before}
    after = CK.snapshot(g, periods)
    diffs = [f"{k[1]}@{k[2]} p{k[0]}: {before.get(k)} -> {after.get(k)}" for k in sorted(set(before) | set(after))
             if before.get(k) != after.get(k)]
    if diffs:
        g.log.anomaly("closed_year_changed", f"after {what}: {len(diffs)} cell(s) of a closed period changed: " + " | ".join(diffs[:6]))
    return not diffs


def invariants(g, campaigns, what, light=None):
    """Checks after each event: data check, totals = sum of the detail; full checks (« Recalculate », completion,
    rights) unless ``light``."""
    light = g.quick if light is None else light
    CK.data_check(g, what)
    CK.totals_equal_detail(g, campaigns)
    if not light:
        CK.recalculation_identical(g, campaigns)
        CK.completion_consistent(g, campaigns[0])


def account_form(g, user_pk=None, actor=None, **changes):
    """Administration › Accounts, the account form as the page shows it, with ``changes``. Returns (saved, html)."""
    from collecte.administration import CompteForm
    from referentiel.models import Utilisateur

    actor = actor or g.admin
    with actor.here():
        u = Utilisateur.objects.get(pk=user_pk) if user_pk else Utilisateur(is_active=True)
        form = CompteForm(instance=u, moi=actor.user)
        data = {}
        for name in form.fields:
            v = form[name].value()
            if name == "perimetre_lecture":
                data[name] = [str(x) for x in (v or [])]
            elif not empty(v):
                data[name] = v
    data.update(changes)
    data = {k: v for k, v in data.items() if not empty(v) and v != []}
    data["action"] = "enregistrer"
    url = actor.url("collecte:admin_compte", user_pk) if user_pk else actor.url("collecte:admin_compte_nouveau")
    r = actor.post(url, data)
    html = text_of(r)
    try:
        ok = bool(json.loads(r.content).get("ok")) if "json" in r.get("Content-Type", "") else r.status_code == 302
    except ValueError:
        ok = False
    g.last_password = (r.context or {}).get("mdp_donne") if getattr(r, "context", None) else None
    return ok or "succes" in html or r.status_code == 302, html


def to_reader(g, user_pk):
    """Account form: role "reader". With assignments, the form asks to confirm their removal : the
    administrator reads the number and confirms. Returns (saved, html)."""
    ok, html = account_form(g, user_pk, role="lecteur")
    if 'name="confirmer_retrait"' in html:
        ok, html = account_form(g, user_pk, role="lecteur", confirmer_retrait="on")
    return ok, html


def new_account(g, first, last, email, role):
    """A new account from Administration › Accounts; the person signs in with the temporary password and replaces it
    (My account), as on their first day. Returns the username (the e-mail) or None."""
    ok, html = account_form(g, first_name=first, last_name=last, email=email, role=role)
    u = user(g, email)
    if u is None:
        g.log.anomaly("account_not_created", f"{email}: {CK.short(html)}")
        return None
    temp = g.last_password
    a = g.a(u.username)
    if temp:
        a.post(a.url("collecte:mon_compte"), {"old_password": temp, "new_password1": W.PASSWORD, "new_password2": W.PASSWORD},
               fetch=False)
        a.user.refresh_from_db()
        a.client.force_login(a.user)
        if user(g, email).doit_changer_mdp:
            g.log.anomaly("first_password_not_replaced", email)
    g.w.users[u.username] = role
    return u.username


def user(g, username):
    from referentiel.models import Utilisateur

    with g.db():
        return Utilisateur.objects.filter(username=username).first()


def sign_in(g, identifier, password):
    """The sign-in page, as a person types it. Returns the test client (signed in or not) and the answer."""
    from django.test import Client

    c = Client(raise_request_exception=False)
    from espaces import contexte as E
    from django.urls import reverse

    with E.activer(g.space):
        url = reverse("login")
    r = c.post(url, {"username": identifier, "password": password})
    return c, r


def mcp_call(g, token, tool, arguments):
    return SC.mcp_call(g, token, tool, arguments)


def new_token(g, actor):
    actor.post(actor.url("collecte:mon_compte"), {"action": "jeton_creer", "nom": "Year 4", "jours": "30"}, fetch=False)
    r = actor.get(actor.url("collecte:mon_compte"))
    return ((r.context.get("mcp") or {}).get("nouveau") or {}).get("jeton") if r.context else None


def enable_assistants(g):
    g.admin.admin_panel("serveur_mcp:reglages", data={"actif": "on", "ecriture": "on", "appels_minute": "120", "duree_max_jours": "90"})


def remind_people(g, campaign_id):
    """Dashboard › Reminders: {username: number of lines} for the campaign."""
    adm = g.admin
    r = adm.get(adm.url("collecte:relances"), campagne=campaign_id)
    out = {}
    for af in (r.context.get("liste") or []) if r.context else []:
        out[af.personne.username] = sum(len(ls) for camp, ls in af.campagnes if camp.pk == campaign_id)
    return out


def open_campaign(g, ref, year, all_periods=False):
    ids = g.create_campaign(ref, year, all_periods=all_periods)
    for c in (ids if all_periods else [ids]):
        if c:
            g.set_end_date(c, 40)
            g.campaign_action(c, "ouvrir", "ouverte")
    return ids


def entities_of(g):
    return [e for e in g.w.entities if g.org(e).actif]


# ---------------------------------------------------------------------------------------------------- the year
def year4(g):
    """2026: the annual campaign and the events. Returns the annual campaign id."""
    g.log.step = f"{YEAR}"
    with g.db():
        from referentiel.models import Referentiel

        g.monthly_on = Referentiel.objects.filter(code=W.MONTHLY, actif=True).exists()
    c = open_campaign(g, W.ANNUAL, YEAR)
    g.c4 = c
    values = SC.year_values(g, YEAR)
    g.values4 = values
    contributor_becomes_reader(g, c)
    group = g.a(f"{g.w.prefix}group")
    for kpi in ("FE", "REV"):
        g.enter_one(group, c, kpi, g.w.group, values(kpi, g.w.group), True, kpi_of(g, kpi))
    before_closed = closed_snapshot(g)
    g.closed_before4 = before_closed
    # events placed in the year, in the order a group lives them
    people_departure(g, c)
    validator_becomes_reader(g, c)
    last_admin(g)
    temporary_password(g, c)
    email_changed(g)
    two_spaces(g)
    languages(g, c)
    org_renamed_recoded(g, c)
    level_inserted(g, c)
    sites_merged(g, c)
    entity_sold(g, c)
    site_reopened(g, c)
    unit_changed(g, c)
    format_changed(g)
    kpi_removed_and_back(g, c)
    kpi_optional(g, c)
    formula_changed_open(g, c)
    sensitive_retention(g)
    table_list_value_removed(g)
    table_column_changed(g)
    library_over_local_change(g)
    fiscal_year_april(g, c)
    quarter_month_year(g, c)
    two_years_open(g, c)
    dates_changed(g, c)
    campaign_deleted(g)
    startup_mid_campaign(g, c)
    default_language(g, c)
    space_archived(g)
    closing_with_drafts(g)
    g.log.step = f"{YEAR} end"
    closed_unchanged(g, before_closed, "the whole fourth year")
    CK.after_year(g, YEAR, [c], label="end of the fourth year")  # every check, export imported again and rights included
    return c


# ---------------------------------------------------------------------------------------------------- 1. people
@guarded("contributor leaves and is replaced")
def people_departure(g, c):
    from collecte.models import Journal, ReglageExport, Reponse, VueVisu
    from referentiel.models import Attribution

    w = g.w
    entity = w.entities[0]
    old = w.contributor_of[entity]
    a = g.a(old)
    enable_assistants(g)
    token = new_token(g, a)
    cells = g.cells_of(old, c)
    values = g.values4
    # half validated, half left as drafts; ELEC with its evidence (enter_one adds it)
    for i, (kpi, org) in enumerate(cells):
        v = values(kpi, org)
        if v is None:
            continue
        g.enter_one(a, c, kpi, org, v, i % 2 == 0, kpi_of(g, kpi))
    # a saved export and a personal view
    a.post(a.url("collecte:echanges_exporter"), {"action": "enregistrer", "nom": "My water export", "presentation": "base",
                                                 "format": "xlsx", "exercices": [str(YEAR)], "periodes": ["annee"]}, fetch=False)
    a.post_json(a.url("collecte:visu_vue_creer"), {"nom": "My view", "visuels": []}, expect=(201, 400))
    with g.db():
        saved = ReglageExport.objects.filter(proprietaire__username=old).count()
        views = VueVisu.objects.filter(proprietaire__username=old).count()
        drafts = sorted(Reponse.objects.filter(periode__campagnes=c, saisi_par__username=old, statut="brouillon")
                        .values_list("kpi_id", "organisation_id"))
        lines_before = Journal.objects.filter(utilisateur__username=old).count()
    # the replacement: a new account, then « Replace a person… » with the departed account switched off
    new = new_account(g, "Nora", "Newcomer", f"{w.prefix}con-1-1-new@exemple.test", "contributeur")
    if new is None:
        _played(g, "contributor leaves and is replaced", "not played", "account not created")
        return
    nu, ou = user(g, new), user(g, old)
    adm = g.admin
    r = adm.post(adm.url("collecte:admin_remplacer"), {"de": str(ou.pk), "par": str(nu.pk), "desactiver": "on"}, fetch=False)
    if r.status_code >= 400:
        g.log.anomaly("replace_failed", f"{r.status_code} {CK.short(text_of(r))}")
    w.contributor_of[entity] = new
    with g.db():
        left = Attribution.objects.filter(utilisateur__username=old).count()
        active = type(ou).objects.get(pk=ou.pk).is_active
    if left or active:
        g.log.anomaly("replace_incomplete", f"{left} assignment(s) left to the departed person, account active: {active}")
    if g.cells_of(new, c) != cells:
        g.log.anomaly("replacement_cells_differ", f"the replacement has {len(g.cells_of(new, c))} cell(s), the departed person had {len(cells)}")
    # the departed person: no page, no write, no assistant
    a.client.cookies.clear()
    c_, r_ = sign_in(g, f"{old}@exemple.test", W.PASSWORD)
    if r_.status_code == 302 and "connexion" not in r_.get("Location", ""):
        g.log.anomaly("departed_signs_in", f"{old} signs in after the account was switched off")
    if token:
        st, data, err = mcp_call(g, token, "get_value", {"campaign_id": c, "kpi_code": cells[0][0], "organisation_id": cells[0][1]})
        if not err and data is not None:
            g.log.anomaly("departed_token_works", f"the assistant token of {old} still reads after the account was switched off")
    # the replacement takes over the drafts and validates them; reminders go to the replacement only
    remind = remind_people(g, c)
    if old in remind:
        g.log.anomaly("reminder_to_departed", f"{old} still in the reminders ({remind[old]} line(s))")
    if drafts and new not in remind:
        g.log.anomaly("replacement_not_reminded", f"{new} owns {len(drafts)} draft(s) but is not in the reminders")
    na = g.a(new)
    refused = []
    for kpi, org in drafts:
        ok, html, st = na.cell(c, kpi, org, "valider", valeur=current_of(g, c, kpi, org), commentaire=comment_of(g, c, kpi, org)
                               or "Taken over from my predecessor.")
        if not ok:
            refused.append(f"{kpi}@{org}: {CK.short(html, 120)}")
    if refused:
        g.log.anomaly("replacement_cannot_validate", f"{len(refused)} draft(s) of the departed person: " + " | ".join(refused[:4]))
    with g.db():
        lines_after = Journal.objects.filter(utilisateur__username=old).count()
        still_saved = ReglageExport.objects.filter(proprietaire__username=old).count()
    if lines_after < lines_before:
        g.log.anomaly("history_lost", f"log lines of the departed person: {lines_before} -> {lines_after}")
    invariants(g, [c], "departure")
    _played(g, "contributor leaves and is replaced", "played",
            f"{len(cells)} cells, {len(drafts)} drafts taken over, token {'refused' if token else 'not created'}, "
            f"saved exports {saved}->{still_saved}, views {views}")


@guarded("contributor becomes reader")
def contributor_becomes_reader(g, c):
    """The group contributor becomes a reader (another job) before anyone is named in their place: their cells are
    left without anyone who can fill them."""
    from referentiel.models import Attribution

    name = f"{g.w.prefix}group"
    u = user(g, name)
    with g.db():
        cells = list(Attribution.objects.filter(utilisateur=u, role=Attribution.Role.CONTRIBUTEUR).values_list("kpi_id", "organisation_id"))
    to_reader(g, u.pk)
    if user(g, name).role != "lecteur":
        _played(g, "contributor becomes reader", "not played", "role not changed")
        return
    remind = remind_people(g, c)
    adm = g.admin
    r = adm.get(adm.url("collecte:relances"), campagne=c)
    orphans = (r.context or {}).get("sans_spoc") if r.context else None
    if remind.get(name):
        g.log.anomaly("reminder_to_reader", f"{name}, now a reader, is in the reminders for {remind[name]} cell(s) they cannot fill "
                      f"(cells without a contributor shown: {orphans})")
    with g.db():
        from collecte.models import Journal

        logged = Journal.objects.filter(action="retrait_attributions_role", objet_id=str(u.pk)).count()
    if cells and logged != 1:
        g.log.anomaly("removal_not_logged", f"{name}: {len(cells)} assignment(s) removed, {logged} history line(s)")
    account_form(g, u.pk, role="contributeur")
    with g.db():
        back = Attribution.objects.filter(utilisateur=u).count()
    if back:
        g.log.anomaly("assignments_given_back", f"{name}: {back} assignment(s) back with the former role (decision: never)")
    if cells:  # back to contributor: the administrator assigns the cells again (the scenario goes on)
        g.assign(cells, name, c)
    g.actors.pop(name, None)
    _played(g, "contributor becomes reader", "played", f"in the reminders: {bool(remind.get(name))}; cells without contributor {orphans}; "
            f"{len(cells)} cell(s) removed then assigned again")


@guarded("validator becomes reader")
def validator_becomes_reader(g, c):
    """A validator takes another job and becomes a reader. Now a read-only account loses its assignments, and
    the account form says so: the administrator first gives them to the new validator ("Replace a person…", the only way
    to give validator assignments in the tool), then changes the role (nothing left to remove)."""
    from referentiel.models import Attribution

    w = g.w
    country, vname = next(iter(w.validator_of.items()))
    vu = user(g, vname)
    with g.db():
        had = Attribution.objects.filter(utilisateur=vu).count()
        had_valid = list(Attribution.objects.filter(utilisateur=vu, role=Attribution.Role.VALIDATEUR).values_list("kpi_id", "organisation_id"))
    # the new validator of the country first (the scenario goes on with them)
    new = new_account(g, "Vera", "Validator", f"{w.prefix}val-1-new@exemple.test", "validateur")
    nu = user(g, new) if new else None
    if nu:
        adm = g.admin
        adm.post(adm.url("collecte:admin_remplacer"), {"de": str(vu.pk), "par": str(nu.pk)}, fetch=False)
        with g.db():
            if Attribution.objects.filter(utilisateur=vu).exists() or Attribution.objects.filter(utilisateur=nu).count() < had:
                g.log.anomaly("replace_incomplete", f"assignments of {vname} not moved to {new}")
        w.validator_of[country] = new
    ok, html = to_reader(g, vu.pk)
    vu = user(g, vname)
    if vu.role != "lecteur":
        g.log.anomaly("role_not_changed", f"{vname}: {vu.role} {CK.short(html)}")
        return
    g.w.users[vname] = "lecteur"
    g.actors.pop(vname, None)
    with g.db():
        kept = Attribution.objects.filter(utilisateur=vu).count()
    site = next(s for s in w.sites if g.org(s).actif and g.org(g.org(s).parent_id).parent_id == country)
    before = g.answer(c, "WATER", site)
    ok, html, st = g.a(vname).enter(c, "WATER", site, "4242", validate=True)
    after = g.answer(c, "WATER", site)
    if ok or (after and after.valeur == D(4242)):
        g.log.anomaly("write_out_of_rights", f"{vname}, now a reader, wrote WATER@{site}")
    for name in ("collecte:saisie", "collecte:tableau_de_bord", "collecte:pour_moi", "collecte:visu"):
        g.a(vname).get(g.a(vname).url(name), expect=(200, 302, 403))
    if kept:
        g.log.anomaly("reader_keeps_assignments", f"{vname} became a reader and keeps {kept} validator assignment(s): the "
                      "Assignments page still names a validator who cannot validate", rule=True)
    back = _validator_again(g, c, vname, had_valid, site)
    _played(g, "validator becomes reader", "played", f"write refused; {had} assignment(s) given to {new} first, {kept} kept; "
            f"{before and before.valeur}; {back}")


def _validator_again(g, c, vname, pairs, site):
    """Back to the validator role : the role gives nothing back, then the administrator gives the
    validator assignments again in Administration › Assignments, choice "Validators" (the page, as a person does it)."""
    from collecte import saisie as S
    from collecte.models import Journal
    from referentiel.models import KPI, Attribution

    if not pairs:
        return "no validator assignment to give back"
    vu = user(g, vname)
    ok, html = account_form(g, vu.pk, role="validateur")
    vu = user(g, vname)
    if vu.role != "validateur":
        g.log.anomaly("role_not_changed", f"{vname}: back to validator refused {CK.short(html)}")
        return "back to validator refused"
    g.w.users[vname] = "validateur"
    with g.db():
        if Attribution.objects.filter(utilisateur=vu).exists():
            g.log.anomaly("assignments_given_back", f"{vname}: assignments back with the role (decision: never)")
        logged = Journal.objects.filter(action="attribution_validateur").count()
    adm = g.admin
    niveau = g.org(pairs[0][1]).niveau_id
    r = adm.get(adm.url("collecte:admin_attributions"), role="validateur", niveau=niveau, personne=vu.pk)
    offered = {x["id"] for x in ((r.context or {}).get("comptes_json") or [])} if getattr(r, "context", None) else set()
    if r.status_code != 200 or vu.pk not in offered:
        g.log.anomaly("validator_not_offered", f"{vname} is not offered in the choice Validators of the Assignments page")
    if not g.assign(pairs, vname, c, role="validateur"):
        return "validator assignments refused"
    with g.db():
        now = set(Attribution.objects.filter(utilisateur=vu, role=Attribution.Role.VALIDATEUR).values_list("kpi_id", "organisation_id"))
        new_lines = Journal.objects.filter(action="attribution_validateur").count() - logged
        role = S.role_sur(vu, KPI.objects.get(code="WATER"), g.org(site))
    if now != set(pairs):
        g.log.anomaly("validator_assignments_missing", f"{vname}: {len(now)} of {len(pairs)} validator assignment(s) given back")
    if new_lines != len(pairs):
        g.log.anomaly("validator_assignment_not_logged", f"{vname}: {len(pairs)} given, {new_lines} history line(s)")
    if role != "validateur":
        g.log.anomaly("validator_rights_not_back", f"{vname}: role on WATER@{site} is {role}")
    r = adm.get(adm.url("collecte:admin_attributions"), role="validateur", niveau=niveau, personne=vu.pk)
    if not re.search(r'data-spocs="(?:\d+,)*%d(?:,\d+)*"' % vu.pk, r.content.decode()):
        g.log.anomaly("validator_not_in_grid", f"{vname}: not shown in the grid after the assignment")
    return f"back to validator: {len(now)} validator assignment(s) given again in the page, {new_lines} history line(s)"


@guarded("last administrator")
def last_admin(g):
    w = g.w
    me = g.admin
    # demoting oneself: refused
    ok, html = account_form(g, me.user.pk, role="contributeur")
    if user(g, f"{w.prefix}admin").role != "admin":
        g.log.anomaly("last_admin_demoted", "the only administrator demoted their own account")
        return
    # a second administrator demotes the first, then the second is the last one: refused to demote
    second = new_account(g, "Bea", "Backup", f"{w.prefix}admin2@exemple.test", "admin")
    if second is None:
        return
    su = user(g, second)
    s = g.a(second)
    ok, html = account_form(g, su.pk, actor=s, is_active="", role="admin")  # switch off oneself: refused
    if not user(g, second).is_active:
        g.log.anomaly("last_admin_demoted", "an administrator switched off their own account")
    ok, html = account_form(g, me.user.pk, actor=s, role="validateur")  # demote the other one: allowed (one left)
    demoted = user(g, f"{w.prefix}admin").role != "admin"
    if demoted:
        ok, html = account_form(g, su.pk, actor=s, role="contributeur")  # now the last one: refused
        if user(g, second).role != "admin":
            g.log.anomaly("last_admin_demoted", "the last administrator demoted their own account")
        # the second administrator gives the role back
        account_form(g, me.user.pk, actor=s, role="admin")
    if user(g, f"{w.prefix}admin").role != "admin":
        g.log.anomaly("admin_not_restored", "the first administrator did not get the role back")
    g.actors.pop(f"{w.prefix}admin", None)
    # the first one switches the second off (two administrators: allowed)
    account_form(g, su.pk, is_active="", role="admin")
    _played(g, "last administrator", "played", f"self-demotion refused; demote the other: {'done' if demoted else 'refused'}; "
            f"last one kept; second switched off: {not user(g, second).is_active}")


@guarded("temporary password")
def temporary_password(g, c):
    from referentiel.models import Utilisateur

    w = g.w
    name = w.contributor_of[w.entities[-1]]
    u = user(g, name)
    adm = g.admin
    r = adm.post(adm.url("collecte:admin_compte", u.pk), {"action": "reinitialiser"})
    pwd = (r.context or {}).get("mdp_donne") if hasattr(r, "context") and r.context else None
    if not pwd:
        _played(g, "temporary password", "not played", "no temporary password shown")
        return
    client, r = sign_in(g, name + "@exemple.test", pwd)
    # with the temporary password, only My account opens
    from espaces import contexte as E
    from django.urls import reverse

    with E.activer(g.space):
        cell_url = reverse("collecte:cellule", args=[c, "WATER", g.children(w.entities[-1])[0]])
        account_url = reverse("collecte:mon_compte")
    r2 = client.post(cell_url, {"action": "enregistrer", "valeur": "5", "commentaire": ""}, HTTP_X_REQUESTED_WITH="fetch")
    if r2.status_code == 200 and json.loads(r2.content or b"{}").get("ok"):
        g.log.anomaly("temporary_password_writes", "a person with a temporary password wrote a value")
    new_pwd = "Group-life-2026-new"
    r3 = client.post(account_url, {"old_password": pwd, "new_password1": new_pwd, "new_password2": new_pwd})
    with g.db():
        must = Utilisateur.objects.get(pk=u.pk).doit_changer_mdp
    if must:
        g.log.anomaly("password_not_changed", f"{name}: {r3.status_code} {CK.short(text_of(r3))}")
    g.actors.pop(name, None)
    _played(g, "temporary password", "played", "only My account opens; changed by the person")


@guarded("e-mail changed")
def email_changed(g):
    from espaces.models import Compte
    from espaces import contexte as E

    w = g.w
    name = w.contributor_of[w.entities[-1]]
    u = user(g, name)
    new_mail = f"{name}.renamed@exemple.test"
    ok, html = account_form(g, u.pk, email=new_mail)
    with E.toutes_les_bases():
        reg = Compte.objects.filter(pk=u.pk).values_list("email", flat=True).first()
    if user(g, name).email != new_mail or reg != new_mail:
        g.log.anomaly("email_not_changed", f"copy {user(g, name).email}, registry {reg}: {CK.short(html)}")
    client, r = sign_in(g, new_mail, "Group-life-2026-new")
    if r.status_code != 302:
        g.log.anomaly("sign_in_new_email", f"{name} cannot sign in with the new e-mail ({r.status_code})")
    client, r = sign_in(g, f"{name}@exemple.test", "Group-life-2026-new")
    if r.status_code == 302:
        g.log.anomaly("sign_in_old_email", f"{name} still signs in with the former e-mail")
    _played(g, "e-mail changed", "played", "registry and copy follow; sign-in with the new e-mail only")


@guarded("person in two spaces")
def two_spaces(g):
    from espaces import contexte as E
    from espaces.models import Espace
    from referentiel.models import Utilisateur

    code = getattr(g, "second_space_code", None)
    with E.toutes_les_bases():
        ok_space = code and Espace.objects.filter(code=code, etat="actif").exists()
    if not ok_space:
        _played(g, "person in two spaces", "not played", "no second space in this run")
        return
    w = g.w
    name = w.contributor_of[w.entities[0]]
    mail = user(g, name).email
    s2 = Actor("s2-admin", g.log, code)
    ok, html = account_form(g, actor=s2, first_name="Nora", last_name="Newcomer", email=mail, role="lecteur")
    with E.activer(code):
        copy = Utilisateur.objects.filter(email=mail).first()
    if copy is None:
        g.log.anomaly("two_spaces_not_linked", f"{mail}: {CK.short(html)}")
        return
    # identity owned by the main space: the administrator of the second space cannot change the e-mail
    account_form(g, copy.pk, actor=s2, email="hijack@exemple.test")
    with E.activer(code):
        if Utilisateur.objects.get(pk=copy.pk).email != mail:
            g.log.anomaly("identity_changed_elsewhere", "the administrator of the second space changed the e-mail of a shared account")
    # switched off in the main space: still a reader in the second one
    main_pk = user(g, name).pk
    account_form(g, main_pk, is_active="")
    with E.activer(code):
        still = Utilisateur.objects.get(pk=copy.pk).is_active
    account_form(g, main_pk, is_active="on")
    _played(g, "person in two spaces", "played", f"linked; identity locked; switched off in the main space, active in the other: {still}")


# ---------------------------------------------------------------------------------------------------- 2. organisations
@guarded("organisation renamed and recoded")
def org_renamed_recoded(g, c):
    w = g.w
    site = g.children(w.entities[0])[0]
    o = g.org(site)
    old_code, old_name = o.code, o.nom
    g.org_form(site, nom=f"{old_name} (renamed)", code="GL-RENAMED-01")
    o = g.org(site)
    if o.code != "GL-RENAMED-01" or not o.nom.endswith("(renamed)"):
        g.log.anomaly("org_not_renamed", f"{o.code} {o.nom}")
    owner = g.owner("WATER", site)
    actor = g.a(owner)
    # a file prepared before the change, with the former code and name: matched or refused, never another site
    lines = [["KPI ID", "Organisation code", "Organisation", "Period", "Value", "Comment"],
             ["WATER", old_code, old_name, "", 777, "Old file"]]
    preview, result, written = actor.import_file(xlsx_bytes(lines), campaign_id=c)
    r = g.answer(c, "WATER", site)
    status = "matched" if r and r.valeur == D(777) else "refused"
    lines[1][1:3] = [o.code, o.nom]
    lines[1][4] = float(g.values4("WATER", site))
    actor.import_file(xlsx_bytes(lines), campaign_id=c)
    invariants(g, [c], "renamed")
    _played(g, "organisation renamed and recoded", "played", f"file with the former code: {status}")


@guarded("level Region inserted, entity moved in an open campaign")
def level_inserted(g, c):
    from parametres.models import NiveauHierarchique
    from referentiel.models import Attribution

    w = g.w
    adm = g.admin
    adm.post(adm.url("parametres:niveaux"), {"action": "ajouter", "nom": "Region", "nom_pluriel": "Regions", "couleur": "#5B7F3A",
                                              "position": W.Niveau.COUNTRY}, fetch=False)
    with g.db():
        lvl = NiveauHierarchique.objects.filter(nom="Region").first()
        ranks = dict(NiveauHierarchique.objects.values_list("code", "rang"))
    if lvl is None:
        g.log.anomaly("level_not_added", "Region")
        _played(g, "level Region inserted, entity moved in an open campaign", "not played", "level refused")
        return
    from referentiel.models import Niveau

    if not ranks[Niveau.COUNTRY] < lvl.rang < ranks[Niveau.ENTITY]:
        g.log.anomaly("level_misplaced", f"Region at rank {lvl.rang}: {ranks}")
    entity = next(e for e in w.entities if g.org(e).actif)
    country = g.org(entity).parent_id
    region = g.org_form(None, nom=f"{w.prefix}Region North", niveau=lvl.code, parent=str(country), actif="on")
    before_val = g.answer(c, "HEAD", country)
    g.org_form(entity, parent=str(region))
    # the validator of the country still validates the entity (the region is below the country)
    vname = w.validator_of.get(country)
    site = next((s for s in g.children(entity)), None)
    if vname and site:
        ok, html, st = g.a(vname).enter(c, "WATER", site, SC.fr(g.values4("WATER", site)))
        if not ok:
            g.log.anomaly("validator_lost_after_region", f"{vname} no longer writes in an entity moved under a region: {CK.short(html)}")
    after_val = g.answer(c, "HEAD", country)
    region_total = g.answer(c, "HEAD", region)
    with g.db():
        assigned = Attribution.objects.filter(organisation_id=entity).count()
    invariants(g, [c], "region inserted", light=False)
    closed_unchanged(g, g.closed_before4, "a level inserted")
    _played(g, "level Region inserted, entity moved in an open campaign", "played",
            f"country HEAD {before_val and before_val.valeur} -> {after_val and after_val.valeur}, region "
            f"{region_total and (region_total.valeur, region_total.statut)}; {assigned} assignment(s) kept")


@guarded("two sites merged")
def sites_merged(g, c):
    entity = entities_of(g)[-1]
    sites = g.children(entity)
    if len(sites) < 2:
        _played(g, "two sites merged", "not played", "entity with one site")
        return
    a_site, b_site = sites[0], sites[1]
    owner = g.owner("WATER", a_site)
    actor = g.a(owner)
    # site A enters its first half-year, then closes on 30/06; site B goes on
    g.enter_one(actor, c, "WATER", a_site, D(150), True, kpi_of(g, "WATER"))
    g.org_form(a_site, nom=g.org(a_site).nom + " (merged into " + g.org(b_site).nom[-7:] + ")", actif="",
               date_desactivation=f"{YEAR}-06-30")
    g.org_form(b_site)  # nothing changes on B: the form saved as it is
    remind = remind_people(g, c)
    r = g.answer(c, "WATER", a_site)
    if r is None or r.valeur != D(150):
        g.log.anomaly("merged_site_value_lost", f"WATER of the closed site: {r and r.valeur}")
    invariants(g, [c], "merge")
    _played(g, "two sites merged", "played", f"site closed 30/06 keeps its value {r and r.valeur}; reminders {sum(remind.values())} line(s)")


@guarded("entity sold with its sites")
def entity_sold(g, c):
    w = g.w
    candidates = [e for e in entities_of(g) if e != w.entities[0]]
    if not candidates:
        _played(g, "entity sold with its sites", "not played", "one entity only")
        return
    entity = candidates[0]
    owner = w.contributor_of[entity]
    sites = g.children(entity)
    # the entity first: refused while its sites are active
    g.org_form(entity, actif="", date_desactivation=f"{YEAR}-03-31")
    if not g.org(entity).actif:
        g.log.anomaly("parent_closed_before_children", "an entity was closed while its sites were still active")
    for s in sites:
        g.org_form(s, actif="", date_desactivation=f"{YEAR}-03-31")
    g.org_form(entity, actif="", date_desactivation=f"{YEAR}-03-31")
    remind = remind_people(g, c)
    if remind.get(owner):
        g.log.anomaly("reminder_for_sold_entity", f"{owner} is reminded {remind[owner]} line(s) of an entity sold on 31/03 "
                      "without any value this year", rule=True)
    left = g.cells_of(owner, c)
    invariants(g, [c], "sale")
    g.sold = entity
    _played(g, "entity sold with its sites", "played", f"{len(sites)} site(s) closed; {len(left)} cell(s) still asked to {owner}")


@guarded("closed site reopened")
def site_reopened(g, c):
    closing = getattr(g, "closing_site", None)
    if closing is None or g.org(closing).actif:
        _played(g, "closed site reopened", "not played", "no site closed in an earlier year in this run")
        return
    owner = g.owner("WATER", closing)
    g.org_form(closing, actif="on")
    if not g.org(closing).actif:  # its entity is closed too (sold): attached to an open entity, then reopened
        g.org_form(closing, actif="on", parent=str(entities_of(g)[0]))
    o = g.org(closing)
    asked = [x for x in g.cells_of(owner, c) if x[1] == closing] if owner else []
    invariants(g, [c], "reopened site")
    closed_unchanged(g, g.closed_before4, "a site reopened")
    _played(g, "closed site reopened", "played", f"active {o.actif}, closing date {o.date_desactivation}; {len(asked)} cell(s) asked again")


# ---------------------------------------------------------------------------------------------------- 3. framework
@guarded("unit of a KPI changed between two years")
def unit_changed(g, c):
    from referentiel.models import KPI

    adm = g.admin
    adm.post(adm.url("parametres:referentiel") + "?section=unites", {"action": "ajouter", "symbole": "L", "libelle": "litre",
                                                                    "famille": "Volume", "decimales": "0"}, fetch=False)
    unit = unit_pk(g, "L")
    if not unit:
        _played(g, "unit of a KPI changed between two years", "not played", "unit not created")
        return
    with g.db():
        before = KPI.objects.get(pk="WATER").unite_id
    saved = g.kpi_sheet("WATER", unite=unit)  # refused now (the KPI has values): not an anomaly
    g.log.anomalies = [a for a in g.log.anomalies if not (a["code"] == "kpi_sheet_refused" and "WATER" in a["detail"])]
    with g.db():
        after = KPI.objects.get(pk="WATER").unite_id
    if after != before:
        g.log.anomaly("unit_changed_with_values", "WATER m³ -> L accepted although the KPI has values in m³ in the closed years "
                      "(1 234 m³ of 2025 now read 1 234 L next to 2026)", rule=True)
        g.kpi_sheet("WATER", unite=before)  # back to m³ for the rest of the scenario
    _played(g, "unit of a KPI changed between two years", "played", "refused (values entered)" if after == before else f"saved: {saved}")


@guarded("answer format changed")
def format_changed(g):
    from referentiel.models import KPI

    g.kpi_sheet("CERT", type_reponse="GL-WASTETYPE")  # yes / no -> list: refused (values entered)
    with g.db():
        t = KPI.objects.get(pk="CERT").type_reponse_id
    g.log.anomalies = [a for a in g.log.anomalies if not (a["code"] == "kpi_sheet_refused" and "CERT" in a["detail"])]
    if t != "GL-YESNO":
        g.log.anomaly("format_changed_with_values", f"CERT changed to {t}")
    _played(g, "answer format changed", "played", "refused (values entered)" if t == "GL-YESNO" else "accepted")


@guarded("KPI removed from the framework and put back")
def kpi_removed_and_back(g, c):
    from collecte.models import Reponse

    adm = g.admin
    with g.db():
        before = {(r.organisation_id, r.periode_id): (r.valeur, r.statut) for r in Reponse.objects.filter(kpi_id="TRAIN")}
    theme = theme_pk(g, W.ANNUAL, "Training")
    adm.post(adm.url("parametres:referentiels"), {"action": "retirer", "ref": W.ANNUAL, "element": ["TRAIN"]}, fetch=False)
    with g.db():
        from referentiel.models import ElementReferentiel

        gone = not ElementReferentiel.objects.filter(referentiel_id=W.ANNUAL, kpi_id="TRAIN").exists()
        middle = {(r.organisation_id, r.periode_id): (r.valeur, r.statut) for r in Reponse.objects.filter(kpi_id="TRAIN")}
    CK.recalculation_identical(g, [c])
    adm.post(adm.url("parametres:referentiels"), {"action": "ajouter_kpi", "ref": W.ANNUAL, "theme": str(theme), "kpi": ["TRAIN"],
                                                  "kpis": ["TRAIN"]}, fetch=False)
    with g.db():
        back = ElementReferentiel.objects.filter(referentiel_id=W.ANNUAL, kpi_id="TRAIN").exists()
        after = {(r.organisation_id, r.periode_id): (r.valeur, r.statut) for r in Reponse.objects.filter(kpi_id="TRAIN")}
    if not gone or not back:
        _played(g, "KPI removed from the framework and put back", "not played", f"removed {gone}, back {back}")
        return
    lost = [k for k in before if before[k][0] is not None and (k not in after or after[k][0] != before[k][0])]
    if lost:
        g.log.anomaly("kpi_put_back_lost_values", f"TRAIN removed then put back: {len(lost)} value(s) lost or changed: {lost[:4]}")
    lost_mid = [k for k in before if before[k][0] is not None and k not in middle]
    invariants(g, [c], "KPI put back")
    closed_unchanged(g, g.closed_before4, "a KPI removed and put back")
    _played(g, "KPI removed from the framework and put back", "played", f"{len(before)} answers; while removed: {len(lost_mid)} gone; "
            f"after: {len(lost)} lost")


@guarded("KPI made optional")
def kpi_optional(g, c):
    adm = g.admin
    adm.post(adm.url("parametres:referentiels"), {"action": "facultatif", "ref": W.ANNUAL, "element": ["ACC"]}, fetch=False)
    CK.completion_consistent(g, c)
    invariants(g, [c], "KPI optional")
    _played(g, "KPI made optional", "played", "completion consistent on Data entry, Dashboard and Reminders")


@guarded("formula changed while the campaign is open")
def formula_changed_open(g, c):
    saved = g.kpi_sheet("CO2", formule="[ELEC] * [FE] + [GAS] * 0.18")
    g.formula_changed |= {"CO2", "INTENS"}
    invariants(g, [c], "formula changed", light=False)
    closed_unchanged(g, g.closed_before4, "a formula changed")
    _played(g, "formula changed while the campaign is open", "played", f"saved {saved}; « Recalculate » changes nothing after")


@guarded("sensitive KPI past its retention period")
def sensitive_retention(g):
    from collecte.models import Journal, Preuve

    adm = g.admin
    g.kpi_sheet("ELEC", confidentialite="Confidentiel")
    adm.post(adm.url("parametres:hebergement"), {"action": "reglage_conservation", "preuves_sensibles_mois": "1"}, fetch=False)
    r = adm.get(adm.url("collecte:admin_preuves"))
    lignes = (r.context.get("lignes") or []) if r.context else []
    if not lignes:
        _played(g, "sensitive KPI past its retention period", "not played", "no evidence to delete (no closed year with evidence)")
        return
    ids = [str(l["preuve"].pk) for l in lignes]
    cells = {(l["reponse"].periode_id, l["reponse"].kpi_id, l["reponse"].organisation_id) for l in lignes}
    before = closed_snapshot(g)
    adm.post(adm.url("collecte:admin_preuves"), {"preuves": ids}, fetch=False)
    with g.db():
        left = Preuve.objects.filter(pk__in=ids).count()
        purged = Journal.objects.filter(action="purge_preuve").count()
    if left:
        g.log.anomaly("evidence_not_deleted", f"{left} of {len(ids)}")
    closed_unchanged(g, before, "evidence deleted")
    CK.data_check(g, "evidence deleted")
    # the cell panel of a value whose evidence is gone, for the auditor
    p, kpi, org = sorted(cells)[0]
    from collecte.models import Campagne

    with g.db():
        camp = Campagne.objects.filter(periode_id=p).first()
    aud = g.a(f"{g.w.prefix}auditor")
    aud.get(aud.url("collecte:cellule", camp.pk, kpi, org), fetch=True, expect=(200, 403))
    adm.post(adm.url("parametres:hebergement"), {"action": "reglage_conservation", "preuves_sensibles_mois": ""}, fetch=False)
    _played(g, "sensitive KPI past its retention period", "played", f"{len(ids)} evidence file(s) deleted, values unchanged, "
            f"{purged} log line(s)")


@guarded("list value used in a table removed")
def table_list_value_removed(g):
    from parametres.models import TypeReponse

    with g.db():
        t = TypeReponse.objects.get(code="GL-WASTETYPE")
        types = list(TypeReponse.objects.all())
        i = [x.pk for x in types].index(t.pk)
        before = list(t.valeurs)
    adm = g.admin
    data = {"action": "enregistrer", "nb": str(len(types))}
    for j, x in enumerate(types):
        data[f"code__{j}"] = x.pk
    data[f"code__{i}"] = t.pk
    data[f"libelle__{i}"] = t.libelle
    data[f"valeurs__{i}"] = "\n".join(v for v in before if v != "Plastic")
    adm.post(adm.url("parametres:referentiel") + "?section=types-reponse", data, fetch=False)
    with g.db():
        after = list(TypeReponse.objects.get(code="GL-WASTETYPE").valeurs)
    if "Plastic" not in after:
        g.log.anomaly("list_value_used_in_table_removed", "« Plastic » removed from the waste type list although table answers "
                      "(waste by type) use it: these answers can no longer be saved again nor imported again")
        with g.db():  # put it back for the rest of the scenario (the page would refuse nothing)
            TypeReponse.objects.filter(code="GL-WASTETYPE").update(valeurs=before)
    _played(g, "list value used in a table removed", "played", "refused" if "Plastic" in after else "accepted")


@guarded("table column changed")
def table_column_changed(g):
    from parametres.models import TypeReponse

    with g.db():
        types = list(TypeReponse.objects.all())
        t = next(x for x in types if x.code == "GL-WASTETAB")
        i = types.index(t)
        before = list(t.colonnes)
    lines = [f"{c['code']};{(c.get('libelle') or {}).get('fr', c['code'])};{c['type']};{c.get('liste') or c.get('unite') or ''}"
             for c in before] + ["site;Site;texte;"]
    data = {"action": "enregistrer", "nb": str(len(types)), f"libelle__{i}": t.libelle, f"colonnes__{i}": "\n".join(lines)}
    for j, x in enumerate(types):
        data[f"code__{j}"] = x.pk
    g.admin.post(g.admin.url("parametres:referentiel") + "?section=types-reponse", data, fetch=False)
    with g.db():
        after = TypeReponse.objects.get(code="GL-WASTETAB").colonnes
    changed = len(after) != len(before)
    if changed:
        g.log.anomaly("table_column_changed_with_answers", "a column added to the waste table although answers exist")
    _played(g, "table column changed", "played", "accepted" if changed else "refused (answers exist)")


@guarded("new library version over a framework changed locally")
def library_over_local_change(g):
    from referentiel.models import KPI, Referentiel

    with g.db():
        ref = Referentiel.objects.filter(code="VSB").first()
        k = KPI.objects.filter(elements__referentiel_id="VSB", type_saisie_id="Saisi").order_by("code").first() if ref else None
    if k is None:
        _played(g, "new library version over a framework changed locally", "not played", "library template not installed in this run")
        return
    g.kpi_sheet(k.code, libelle=k.libelle + " (our wording)")
    SC.library_template(g)
    with g.db():
        now = KPI.objects.get(pk=k.code).libelle
    kept = now.endswith("(our wording)")
    # the preview of the update lists the KPI as « modified » with « Update / Keep mine » (``analyse_kpis``); the scenario
    # keeps the proposed choice (update): the local wording goes, as shown
    _played(g, "new library version over a framework changed locally", "played",
            f"local change {'kept' if kept else 'replaced, as the preview shows (« modified », choice Update / Keep mine)'}")


# ---------------------------------------------------------------------------------------------------- 4. campaigns
@guarded("fiscal year April to March")
def fiscal_year_april(g, c):
    from referentiel.models import Referentiel

    adm = g.admin
    adm.post(adm.url("parametres:referentiels"), {"action": "ajouter", "nom": "Water fiscal year", "code": "FYWATER",
                                                  "frequence": "annee", "mois_debut": "4"}, fetch=False)
    with g.db():
        ref = Referentiel.objects.filter(code="FYWATER").first()
        if ref and ref.mois_debut != 4:
            g.log.anomaly("fiscal_start_not_saved", f"start month {ref.mois_debut}")
    if ref is None:
        with g.db():  # the page asks more than the scenario sends: create it as the « Settings » form would
            ref = Referentiel.objects.create(code="FYWATER", nom="Water fiscal year", frequence="annee", mois_debut=4, ordre=9)
    adm.post(adm.url("parametres:referentiels"), {"action": "ajouter_kpi", "ref": "FYWATER", "kpi": ["WATER"], "kpis": ["WATER"]},
             fetch=False)
    today = timezone.localdate()
    adm.admin_panel("collecte:admin_campagne_nouvelle", data={
        "action": "enregistrer", "referentiel": "FYWATER", "exercice": str(YEAR), "rang": "1", "seuil_pct": "20",
        "seuil_historique": "2", "date_ouverture": (today - datetime.timedelta(days=5)).isoformat(),
        "date_fin_saisie": (today + datetime.timedelta(days=40)).isoformat()})
    from collecte.models import Campagne

    with g.db():
        fyc = Campagne.objects.filter(referentiel_id="FYWATER").select_related("periode").order_by("-pk").first()
    if fyc is None:
        _played(g, "fiscal year April to March", "not played", "campaign not created")
        return
    g.set_end_date(fyc.pk, 40)
    g.campaign_action(fyc.pk, "ouvrir", "ouverte")
    site = next(s for s in g.w.sites if g.org(s).actif and g.owner("WATER", s))
    owner = g.a(g.owner("WATER", site))
    civil = g.answer(c, "WATER", site)
    g.enter_one(owner, fyc.pk, "WATER", site, D(321), True, kpi_of(g, "WATER"))
    civil_after = g.answer(c, "WATER", site)
    if (civil and civil.valeur) != (civil_after and civil_after.valeur):
        g.log.anomaly("fiscal_year_overwrites_calendar", f"WATER of the calendar year changed {civil and civil.valeur} -> "
                      f"{civil_after and civil_after.valeur} by an entry in the April-March year")
    invariants(g, [c, fyc.pk], "fiscal year")
    _played(g, "fiscal year April to March", "played", f"period {fyc.periode.debut} to {fyc.periode.fin}; calendar value untouched")


@guarded("quarters, months and year on the same KPI")
def quarter_month_year(g, c):
    from collecte.models import Campagne
    from referentiel.models import Referentiel

    if not g.monthly_on:
        _played(g, "quarters, months and year on the same KPI", "not played", "monthly framework not switched on in this run")
        return
    with g.db():
        Referentiel.objects.get_or_create(code="QENERGY", defaults=dict(nom="Quarterly energy", frequence="trimestre", ordre=8))
    g.admin.post(g.admin.url("parametres:referentiels"), {"action": "ajouter_kpi", "ref": "QENERGY", "kpi": ["ELEC"], "kpis": ["ELEC"]},
                 fetch=False)
    today = timezone.localdate()
    g.admin.admin_panel("collecte:admin_campagne_nouvelle", data={
        "action": "enregistrer", "referentiel": "QENERGY", "exercice": str(YEAR), "toutes": "on", "rang": "1", "seuil_pct": "20",
        "seuil_historique": "2"})
    with g.db():
        quarters = list(Campagne.objects.filter(referentiel_id="QENERGY", periode__debut__year=YEAR).values_list("pk", flat=True))
    for q in quarters:
        g.set_end_date(q, 40)
        g.campaign_action(q, "ouvrir", "ouverte")
    del today
    months = open_campaign(g, W.MONTHLY, YEAR, all_periods=True)
    if not all(months) or len(quarters) != 4:
        _played(g, "quarters, months and year on the same KPI", "not played", "campaigns not created")
        return
    site = next(s for s in g.w.sites if g.org(s).actif and g.owner("ELEC", s))
    owner = g.a(g.owner("ELEC", site))
    rows = [("ELEC", site, D(100 + m), "", f"{YEAR}-{m:02d}") for m in range(1, 13)]
    g.import_values(owner, None, rows, validate=True)
    with g.db():
        qcs = list(Campagne.objects.filter(referentiel_id="QENERGY", periode__debut__year=YEAR).order_by("periode__debut"))
    qvals = [g.answer(q.pk, "ELEC", site) for q in qcs]
    year_v = g.answer(c, "ELEC", site)
    expected_q = [sum(D(100 + m) for m in range(3 * i + 1, 3 * i + 4)) for i in range(4)]
    got_q = [r.valeur if r else None for r in qvals]
    if got_q != expected_q:
        g.log.anomaly("quarter_not_sum_of_months", f"ELEC@{site}: quarters {got_q}, sum of the months {expected_q}")
    total = sum(D(100 + m) for m in range(1, 13))
    if year_v is None or year_v.valeur != total:
        g.log.anomaly("year_not_sum_of_months", f"ELEC@{site}: year {year_v and year_v.valeur}, sum of the months {total} "
                      f"(quarters and months both exist)")
    invariants(g, [c] + [q.pk for q in qcs] + months[:1], "quarters")
    _played(g, "quarters, months and year on the same KPI", "played", f"quarters {got_q}; year {year_v and year_v.valeur}")
    g.months4 = months
    g.quarters4 = [q.pk for q in qcs]


@guarded("two years open at the same time")
def two_years_open(g, c):
    c2 = open_campaign(g, W.ANNUAL, YEAR + 1)
    g.c5 = c2
    site = next(s for s in g.w.sites if g.org(s).actif and g.owner("WATER", s))
    owner = g.a(g.owner("WATER", site))
    v26 = g.answer(c, "WATER", site)
    # a file with a Period column: each line goes to its own year
    g.import_values(owner, None, [("WATER", site, D(2027), "", str(YEAR + 1))], validate=False)
    v26b = g.answer(c, "WATER", site)
    v27 = g.answer(c2, "WATER", site)
    if (v26 and v26.valeur) != (v26b and v26b.valeur):
        g.log.anomaly("import_into_wrong_year", f"WATER {YEAR} changed {v26 and v26.valeur} -> {v26b and v26b.valeur} by a {YEAR + 1} line")
    if v27 is None or v27.valeur != D(2027):
        g.log.anomaly("import_period_ignored", f"WATER {YEAR + 1}: {v27 and v27.valeur}")
    # a file without any Period column, while two years are open: which one?
    preview, result, written = owner.import_file(xlsx_bytes([["KPI ID", "Organisation code", "Organisation", "Value"], ["WATER", g.org(site).code, g.org(site).nom, 2028]]))
    v26c, v27c = g.answer(c, "WATER", site), g.answer(c2, "WATER", site)
    went = YEAR if v26c and v26c.valeur == D(2028) else YEAR + 1 if v27c and v27c.valeur == D(2028) else \
        "nowhere: " + "; ".join(f"{l.action} {getattr(l, 'motif', '')}" for l in ((result or preview).lignes if (result or preview) else []))[:160]
    invariants(g, [c, c2], "two years open")
    _played(g, "two years open at the same time", "played", f"Period column followed; file without a period went to {went}")


@guarded("dates changed after opening")
def dates_changed(g, c):
    c2 = getattr(g, "c5", None)
    if not c2:
        _played(g, "dates changed after opening", "not played", "no second year open")
        return
    g.set_end_date(c2, -3)  # end of the entry moved to the past
    site = next(s for s in g.w.sites if g.org(s).actif and g.owner("GAS", s))
    owner = g.a(g.owner("GAS", site))
    ok, html, st = owner.enter(c2, "GAS", site, "100")
    g.set_end_date(c2, 30)
    _played(g, "dates changed after opening", "played", f"entry after the end date: {'accepted' if ok else 'refused'}")


@guarded("campaign deleted then restored")
def campaign_deleted(g):
    # Administration › Campaigns has no « Delete » and « Recently deleted » holds exports, KPI lists and views only
    _played(g, "campaign deleted then restored", "not playable", "no deletion of a campaign in the tool (corbeille.TYPES)")


@guarded("closing with drafts left")
def closing_with_drafts(g):
    from collecte.models import Reponse

    c2 = getattr(g, "c5", None)
    if not c2:
        _played(g, "closing with drafts left", "not played", "no second year open")
        return
    with g.db():
        from collecte.models import Campagne

        p = Campagne.objects.get(pk=c2).periode_id
        drafts = Reponse.objects.filter(periode_id=p, statut="brouillon").count()
    st = g.campaign_action(c2, "cloturer")
    CK.after_closure(g, YEAR + 1, [c2])
    _played(g, "closing with drafts left", "played", f"{drafts} draft(s); status {st}")


# ---------------------------------------------------------------------------------------------------- 5. installation
@guarded("startup in the middle of a campaign")
def startup_mid_campaign(g, c):
    import io

    from django.core.management import call_command

    from collecte.models import Campagne

    with g.db():
        periods = list(Campagne.objects.values_list("periode_id", flat=True))
    before = CK.snapshot(g, periods)
    out = io.StringIO()
    if not getattr(g, "standalone", False):
        _played(g, "startup in the middle of a campaign", "not played", "test suite (no data folder of its own)")
        return
    call_command("startup", stdout=out, stderr=out)
    from django.db import connections

    for x in connections.all():
        x.close()
    after = CK.snapshot(g, periods)
    if before != after:
        diff = [k for k in set(before) | set(after) if before.get(k) != after.get(k)]
        g.log.anomaly("startup_changes_values", f"{len(diff)} cell(s) changed by « startup »: {diff[:4]}")
    _played(g, "startup in the middle of a campaign", "played", "no value changed")


@guarded("default language changed")
def default_language(g, c):
    adm = g.admin
    r = adm.get(adm.url("parametres:langues"))

    def save_default(code):
        from parametres.models import Langue

        with g.db():
            data = {"action": "enregistrer", "defaut": code}
            for lg in Langue.objects.all():
                data[f"libelle__{lg.code}"] = lg.libelle
                if lg.active:
                    data[f"active__{lg.code}"] = "on"
        adm.post(adm.url("parametres:langues"), data, fetch=False)
    with g.db():
        from parametres import langues as L

        before = L.defaut()
    target = "fr" if before == "en" else "en"
    save_default(target)
    with g.db():
        from parametres import langues as L

        now = L.defaut()
    played = now == target
    if played:
        CK.export_reimport(g, c, YEAR)
        save_default(before or "fr")
    _played(g, "default language changed", "played" if played else "not played", f"default {before} -> {now}; export read again "
            "without change" if played else f"default stays {now}")
    del r


@guarded("space archived then reactivated")
def space_archived(g):
    from espaces import contexte as E
    from espaces.models import Espace

    code = getattr(g, "second_space_code", None)
    with E.toutes_les_bases():
        ok_space = code and Espace.objects.filter(code=code).exists()
    if not ok_space:
        _played(g, "space archived then reactivated", "not played", "no second space in this run")
        return
    from collecte.models import Reponse

    with E.activer(code):
        n0 = Reponse.objects.count()
    adm = g.admin
    adm.client.post("/administration/espaces/", {"action": "archiver", "code": code})
    with E.toutes_les_bases():
        st = Espace.objects.get(code=code).etat
    s2 = Actor("s2-admin", g.log, code)
    r = s2.client.get(s2.url("collecte:saisie"))
    adm.client.post("/administration/espaces/", {"action": "reactiver", "code": code})
    with E.activer(code):
        n1 = Reponse.objects.count()
    if n0 != n1:
        g.log.anomaly("space_reactivated_lost_answers", f"{n0} -> {n1}")
    _played(g, "space archived then reactivated", "played", f"archived ({st}), its pages answer {r.status_code}; {n1} answers kept")


# ---------------------------------------------------------------------------------------------------- 6. languages
TYPED = {"fr": "1 234,5", "en": "1,234.5", "de": "1.234,5", "pt": "1 234,5"}


@guarded("one campaign entered in four languages")
def languages(g, c):
    from django.core import mail

    from parametres import langues as L

    with g.db():
        offered = {code for code, _ in L.disponibles()} if hasattr(L, "disponibles") else set()
    langs = [x for x in ("fr", "en", "de", "pt") if not offered or x in offered]
    people = [u for u in [g.w.contributor_of[e] for e in entities_of(g)] if u][:len(langs)]
    if len(people) < 2:
        _played(g, "one campaign entered in four languages", "not played", "not enough contributors left")
        return
    bad, files = [], 0
    for lang, name in zip(langs, people):
        a = g.a(name)
        a.post(a.url("collecte:mon_compte"), {"action": "langue", "langue": lang}, fetch=False)
        cells = [x for x in g.cells_of(name, c) if x[0] == "WATER"]
        if not cells:
            continue
        kpi, org = cells[0]
        ok, html, st = a.enter(c, kpi, org, TYPED[lang], comment="Typed in my language.")
        r = g.answer(c, kpi, org)
        if r is None or r.valeur != D("1234.5"):
            bad.append(f"{lang} « {TYPED[lang]} » stored {r and r.valeur}")
        # the file to fill, in the person's language, filled and imported again
        resp = a.client.get(a.url("collecte:echanges_modele"), {"campagne": c})
        if resp.status_code == 200 and "spreadsheet" in resp.get("Content-Type", ""):
            content = b"".join(resp.streaming_content) if resp.streaming else resp.content
            filled = fill_template(content, kpi, g.org(org), "1234.5" if lang == "en" else "1234,5")
            if filled:
                preview, result, written = a.import_file(filled, campaign_id=c)
                files += 1
                r = g.answer(c, kpi, org)
                if r is None or r.valeur != D("1234.5"):
                    bad.append(f"{lang} file: stored {r and r.valeur}")
    if bad:
        g.log.anomaly("number_read_wrong_in_language", " | ".join(bad))
    # reminders: each person in their own language
    n0 = len(mail.outbox)
    SC.reminders(g, c)
    subjects = {}
    with g.db():
        from referentiel.models import Utilisateur

        mails = {u.email: (u.langue or "") for u in Utilisateur.objects.filter(username__in=people)}
    for m in mail.outbox[n0:]:
        for to in m.to:
            if to in mails:
                subjects[mails[to]] = m.subject
    if len(set(subjects.values())) < len([x for x in subjects if x]):
        g.log.anomaly("reminder_not_in_language", f"subjects by language: {subjects}")
    # export by a German speaker, imported again by an English speaker: nothing to change
    if len(people) >= 3:
        de, en = g.a(people[min(2, len(people) - 1)]), g.a(people[1])
        data = de.export(presentation="base", format="xlsx", exercices=[str(YEAR)], periodes=["annee"], referentiel=W.ANNUAL,
                         contenus=["valide", "brouillon", "a_saisir", "calcule"], niveaux=["Site"], types=["saisie"])
        if data:
            from django.core.files.uploadedfile import SimpleUploadedFile

            r = en.post(en.url("collecte:echanges_importer"), {"action": "verifier", "fichier": SimpleUploadedFile("de.xlsx", data),
                                                               "campagne": str(c)}, fetch=False)
            preview = r.context.get("analyse") if r.context else None
            en.post(en.url("collecte:echanges_importer"), {"action": "annuler"}, fetch=False)
            if preview is not None:
                changes = [line_text(l) for l in preview.lignes if l.action in ("creer", "modifier")]
                own = [l for l in preview.lignes if l.action != "rejet"]
                if changes:
                    g.log.anomaly("export_other_language_changes", f"{len(changes)} change(s): {changes[:4]}")
                del own
    for name in people:  # back to the installation language
        a = g.a(name)
        a.post(a.url("collecte:mon_compte"), {"action": "langue", "langue": ""}, fetch=False)
    invariants(g, [c], "languages")
    _played(g, "one campaign entered in four languages", "played", f"{len(people)} people ({', '.join(langs[:len(people)])}), "
            f"{files} file(s) filled, reminder subjects {len(set(subjects.values()))}")


def fill_template(content, kpi, org, value):
    """Writes ``value`` (text, as typed) in the value cell of the line (kpi, organisation) of a file to fill: the first
    cell of the line with the colour « To fill in » of the legend (the cells a person may change)."""
    import io

    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(content))
    for ws in wb.worksheets:
        rows = list(ws.iter_rows())
        legend = next((r for r in rows[:12] if sum(1 for c in r if c.value not in (None, "")) >= 3 and r[1].value), None)
        colour = legend[1].fill.fgColor.rgb if legend is not None and legend[1].fill is not None else None
        for row in rows:
            vals = [str(c.value or "") for c in row]
            if kpi in vals and (org.code in vals or org.nom in vals):
                for cell in row:
                    if colour and cell.fill is not None and cell.fill.fgColor.rgb == colour:
                        cell.value = value
                        out = io.BytesIO()
                        wb.save(out)
                        return out.getvalue()
    return None


# ---------------------------------------------------------------------------------------------------- entry point
def play4(size="micro", seed=1, years=1, spaces=True, echo=None, standalone=False, second_space="essai", quick=False):
    """Builds the group, plays ``years`` years (``scenario.py``), the second space, then the fourth year. Returns the
    ``Log`` (``log.played``: the events of the fourth year and what came out)."""
    import logging

    from .actors import ErrorRecorder, Log

    log = Log(echo)
    log.played = []
    rec = ErrorRecorder()
    root = logging.getLogger()
    root.addHandler(rec)
    try:
        log.step = "build"
        w = W.build(size, seed)
        g = SC.Game(w, log)
        g.standalone, g.quick = standalone, quick
        c1 = SC.year1(g)
        if years >= 2:
            SC.year2(g, c1)
        if years >= 3:
            SC.year3(g)
        if spaces:
            log.step = "spaces"
            CK.second_space(g, second_space)
            g.second_space_code = second_space
        year4(g)
    except Exception as e:  # noqa: BLE001
        import traceback

        log.anomaly("scenario_crashed", f"{e.__class__.__name__}: {e}\n{traceback.format_exc()[-1500:]}")
    finally:
        root.removeHandler(rec)
        log.step = "end"
    for msg in rec.records:
        if not any(x in msg for x in CK.EXPECTED_LOG_ERRORS):
            log.anomaly("error_logged", msg)
    return log


