"""Aides communes aux tests.

``script_des_pages()`` : texte complet du script des pages. ``collecte/templates/collecte/_app.js`` n'est plus qu'une
liste de ``{% include %}`` (une seule fonction englobante découpée en morceaux, dossier ``_app/``) : les tests qui
cherchent un morceau de code (``assertIn``) ou vérifient qu'un ancien code a disparu (``assertNotIn``) lisent les
morceaux dans l'ordre des inclusions, jamais le seul ``_app.js``, sans quoi un ``assertNotIn`` passerait toujours.

``xlsx(lignes)`` : petit fichier Excel déposé dans un formulaire (import de valeurs, de configuration, de traductions)."""
import io
import re
import threading
from contextlib import contextmanager
from pathlib import Path

GABARITS = Path(__file__).resolve().parent / "templates"
APP_JS = GABARITS / "collecte/_app.js"
INCLUSION = re.compile(r"""{%\s*include\s+["']([^"']+)["']\s*%}""")


def script_des_pages():
    """Texte du script des pages : les morceaux inclus par ``_app.js``, lus dans l'ordre et mis bout à bout."""
    morceaux = INCLUSION.findall(APP_JS.read_text(encoding="utf-8"))
    if not morceaux:
        raise AssertionError(f"aucun {{% include %}} dans {APP_JS}")
    return "".join((GABARITS / m).read_text(encoding="utf-8") for m in morceaux)


def html_de(client, url, statut=200, **extra):
    """Texte de la page ``url`` ; échoue d'abord si le statut n'est pas ``statut`` (200 par défaut), sans quoi une page
    d'erreur ou une redirection serait lue comme une page vide et les ``assertNotIn`` passeraient à tort."""
    reponse = client.get(url, **extra)
    if reponse.status_code != statut:
        raise AssertionError(f"{url} : statut {reponse.status_code} au lieu de {statut}")
    return reponse.content.decode()


def navigateur_indisponible(raison):
    """Les tests du navigateur (Playwright, Chromium) ne peuvent pas tourner : saut (``SkipTest``), sauf si la variable
    d'environnement ``REQUIRE_BROWSER_TESTS=1`` est posée (intégration continue, recette) : échec explicite, pour qu'un
    module manquant ne laisse jamais passer la suite au vert sans ces tests."""
    import os
    import unittest

    if os.environ.get("REQUIRE_BROWSER_TESTS", "").strip() == "1":
        raise AssertionError(f"REQUIRE_BROWSER_TESTS=1 : les tests du navigateur doivent tourner ({raison})")
    raise unittest.SkipTest(raison)


class RetourSerialiseIndependantDeLOrdre:
    """À mettre devant ``TransactionTestCase`` (ou un de ses dérivés) avec ``serialized_rollback = True``.

    Un ``TransactionTestCase`` sans ``serialized_rollback`` vide la base à sa fin ; Django recrée alors les types de
    contenu (et les permissions) avec de nouveaux identifiants. La remise à l'état d'origine d'une classe
    ``serialized_rollback`` qui passe ensuite réinsère ceux du cliché : ``UNIQUE constraint failed:
    django_content_type…``, selon l'ordre des tests (toujours en parallèle, ou avec ``--shuffle``). On efface donc les
    types de contenu avant la remise : le cliché les réinsère, avec leurs permissions, tels que la base les avait.

    Le cliché est réinséré avec les numéros d'origine des lignes, et Django ne remet pas les séquences au-dessus
    (PostgreSQL ; SQLite les suit tout seul). Un test précédent qui a ramené les séquences au début (restauration d'une
    sauvegarde : ``flush`` les remet à 1, ``loaddata`` ne relève que celles des tables de l'archive) laissait alors la
    création suivante reprendre un numéro déjà pris : « duplicate key value violates unique constraint
    collecte_reglageexport_pkey », selon l'ordre des tests. Les séquences des tables du cliché sont donc remises
    au-dessus de leur plus grand numéro après la remise, comme le fait ``loaddata``."""

    @classmethod
    def _fixture_setup(cls):  # méthode de classe depuis Django 5.2 (instance avant)
        from django.contrib.contenttypes.models import ContentType
        from django.db import connections

        remises = []
        for alias in cls._databases_names(include_mirrors=False):
            connexion = connections[alias]
            if cls.serialized_rollback and hasattr(connexion, "_test_serialized_contents"):
                remises.append(connexion)
                if ContentType._meta.db_table in connexion.introspection.table_names():
                    ContentType.objects.using(alias).all().delete()  # supprime aussi les permissions
        super()._fixture_setup()
        ContentType.objects.clear_cache()
        for connexion in remises:
            _sequences_au_dessus_du_cliche(connexion)


