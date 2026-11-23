"""Aides des tests du navigateur (Playwright, Chromium) : lancement du navigateur, base des tests, axe-core."""
import asyncio
import glob
from contextlib import contextmanager
import datetime
import os
import shutil
import tempfile
import time
from decimal import Decimal

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.utils import timezone

from collecte.models import Campagne, Reponse
from collecte.outils_tests import RetourSerialiseIndependantDeLOrdre, ServeurDeTestUnSeulFil, hors_requete, navigateur_indisponible
from parametres.referentiel import unite_depuis_symbole as U
from referentiel.models import KPI, Niveau, Organisation, Utilisateur

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - poste sans Playwright
    sync_playwright = None


@contextmanager
def _hors_boucle():
    """Lecture ou écriture en base pendant que Playwright tourne : sa boucle asyncio, active dans ce fil, ferait
    passer l'ORM par une autre connexion que celle du serveur de test (SQLite en mémoire : « table is locked »). On la
    retire le temps de l'appel, et l'ORM reprend la connexion du fil, partagée avec le serveur. L'appel n'a jamais lieu
    pendant que le serveur de test traite une requête (``hors_requete`` : sans quoi une lecture faite pendant un
    enregistrement voit une ligne à moitié écrite)."""
    boucle = asyncio.events._get_running_loop()
    asyncio.events._set_running_loop(None)
    try:
        with hors_requete():
            yield
    finally:
        asyncio.events._set_running_loop(boucle)


def _lancer_chromium(pw):
    chemins = glob.glob("/opt/pw-browsers/chromium*/chrome-linux*/chrome")
    return pw.chromium.launch(executable_path=chemins[0]) if chemins else pw.chromium.launch()


D = Decimal

# Politique de sécurité des contenus (collecte/politique_contenus.py) : toute violation, dans n'importe quel test du
# navigateur, fait échouer le test. Chromium l'écrit dans la console (« Refused to … because it violates the following
# Content Security Policy directive ») ; l'évènement ``securitypolicyviolation`` la redit avec la directive et la source.
SURVEILLANCE_CSP = """document.addEventListener("securitypolicyviolation", (e) => {
  console.error(`[csp] ${e.effectiveDirective} bloqué : ${e.blockedURI || "intégré"} (${e.sourceFile}:${e.lineNumber}) ${e.sample}`);
}, true);"""


def surveiller_politique(test, page):
    """Note dans ``page.violations_csp`` toute violation de la politique dans le contexte de la page (onglets ouverts
    ensuite compris) ; le test échoue à la fin s'il y en a eu une."""
    page.violations_csp = []

    def console(message):
        texte = message.text
        if "[csp]" in texte or "Content Security Policy" in texte:
            page.violations_csp.append(texte)
    page.context.on("console", console)
    page.context.add_init_script(SURVEILLANCE_CSP)
    if not hasattr(test, "_pages_csp"):
        test._pages_csp = []
        test.addCleanup(lambda: test.assertEqual([v for p in test._pages_csp for v in p.violations_csp], [],
                                                 "violation de la politique de sécurité des contenus"))
    test._pages_csp.append(page)
    return page

# Délai d'une ATTENTE explicite d'un résultat (réponse d'un fetch, image, rechargement, téléchargement) : le serveur de test n'a
# qu'un fil (``ServeurDeTestUnSeulFil``) et sert, sous charge, une vingtaine de captures ou plusieurs requêtes à la suite. Les
# gestes (clic, saisie) gardent le délai par défaut de la page : une attente plus longue ne rend aucun test plus tolérant à un
# défaut, elle ne change que le temps que met à échouer un test qui échoue.
ATTENTE_LONGUE = 30000
_ATTENTES = ("wait_for_selector", "wait_for_url", "wait_for_load_state", "expect_navigation",
             "expect_download", "expect_response", "expect_request")


def attentes_longues(page):
    """Les attentes explicites de la page (``wait_for_*``, ``expect_*``) durent ``ATTENTE_LONGUE`` sauf délai donné ; les
    pages des tests du navigateur passent toutes par ici. Le ``set_default_timeout`` de la page ne vaut que pour les gestes."""
    def avec_delai(fonction):
        def attendre(*args, **kwargs):
            kwargs.setdefault("timeout", ATTENTE_LONGUE)
            return fonction(*args, **kwargs)
        return attendre

    for nom in _ATTENTES:
        setattr(page, nom, avec_delai(getattr(page, nom)))
    page.wait_for_function = attente_sans_eval(page)
    page.add_script_tag = script_ajoute_sans_jeton(page)
    return page


def script_ajoute_sans_jeton(page):
    """``add_script_tag(content=…)`` (axe-core) : un ``<script>`` ajouté sans le jeton de la page serait refusé par la
    politique de sécurité des contenus ; le texte est évalué par ``page.evaluate`` (protocole du navigateur, hors
    politique), ce qui définit les mêmes variables globales. Les autres formes (``url=`` de l'outil) restent celles de
    Playwright."""
    origine = page.add_script_tag

    def ajouter(url=None, path=None, content=None, type=None):
        if content is not None and url is None and path is None and type is None:
            page.evaluate(content)
            return None
        return origine(url=url, path=path, content=content, type=type)
    return ajouter


