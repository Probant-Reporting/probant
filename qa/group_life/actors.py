"""People of the group: one Django test client per account, signed in, that uses the pages like a person does.

Each call goes through a URL of the tool (never a direct write in the database). A 5xx answer, or an answer that is not
what the page should give, is written in the ``Log`` of the scenario as an anomaly; the scenario continues.
"""
import io
import json
import logging
import re
from contextlib import contextmanager

from django.test import Client
from django.urls import reverse

from espaces import contexte as E

FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}
PDF = b"%PDF-1.4 group life evidence\n%%EOF\n"


class ErrorRecorder(logging.Handler):
    """Every log record at ERROR or above while the scenario runs (``django.request`` 500s included)."""

    def __init__(self):
        super().__init__(logging.ERROR)
        self.records = []

    def emit(self, record):
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001
            msg = str(record.msg)
        self.records.append(f"{record.name}: {msg}"[:500])


class Log:
    """Anomalies and events of a run. ``anomaly(code, ...)``: something the tool should not do."""

    def __init__(self, echo=None):
        self.anomalies = []
        self.events = []
        self.echo = echo
        self.durations = {}  # seconds spent in each step (to keep the version of the suite short)
        self._step, self._since = "", None

    @property
    def step(self):
        return self._step

    @step.setter
    def step(self, value):
        import time

        now = time.monotonic()
        if self._since is not None:
            self.durations[self._step] = self.durations.get(self._step, 0) + now - self._since
        self._step, self._since = value, now

    def event(self, text):
        self.events.append(f"[{self.step}] {text}")
        if self.echo:
            self.echo(f"  {self.step}: {text}")

    def anomaly(self, code, detail, **data):
        item = {"code": code, "step": self.step, "detail": str(detail)[:1500], **data}
        self.anomalies.append(item)
        if self.echo:
            self.echo(f"  !! {code} [{self.step}] {str(detail)[:300]}")

    def codes(self):
        return sorted({a["code"] for a in self.anomalies})


def text_of(response):
    """HTML of an answer: the "html" key of a JSON answer (pages opened by the script), otherwise the body."""
    ctype = response.get("Content-Type", "")
    if "json" in ctype:
        try:
            data = json.loads(response.content)
        except ValueError:
            return response.content.decode(errors="replace")
        return data.get("html") or json.dumps(data, ensure_ascii=False)
    if getattr(response, "streaming", False):
        return ""
    return response.content.decode(errors="replace")


ERRORS = re.compile(r'class="[^"]*(?:erreur|errorlist|alerte-erreur|message-error)[^"]*"[^>]*>(.*?)</', re.S)


def errors_in(html):
    return [re.sub(r"<[^>]+>", "", m).strip() for m in ERRORS.findall(html) if re.sub(r"<[^>]+>", "", m).strip()][:5]