def _modeles_du_cliche(connexion):
    """Modèles des lignes du cliché de la base de test ``connexion`` (lu une fois par base et par cliché)."""
    import json

    from django.apps import apps

    contenu = connexion._test_serialized_contents
    deja = getattr(connexion, "_modeles_du_cliche", None)
    if deja is None or deja[0] is not contenu:
        labels = {o["model"] for o in json.loads(contenu or "[]")}
        deja = (contenu, [apps.get_model(label) for label in sorted(labels)])
        connexion._modeles_du_cliche = deja
    return deja[1]


def _sequences_au_dessus_du_cliche(connexion):
    """Séquences des tables du cliché remises à leur plus grand numéro (``loaddata`` fait de même après un chargement)."""
    from django.core.management.color import no_style

    requetes = connexion.ops.sequence_reset_sql(no_style(), _modeles_du_cliche(connexion))  # [] sous SQLite
    if requetes:
        with connexion.cursor() as c:
            for sql in requetes:
                c.execute(sql)


def tables_en_retard(connexion):
    """Tables dont la séquence donnerait un numéro déjà pris (prochain numéro <= plus grand numéro), avec ces deux
    numéros ; PostgreSQL seulement (SQLite suit seul le plus grand numéro : liste vide)."""
    from django.apps import apps

    if connexion.vendor != "postgresql":
        return []
    en_retard = []
    tables = set(connexion.introspection.table_names())
    with connexion.cursor() as c:
        for modele in apps.get_models(include_auto_created=True):
            champ = modele._meta.pk
            if champ.get_internal_type() not in ("AutoField", "BigAutoField", "SmallAutoField"):
                continue
            table = modele._meta.db_table
            if table not in tables:
                continue
            c.execute("SELECT pg_get_serial_sequence(%s, %s)", [connexion.ops.quote_name(table), champ.column])
            sequence = c.fetchone()[0]
            if not sequence:
                continue
            c.execute(f"SELECT last_value, is_called FROM {sequence}")
            dernier, appelee = c.fetchone()
            prochain = dernier + 1 if appelee else dernier
            c.execute(f"SELECT MAX({connexion.ops.quote_name(champ.column)}) FROM {connexion.ops.quote_name(table)}")
            plus_grand = c.fetchone()[0]
            if plus_grand is not None and prochain <= plus_grand:
                en_retard.append(f"{table} (prochain {prochain}, plus grand {plus_grand})")
    return en_retard


_VERROU_REQUETES = threading.RLock()  # réentrant : _hors_boucle imbriqués


@contextmanager
def hors_requete():
    """Lecture (ou écriture) de la base par le fil des tests, jamais pendant que le serveur de test
    (``ServeurDeTestUnSeulFil``) traite une requête : elle attend la fin de la requête en cours, et la suivante attend la
    fin de la lecture. Sous SQLite en mémoire, le serveur et le fil des tests partagent la même connexion : lue pendant
    un enregistrement, la ligne était déjà créée mais pas encore remplie (valeur vide, « à saisir »). Attendre côté
    navigateur qu'aucune requête ne soit en cours ne suffit pas : Chromium déclare abandonné (net::ERR_ABORTED) l'envoi
    « keepalive » parti au déchargement de la page, que le serveur reçoit et traite pourtant ensuite."""
    with _VERROU_REQUETES:
        yield


def _fil_serveur_un_seul_fil():
    from django.core.servers.basehttp import WSGIServer
    from django.test.testcases import LiveServerThread

    class ServeurUnSeulFil(WSGIServer):
        request_queue_size = 64  # requêtes parallèles du navigateur : attendues, pas refusées

        def __init__(self, *args, connections_override=None, **kwargs):  # remplacement déjà posé dans le fil (run)
            super().__init__(*args, **kwargs)

        def set_app(self, application):
            # chaque requête traitée sous le verrou de hors_requete : jamais pendant une lecture du fil des tests. Posé
            # autour de l'application, pas de toute la connexion : une connexion ouverte d'avance par le navigateur, qui
            # n'a encore rien envoyé, ne bloque pas les lectures du test
            def sous_verrou(environ, start_response):
                with _VERROU_REQUETES:
                    return application(environ, start_response)
            super().set_app(sous_verrou)

    class FilUnSeulServeur(LiveServerThread):
        server_class = ServeurUnSeulFil

    return FilUnSeulServeur