def attente_sans_eval(page):
    """``wait_for_function`` sans ``eval`` dans la page. Celle de Playwright évalue l'expression par ``globalThis.eval``
    dans la page, que la politique de sécurité des contenus de l'outil refuse (pas de ``unsafe-eval``, voir
    collecte/politique_contenus.py) ; ici l'expression est évaluée par ``page.evaluate`` (protocole du navigateur, hors
    politique), toutes les 50 ms, jusqu'à une valeur vraie ou la fin du délai. Même signature, même erreur au délai."""
    from playwright.sync_api import Error as ErreurPlaywright
    from playwright.sync_api import TimeoutError as DelaiDepasse

    def attendre(expression, arg=None, timeout=ATTENTE_LONGUE, polling=None):
        fin = time.monotonic() + (timeout or ATTENTE_LONGUE) / 1000
        intervalle = polling if isinstance(polling, (int, float)) else 50
        while True:
            try:
                resultat = page.evaluate(expression, arg)
            except ErreurPlaywright as e:  # page en cours de rechargement : on réessaie
                if "context was destroyed" not in str(e) and "navigat" not in str(e):
                    raise
                resultat = None
            if resultat:
                return resultat
            if time.monotonic() > fin:
                raise DelaiDepasse(f"Délai de {timeout} ms dépassé en attendant : {expression}")
            page.wait_for_timeout(intervalle)
    return attendre


def attendre_images(page, selecteur):
    """Attend que chaque image du sélecteur soit chargée : ``naturalWidth > 0`` (``complete`` est vrai aussi pour une image en
    échec, qui ne se chargera jamais). Une image manquante fait échouer le test, avec la liste de celles qui manquent."""
    attente = ("(s) => { const l = [...document.querySelectorAll(s)]; return l.length > 0 && l.every(i => i.naturalWidth > 0); }")
    try:
        page.wait_for_function(attente, arg=selecteur, timeout=ATTENTE_LONGUE)
    except Exception as e:  # noqa: BLE001 - délai dépassé : on dit quelles images manquent
        manquantes = page.evaluate("(s) => [...document.querySelectorAll(s)].filter(i => i.naturalWidth === 0).map(i => i.getAttribute('src'))",
                                   selecteur)
        raise AssertionError(f"Images non chargées ({len(manquantes)}) : {manquantes[:5]}") from e


class NavigateurBase(ServeurDeTestUnSeulFil, RetourSerialiseIndependantDeLOrdre, StaticLiveServerTestCase):
    """Un groupe, un pays, deux entités ; un KPI « Effectif » validé sur trois exercices clôturés."""

    serialized_rollback = True

    @classmethod
    def setUpClass(cls):
        if sync_playwright is None:
            navigateur_indisponible("Playwright n'est pas installé.")
        cls._async = os.environ.get("DJANGO_ALLOW_ASYNC_UNSAFE")
        os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
        cls._media = tempfile.mkdtemp()
        cls._reglage_media = override_settings(MEDIA_ROOT=cls._media)
        cls._reglage_media.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._reglage_media.disable()
        shutil.rmtree(cls._media, ignore_errors=True)
        if cls._async is None:
            os.environ.pop("DJANGO_ALLOW_ASYNC_UNSAFE", None)
        else:
            os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = cls._async

    def setUp(self):
        super().setUp()
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.e1 = Organisation.objects.create(nom="Lille", niveau_id=Niveau.ENTITY, parent=self.p)
        self.e2 = Organisation.objects.create(nom="Lyon", niveau_id=Niveau.ENTITY, parent=self.p)
        unite = U("ETP")
        self.eff = KPI.objects.create(code="EFF", libelle="Effectif", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                                      methode_agregation="Somme", unite=unite, decimales=0)
        self.campagnes = []
        for i, an in enumerate((2023, 2024, 2025)):
            c = Campagne.objects.create(exercice=an, statut=Campagne.Statut.CLOTUREE)
            self.campagnes.append(c)
            for o, v in ((self.e1, 100 + 10 * i), (self.e2, 40 + 5 * i)):
                Reponse.objects.create(periode=c.periode, kpi=self.eff, organisation=o, valeur=D(v), statut="valide",
                                       origine="import")
        fin = timezone.localdate() + datetime.timedelta(days=30)
        Campagne.objects.create(exercice=2026, statut=Campagne.Statut.OUVERTE, date_fin_saisie=fin)
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        self.lecteur = Utilisateur.objects.create(username="lecteur", email="lecteur@exemple.test", role=Utilisateur.Role.LECTEUR)
        self._pw = self.navigateur = None

    def tearDown(self):
        if self._pw is not None:
            self.navigateur.close()
            self._pw.stop()
        super().tearDown()

    def page(self, utilisateur=None, largeur=1440, hauteur=900, tactile=False):
        with _hors_boucle():
            self.client.force_login(utilisateur or self.admin)
        if self._pw is None:
            self._pw = sync_playwright().start()
            try:
                self.navigateur = _lancer_chromium(self._pw)
            except Exception as e:  # noqa: BLE001 - navigateur absent : test ignoré
                self._pw.stop()
                self._pw = None
                navigateur_indisponible(f"Chromium indisponible : {e}")
        ctx = self.navigateur.new_context(viewport={"width": largeur, "height": hauteur}, accept_downloads=True, has_touch=tactile,
                                          is_mobile=tactile)
        ctx.add_cookies([{"name": settings.SESSION_COOKIE_NAME, "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value,
                          "url": self.live_server_url}])
        page = ctx.new_page()
        page.set_default_timeout(8000)
        attentes_longues(page)
        page.erreurs = []
        page.on("pageerror", lambda e: page.erreurs.append(str(e)))
        return surveiller_politique(self, page)

    def aller(self, page, chemin):
        page.goto(self.live_server_url + chemin)
        page.wait_for_load_state("networkidle")


AXE = os.environ.get("AXE_JS", "")