class Actor:
    """An account of the space ``space``, signed in with its own test client."""

    def __init__(self, username, log, space="principal"):
        from referentiel.models import Utilisateur

        self.username, self.log, self.space = username, log, space
        self.client = Client(raise_request_exception=False)
        with E.activer(space):
            self.user = Utilisateur.objects.get(username=username)
        self.client.force_login(self.user)

    def __repr__(self):
        return f"<{self.username}>"

    @contextmanager
    def here(self):
        with E.activer(self.space):
            yield

    def url(self, name, *args, query=""):
        with E.activer(self.space):
            return reverse(name, args=args) + (f"?{query}" if query else "")

    # ------------------------------------------------------------------ transport
    def _check(self, method, url, r, expect):
        if r.status_code >= 500:
            self.log.anomaly("http_500", f"{self.username} {method} {url} -> {r.status_code}", url=url, user=self.username)
        elif expect is not None and r.status_code not in (expect if isinstance(expect, (tuple, list, set)) else (expect,)):
            self.log.anomaly("unexpected_status", f"{self.username} {method} {url} -> {r.status_code} (expected {expect})",
                             url=url, user=self.username)
        return r

    def get(self, url, expect=200, fetch=False, **params):
        r = self.client.get(url, params or None, **(FETCH if fetch else {}))
        return self._check("GET", url, r, expect)

    def post(self, url, data=None, expect=(200, 302), fetch=True, **extra):
        r = self.client.post(url, data or {}, **(FETCH if fetch else {}), **extra)
        return self._check("POST", url, r, expect)

    def post_json(self, url, body, expect=200):
        r = self.client.post(url, json.dumps(body), content_type="application/json", **FETCH)
        return self._check("POST", url, r, expect)

    # ------------------------------------------------------------------ data entry (panel of a cell)
    def cell_url(self, campaign_id, kpi, org_id):
        return self.url("collecte:cellule", campaign_id, kpi, org_id)

    def cell(self, campaign_id, kpi, org_id, action, expect=(200, 403), **fields):
        """One action of the entry panel. Returns (ok, html, status)."""
        r = self.post(self.cell_url(campaign_id, kpi, org_id), {"action": action, **fields}, expect=expect)
        if r.status_code != 200:
            return False, text_of(r), r.status_code
        try:
            data = json.loads(r.content)
        except ValueError:
            return False, text_of(r), r.status_code
        return bool(data.get("ok")), data.get("html", ""), r.status_code

    def enter(self, campaign_id, kpi, org_id, value="", na=False, comment="", validate=False, expect=(200, 403)):
        fields = {"valeur": value, "commentaire": comment}
        if na:
            fields["non_applicable"] = "on"
        return self.cell(campaign_id, kpi, org_id, "valider" if validate else "enregistrer", expect=expect, **fields)

    def evidence(self, campaign_id, kpi, org_id, name="evidence.pdf", content=PDF):
        from django.core.files.uploadedfile import SimpleUploadedFile

        f = SimpleUploadedFile(name, content, content_type="application/pdf")
        r = self.post(self.cell_url(campaign_id, kpi, org_id), {"action": "preuve", "fichier": f})
        return r.status_code == 200 and json.loads(r.content).get("ok")

    # ------------------------------------------------------------------ administration panels
    def admin_panel(self, name, *args, data=None, expect=(200, 302)):
        r = self.post(self.url(name, *args), data or {}, expect=expect)
        return r, text_of(r)

    def import_file(self, content, filename="values.xlsx", campaign_id=None, validate=False, create_campaigns=False,
                    corrections=None):
        """Import / Export › Import values: preview, then confirm. Returns (preview analysis, result analysis, written)."""
        from django.core.files.uploadedfile import SimpleUploadedFile

        url = self.url("collecte:echanges_importer")
        data = {"action": "verifier", "fichier": SimpleUploadedFile(filename, content)}
        if campaign_id:
            data["campagne"] = str(campaign_id)
        if validate:
            data["valider"] = "on"
        if create_campaigns:
            data["creer_campagnes"] = "on"
        r = self.post(url, data, fetch=False, expect=(200, 302))
        preview = r.context.get("analyse") if r.status_code == 200 and r.context else None
        if preview is None:
            self.log.anomaly("import_no_preview", f"{self.username}: no preview for {filename} ({r.status_code})")
            return None, None, 0
        r = self.post(url, {"action": "confirmer"}, fetch=False, expect=(200, 302))
        if r.status_code == 302:  # background task (large file)
            return preview, None, self._run_background(r)
        result = r.context.get("analyse") if r.context else None
        written = r.context.get("ecrites", 0) if r.context else 0
        return preview, result, written

    def _run_background(self, r):
        from collecte import imports_arriere_plan as AP
        from collecte.models import TacheImport

        with self.here():
            t = TacheImport.objects.filter(utilisateur=self.user).order_by("-pk").first()
            if t is None:
                self.log.anomaly("import_task_missing", f"{self.username}: redirect without task ({r['Location']})")
                return 0
            AP.executer(t)
            t.refresh_from_db()
            if t.statut != TacheImport.Statut.TERMINEE:
                self.log.anomaly("import_task_failed", f"task {t.pk}: {t.statut} {t.erreur[:300]}")
            return t.ecrites

    def _post_export(self, params):
        from django.http import QueryDict

        q = QueryDict(mutable=True)
        for k, v in {"action": "telecharger", **params}.items():
            if isinstance(v, (list, tuple)):
                q.setlist(k, [str(x) for x in v])
            else:
                q[k] = str(v)
        return self.client.post(self.url("collecte:echanges_exporter"), q.urlencode(),
                                content_type="application/x-www-form-urlencoded")

    @staticmethod
    def _bytes(r):
        return b"".join(r.streaming_content) if r.streaming else r.content

    def export(self, **params):
        """Import / Export › Export, "Download". Returns the bytes of the file (or None). Above the threshold of large
        exports (Settings › Hosting), the page queues a background task and sends the person to My exports: the actor then
        follows the task like the page does (state, then download) and checks that the file is the same as the immediate
        download (threshold lifted for one request)."""
        r = self._post_export(params)
        if r.status_code == 302 and "#exports-fond" in r.get("Location", ""):
            data = self._export_background(params)
            if data is not None:
                immediate = self._export_immediate(params)
                if immediate is not None and not same_export(data, immediate):
                    self.log.anomaly("export_background_differs", f"{self.username}: background export {params} is not "
                                     "the same as the immediate download")
            return data
        self._check("POST", "export", r, (200,))
        if r.status_code != 200 or "html" in r.get("Content-Type", ""):
            self.log.anomaly("export_no_file", f"{self.username}: export {params} gave no file ({r.status_code})")
            return None
        return self._bytes(r)

    def _export_background(self, params, timeout=600):
        """The task of the person: made here if nobody has taken it yet (as the scheduler would), then followed through
        its state page until it is finished, then downloaded from My exports."""
        import time

        from collecte import exports_arriere_plan as EAP
        from collecte.models import TacheExport

        with self.here():
            t = TacheExport.objects.filter(utilisateur=self.user).order_by("-pk").first()
            if t is None:
                self.log.anomaly("export_task_missing", f"{self.username}: export {params} sent to My exports without a task")
                return None
            if t.statut == TacheExport.Statut.ATTENTE and EAP.prise(t):
                t.refresh_from_db()
                EAP.executer(t)
        fin = time.monotonic() + timeout
        while True:
            r = self.get(self.url("collecte:echanges_export_etat", t.pk), fetch=True)
            etat = json.loads(r.content) if r.status_code == 200 else {}
            if etat.get("fini") or time.monotonic() > fin:
                break
            time.sleep(0.5)
        if etat.get("statut") != TacheExport.Statut.PRET:
            with self.here():
                t.refresh_from_db()
            self.log.anomaly("export_task_failed", f"{self.username}: background export {params}: {t.statut} {t.erreur[:300]}")
            return None
        r = self.get(self.url("collecte:echanges_export_fichier", t.pk))
        if r.status_code != 200 or "html" in r.get("Content-Type", ""):
            self.log.anomaly("export_no_file", f"{self.username}: background export {params} gave no file ({r.status_code})")
            return None
        return self._bytes(r)

    def _export_immediate(self, params):
        from parametres.models import Instance

        with self.here():
            avant = Instance.courante().exports_fond_cellules
            Instance.objects.filter(pk=1).update(exports_fond_cellules=0)
        try:
            r = self._post_export(params)
        finally:
            with self.here():
                Instance.objects.filter(pk=1).update(exports_fond_cellules=avant)
        if r.status_code != 200 or "html" in r.get("Content-Type", ""):
            self.log.anomaly("export_no_file", f"{self.username}: immediate export {params} gave no file ({r.status_code})")
            return None
        return self._bytes(r)


# « Exporté 13:56 · admin » : l'heure de fabrication du fichier (à la minute) n'est pas son contenu ; deux
# fichiers faits de part et d'autre d'un changement de minute restent le même export
HORODATAGE = re.compile(r"\b\d{1,4}[./-]\d{1,2}[./-]\d{1,4} \d{1,2}:\d{2}\b")


def _sans_horodatage(v):
    return HORODATAGE.sub("<horodatage>", v) if isinstance(v, str) else v


def export_rows(data):
    """Rows of an export file (xlsx: every sheet; csv: the lines), to compare two files whatever their packaging. The time
    at which the file was made (short date and time, to the minute) is masked."""
    if data[:2] == b"PK":
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(data), read_only=True)
        return [(ws.title, [tuple(_sans_horodatage(v) for v in row) for row in ws.iter_rows(values_only=True)])
                for ws in wb.worksheets]
    return [_sans_horodatage(ligne) for ligne in data.decode("utf-8-sig").splitlines()]


def same_export(a, b):
    return export_rows(a) == export_rows(b)


def xlsx_bytes(rows, sheet="Saisie"):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    for row in rows:
        ws.append(row)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