class ServeurDeTestUnSeulFil:
    """À mettre devant ``LiveServerTestCase`` / ``StaticLiveServerTestCase`` (tests du navigateur).

    Sous SQLite en mémoire, Django donne au serveur de test la connexion du fil des tests, partagée par tous les fils
    du serveur, qui traite par défaut chaque requête dans un fil à part. Deux requêtes en même temps (préchargement de
    « Je réponds à », envoi automatique, navigation qui part pendant un fetch) utilisent alors la même connexion SQLite
    à la fois : « bad parameter or other API misuse », IndexError, page d'erreur 500 au hasard. Une installation, elle,
    ouvre une connexion par fil. Le serveur de test traite donc les requêtes l'une après l'autre (Django ferme alors
    chaque connexion HTTP après sa réponse : le navigateur n'en garde aucune ouverte).

    Entre deux tests, la base n'est vidée puis rechargée qu'une fois traitées toutes les requêtes déjà reçues par le
    serveur. Un test peut finir avec des requêtes de la page encore en vol (sections chargées après coup, envoi au
    déchargement) : le navigateur fermé, le serveur les traitait quand même, pendant le vidage ou pendant le rechargement
    de la base du test suivant. Sous SQLite en mémoire (connexion partagée), une écriture du serveur dans le bloc
    atomique du rechargement faisait échouer la préparation du test suivant (« cannot release savepoint - SQL
    statements in progress », puis « An error occurred in the current transaction ») ; sous PostgreSQL, elle écrivait
    dans la base vidée ou dans celle du test suivant. Test : ``collecte/test_serveur_un_seul_fil_remise_base.py``."""

    server_thread_class = _fil_serveur_un_seul_fil()

    def _post_teardown(self):
        _attendre_les_requetes_recues(self.live_server_url)
        super()._post_teardown()

    # vidage et rechargement de la base sous le verrou des requêtes, comme toute lecture du fil des tests : jamais
    # pendant le traitement d'une requête, même arrivée après l'attente ci-dessus
    @classmethod
    def _fixture_setup(cls):  # méthode de classe depuis Django 5.2
        with hors_requete():
            super()._fixture_setup()

    def _fixture_teardown(self):
        with hors_requete():
            super()._fixture_teardown()


def _attendre_les_requetes_recues(adresse):
    """Rend la main quand le serveur de test a traité toutes les requêtes déjà reçues : une requête de plus, qui lui
    arrive après elles (il les prend dans l'ordre d'arrivée, une à une), et l'attente de sa réponse. Appelé après la
    fermeture du navigateur (``tearDown``), qui n'en envoie donc plus. Sans le verrou des requêtes : il serait sinon
    attendu par le serveur, qui attendrait la fin de cette attente."""
    import http.client
    from urllib.parse import urlsplit

    morceaux = urlsplit(adresse)
    connexion = http.client.HTTPConnection(morceaux.hostname, morceaux.port, timeout=120)
    try:
        connexion.request("GET", "/connexion/")  # page de connexion : rien d'écrit, rien de mesuré
        connexion.getresponse().read()
    finally:
        connexion.close()


def xlsx(lignes, onglet="Saisie"):
    """Fichier Excel « fichier.xlsx » (SimpleUploadedFile) : ``lignes`` dans la première feuille, nommée ``onglet``
    (None : nom laissé par openpyxl, « Sheet ») ; ou, si ``lignes`` est un dictionnaire {onglet: lignes}, une feuille
    par onglet, dans cet ordre."""
    from django.core.files.uploadedfile import SimpleUploadedFile
    from openpyxl import Workbook

    wb = Workbook()
    if isinstance(lignes, dict):
        wb.remove(wb.active)
        feuilles = [(wb.create_sheet(nom), ls) for nom, ls in lignes.items()]
    else:
        if onglet:
            wb.active.title = onglet
        feuilles = [(wb.active, lignes)]
    for ws, ls in feuilles:
        for ligne in ls:
            ws.append(ligne)
    flux = io.BytesIO()
    wb.save(flux)
    return SimpleUploadedFile("fichier.xlsx", flux.getvalue())
