"""Politique de sécurité des contenus (collecte/politique_contenus.py) sur toutes les adresses de l'outil, pour chaque
rôle et sans connexion : chaque page HTML porte l'en-tête, avec un jeton propre à la requête ; chaque script et chaque
style intégrés portent ce jeton ; aucun gestionnaire en attribut, aucun lien ``javascript:``, aucune ressource venue
d'un autre site, aucun cadre. Les fichiers déposés gardent leur politique plus stricte ; le JSON n'est pas touché."""
import logging
import re
from html.parser import HTMLParser

from django.contrib.admin import site as site_expert
from django.core.exceptions import SuspiciousOperation
from django.http import HttpResponse
from django.test import Client, override_settings
from django.urls import path, reverse

from parametres.models import Instance

from . import politique_contenus as PC
from .test_droits_balayage import Balayage, routes


def _boum(request):
    raise RuntimeError("erreur volontaire")


def _requete_forgee(request):
    raise SuspiciousOperation("requête forgée")


def _json(request):
    return HttpResponse('{"a": 1}', content_type="application/json")


def _deja_protegee(request):
    r = HttpResponse("<p>x</p>")
    r["Content-Security-Policy"] = "default-src 'none'"
    return r


urlpatterns = [path("essai-csp/boum/", _boum), path("essai-csp/forgee/", _requete_forgee), path("essai-csp/json/", _json),
               path("essai-csp/protegee/", _deja_protegee)]
from config.urls import urlpatterns as _outil  # noqa: E402  (adresses d'essai d'abord, puis celles de l'outil)

urlpatterns += _outil
handler403 = "collecte.reponses_script.refus"


class _Balises(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.balises = []

    def handle_starttag(self, tag, attrs):
        self.balises.append((tag, {k: (v or "") for k, v in attrs}))

    handle_startendtag = handle_starttag


EXTERNE = re.compile(r"^\s*(https?:)?//", re.I)


def jeton(reponse):
    entete = reponse.get(PC.ENTETE) or reponse.get(PC.ENTETE_SIGNALEMENT) or ""
    m = re.search(r"'nonce-([A-Za-z0-9_-]+)'", entete)
    return m.group(1) if m else None


def defauts(html, nonce):
    """Ce qui ne passerait pas la politique : script ou style intégré sans le jeton, gestionnaire en attribut, lien
    ``javascript:``, ressource d'un autre site, cadre ou objet."""
    p = _Balises()
    p.feed(html)
    sortie = []
    for tag, a in p.balises:
        for nom, valeur in a.items():
            if nom.startswith("on"):
                sortie.append(f"<{tag} {nom}=…> : gestionnaire en attribut")
            if nom in ("href", "src", "action", "formaction") and valeur.strip().lower().startswith("javascript:"):
                sortie.append(f"<{tag} {nom}=javascript:…>")
        if tag == "script":
            if a.get("src"):
                if EXTERNE.match(a["src"]):
                    sortie.append(f"script d'un autre site : {a['src']}")
            elif a.get("type", "").lower() != "application/json" and a.get("nonce") != nonce:
                sortie.append("script intégré sans le jeton")
        elif tag == "style" and a.get("nonce") != nonce:
            sortie.append("style intégré sans le jeton")
        elif tag in ("img", "link", "source", "video", "audio") and EXTERNE.match(a.get("src") or a.get("href") or "") and (
                tag != "link" or "stylesheet" in a.get("rel", "") or "icon" in a.get("rel", "")):
            sortie.append(f"<{tag}> d'un autre site")
        elif tag in ("iframe", "frame", "object", "embed"):
            sortie.append(f"<{tag}>")
    return sortie


@override_settings(ROOT_URLCONF="collecte.test_politique_contenus_pages")
class PolitiqueContenusPagesTests(Balayage):
    def verifier_page(self, rep, quoi, vus):
        if not rep.get("Content-Type", "").startswith("text/html"):
            return
        nonce = jeton(rep)
        self.assertIsNotNone(nonce, f"{quoi} : page sans politique ({rep.status_code})")
        self.assertNotIn(nonce, vus, f"{quoi} : jeton déjà servi")
        vus.add(nonce)
        self.assertEqual(rep[PC.ENTETE], PC.politique(nonce), quoi)
        html = rep.content.decode("utf-8", "replace")
        self.assertEqual(defauts(html, nonce), [], f"{quoi} ({rep.status_code})")
        return html

    def test_toutes_les_adresses_pour_chaque_role(self):
        vus, pages = set(), 0
        anonyme = Client()
        comptes = [("anonyme", None), ("admin", self.admin), ("validateur", self.validateur), ("contributeur", self.contrib),
                   ("lecteur", self.lecteur), ("auditeur", self.auditeur)]
        for nom, u in comptes:
            c = anonyme if u is None else Client()
            if u is not None:
                c.force_login(u)
            for ns, n, motif in routes():
                if n in ("logout",) or motif.startswith("essai-csp/"):
                    continue
                url = self.url(motif)
                rep = c.get(url)
                if self.verifier_page(rep, f"{nom} GET {url}", vus) is not None:
                    pages += 1
        self.assertGreater(pages, 300)  # environ 120 adresses par rôle connecté répondent par une page

    def test_mode_expert(self):
        self.admin.is_staff = self.admin.is_superuser = True
        self.admin.save()
        self.client.force_login(self.admin)
        vus = set()
        urls = ["/admin/"] + [reverse(f"admin:{m._meta.app_label}_{m._meta.model_name}_changelist") for m in site_expert._registry][:12]
        for url in urls:
            rep = self.client.get(url)
            self.assertEqual(rep.status_code, 200, url)
            self.verifier_page(rep, url, vus)

    def test_assistant_de_mise_en_place(self):
        Instance.objects.filter(pk=Instance.courante().pk).update(mise_en_place_terminee=False, mise_en_place_etape=2)
        self.client.force_login(self.admin)
        vus = set()
        for etape in range(2, 9):
            rep = self.client.get(reverse("parametres:mise_en_place_etape", args=[etape]))
            self.assertEqual(rep.status_code, 200, etape)
            self.verifier_page(rep, f"étape {etape}", vus)

    def test_pages_d_erreur(self):
        logging.disable(logging.CRITICAL)  # erreurs volontaires : rien au journal des tests
        self.addCleanup(logging.disable, logging.NOTSET)
        c = Client(raise_request_exception=False)
        vus = set()
        for url, code in (("/essai-csp/boum/", 500), ("/essai-csp/forgee/", 400), ("/nulle-part/", 404)):
            rep = c.get(url)
            self.assertEqual(rep.status_code, code, url)
            self.verifier_page(rep, url, vus)
            self.assertIn(f'<style nonce="{jeton(rep)}">', rep.content.decode())
        c.force_login(self.contrib)
        rep = c.get(reverse("collecte:admin_accueil"))  # 403
        self.assertEqual(rep.status_code, 403)
        self.verifier_page(rep, "403", vus)
        csrf = Client(enforce_csrf_checks=True)
        rep = csrf.post(reverse("login"), {"username": "x", "password": "y"})  # sans jeton CSRF
        self.assertEqual(rep.status_code, 403)
        self.verifier_page(rep, "échec CSRF", vus)

    def test_reponses_qui_ne_sont_pas_des_pages_et_fichiers_proteges(self):
        rep = self.client.get("/essai-csp/json/")
        self.assertNotIn(PC.ENTETE, rep)
        rep = self.client.get("/essai-csp/protegee/")
        self.assertEqual(rep[PC.ENTETE], "default-src 'none'")  # jamais affaiblie
        self.assertNotIn(PC.ENTETE_SIGNALEMENT, rep)
        rep = self.client.post("/mcp/", "{}", content_type="application/json")  # serveur MCP : JSON, sans politique
        self.assertNotIn(PC.ENTETE, rep)
        self.assertNotEqual(rep.status_code, 500)

    def test_signalement_seulement(self):
        with override_settings(POLITIQUE_CONTENUS_MODE="report-only"):
            rep = self.client.get(reverse("login"))
            self.assertNotIn(PC.ENTETE, rep)
            self.assertEqual(rep[PC.ENTETE_SIGNALEMENT], PC.politique(jeton(rep)))
        with override_settings(POLITIQUE_CONTENUS_MODE="n'importe quoi"):  # valeur inconnue : politique bloquante
            rep = self.client.get(reverse("login"))
            self.assertIn(PC.ENTETE, rep)
        self.assertIn(PC.ENTETE, self.client.get(reverse("login")))

    def test_variable_d_environnement(self):
        """``CONTENT_SECURITY_POLICY_MODE`` (docs/installation.md) : bloquante sans variable, signalement à la demande."""
        import tempfile

        from parametres.aides_tests.hebergement import reglages

        with tempfile.TemporaryDirectory() as d:
            code = "print(json.dumps(s.POLITIQUE_CONTENUS_MODE))"
            self.assertEqual(reglages({"DATA_DIR": d, "CONTENT_SECURITY_POLICY_MODE": ""}, code), "enforce")
            self.assertEqual(reglages({"DATA_DIR": d, "CONTENT_SECURITY_POLICY_MODE": "report-only"}, code), "report-only")

    def test_politique_stricte_pour_les_scripts(self):
        p = PC.politique("abc")
        directives = dict((d.split(" ", 1) + [""])[:2] for d in p.split("; "))
        self.assertEqual(directives["script-src"], "'self' 'nonce-abc'")
        self.assertNotIn("unsafe-eval", p)
        self.assertNotIn("unsafe-inline", directives["script-src"])
        self.assertEqual(directives["style-src-elem"], "'self' 'nonce-abc'")
        for d, v in (("default-src", "'self'"), ("object-src", "'none'"), ("base-uri", "'self'"), ("frame-ancestors", "'none'"),
                     ("form-action", "'self'"), ("connect-src", "'self'"), ("font-src", "'self'"), ("frame-src", "'none'")):
            self.assertEqual(directives[d], v, d)
