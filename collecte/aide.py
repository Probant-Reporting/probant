"""Aide dans l'outil : les guides par rôle (``docs/guides/`` en anglais, ``docs/<langue>/guides/`` dans les six autres langues),
lus par l'outil lui-même, sans Internet, et rendus par le rendu Markdown sûr (``collecte/markdown.py``).

- Un guide par rôle : administrateur, validateur, contributeur, lecteur, auditeur. Chaque guide est découpé en tâches
  (``## Titre {#ancre}``) ; les ancres sont les mêmes dans les sept langues.
- Langue : le guide de la langue de l'interface ; une langue de l'interface sans guide reçoit le guide anglais, avec une note.
- Images : les captures de ``docs/screenshots/<langue>/`` (faites par ``qa/guide_screenshots.js``), servies par l'outil.
- Lien d'aide de la barre du haut : le guide du rôle de la personne, à la section de la page où elle se trouve.
- Accès : toute personne connectée, lecteur et auditeur compris (les guides ne contiennent aucune donnée et la page n'écrit
  rien) ; un rôle peut aussi lire les guides des autres rôles. Sans connexion : renvoi à la page de connexion.

Les guides sont écrits par nous : le rendu les traite comme du texte sûr (tout est échappé), avec en plus les images de
``docs/screenshots/`` (aucune autre image n'est jamais chargée) et les ancres des titres.
"""
import html
import re
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import render
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_GET

from parametres import langues as L

from . import markdown as MD

DOCS = Path(settings.BASE_DIR) / "docs"
IMAGES = DOCS / "screenshots"
LANGUES_GUIDES = ("en", "fr", "es", "de", "it", "nl", "pt")
# guide (adresse) → nom du fichier, par langue ; ordre = ordre d'affichage des liens
GUIDES = {
    "administrator": {"en": "administrator.md", "fr": "administrateur.md", "es": "administrador.md",
                      "de": "administrator.md", "it": "amministratore.md", "nl": "beheerder.md", "pt": "administrador.md"},
    "validator": {"en": "validator.md", "fr": "validateur.md", "es": "validador.md", "de": "validator.md",
                  "it": "validatore.md", "nl": "validator.md", "pt": "validador.md"},
    "contributor": {"en": "contributor.md", "fr": "contributeur.md", "es": "colaborador.md", "de": "mitwirkender.md",
                    "it": "collaboratore.md", "nl": "bijdrager.md", "pt": "colaborador.md"},
    "reader": {"en": "reader.md", "fr": "lecteur.md", "es": "lector.md", "de": "leser.md", "it": "lettore.md",
               "nl": "lezer.md", "pt": "leitor.md"},
    "auditor": {"en": "auditor.md", "fr": "auditeur.md", "es": "auditor.md", "de": "auditor.md", "it": "auditor.md",
                "nl": "auditor.md", "pt": "auditor.md"},
}
ROLE_VERS_GUIDE = {"admin": "administrator", "validateur": "validator", "contributeur": "contributor",
                   "lecteur": "reader", "auditeur": "auditor"}
GUIDE_VERS_ROLE = {g: r for r, g in ROLE_VERS_GUIDE.items()}

# page (nom de l'adresse) → section du guide de chaque rôle ; sans entrée : le début du guide
SECTIONS = {
    # administrateur : section « Saisir et contrôler » (« Rouvrir une saisie validée » décrit une action, pas la page ; pas de section « Pour moi »)
    "saisie": {"contributor": "enter", "validator": "review", "auditor": "read-only", "administrator": "entry"},
    "pour_moi": {"contributor": "find", "validator": "scope"},
    "cellule": {"contributor": "enter", "validator": "review", "administrator": "reopen", "auditor": "read-only"},
    "tableau_de_bord": {"validator": "dashboard", "reader": "dashboard", "auditor": "dashboard", "administrator": "reminders"},
    "consolidation": {"validator": "dashboard", "reader": "consolidation", "auditor": "dashboard", "administrator": "consolidation"},
    "relances": {"validator": "reminders", "administrator": "reminders"},
    "forcages": {"validator": "forced"},
    "coherence": {"contributor": "check", "validator": "alerts", "auditor": "consistency", "administrator": "consistency"},
    "alerte": {"contributor": "check", "validator": "alerts", "auditor": "consistency", "administrator": "consistency"},
    "regles": {"administrator": "consistency"},
    "regle_nouvelle": {"administrator": "consistency"},
    "regle": {"administrator": "consistency"},
    "historique": {"auditor": "history", "administrator": "history"},
    "echanges_importer": {"administrator": "import-values"},
    "export_officiel": {"administrator": "official-formats"},
    "echanges_listes_page": {"administrator": "kpi-lists"},
    "echanges_listes": {"administrator": "kpi-lists"},
    # Paramètres (identité, niveaux, seuils) : une seule section ; les autres onglets ont la leur plus bas
    "identite": {"administrator": "settings"},
    "niveaux": {"administrator": "settings"},
    "seuils": {"administrator": "settings"},
    "visualisation": {"administrator": "visualisation"},  # Paramètres › Visualisation
    "liste": {"administrator": "spaces"},  # espaces/urls.py : « liste » et « nouveau » ne servent qu'aux espaces
    "nouveau": {"administrator": "spaces"},
    # Import / Export s'ouvre sur « Mes exports » : les gros fichiers sont dans le guide de l'administrateur et de l'auditeur
    # (validateur et contributeur : « Importer des valeurs », par le préfixe « echanges » plus bas)
    "echanges": {"administrator": "large-exports", "auditor": "large-exports"},
    "echanges_exporter": {"administrator": "large-exports", "auditor": "large-exports"},
    "echanges_resume": {"administrator": "large-exports", "auditor": "large-exports"},
    "echanges_export_etat": {"administrator": "large-exports", "auditor": "large-exports"},
    "echanges_export_fichier": {"administrator": "large-exports", "auditor": "large-exports"},
    "mon_compte": {"contributor": "account", "validator": "language", "reader": "account", "auditor": "language",
                   "administrator": "account"},
    "admin_accueil": {"administrator": "overview"},
    "admin_journal": {"administrator": "history"},
    "admin_preuves": {"administrator": "evidence-delete"},
    "admin_attributions": {"administrator": "assign"},
    "admin_attributions_lecture_seule": {"administrator": "accounts"},  # comptes en lecture seule qui ont encore des attributions
    "admin_remplacer": {"administrator": "assign"},
    "mise_en_place": {"administrator": "setup"},
    "langues": {"administrator": "languages"},
    "ia": {"administrator": "ai"},
    "reglages": {"administrator": "assistants"},  # Paramètres › Assistants (serveur_mcp)
    "hebergement": {"administrator": "hosting"},
}
# préfixes : pages de la même famille (une campagne, un compte, un référentiel…)
PREFIXES = (
    ("admin_campagne", {"administrator": "campaign"}),
    ("admin_compte", {"administrator": "accounts"}),
    ("admin_organisation", {"administrator": "organisations"}),
    ("referentiel", {"administrator": "framework"}),
    ("installer_", {"administrator": "framework"}),
    ("paquet", {"administrator": "framework"}),
    ("traductions", {"administrator": "languages"}),
    ("sauvegarde", {"administrator": "hosting"}),
    ("echanges", {"contributor": "import", "validator": "import"}),
    ("visu", {"reader": "visualisation", "auditor": "dashboard", "contributor": "visualisation", "administrator": "visualisation"}),
)
_ENTETE = re.compile(r"^(#{1,6})[ \t]+(.*?)(?:[ \t]+\{#([a-z0-9-]+)\})?[ \t]*$")
_IMAGE_SEULE = re.compile(r"^!\[([^\[\]\n]{0,500})\]\(\s*([^()\s]{1,300})\s*\)\s*$")
_CHEMIN_IMAGE = re.compile(r"^(?:\.\./)+screenshots/(" + "|".join(LANGUES_GUIDES) + r")/([a-z0-9_-]{1,80}\.png)$")
# phrase qui renvoie à l'autre langue (inutile dans l'outil, où la langue est choisie par l'outil)
_AUTRE_VERSION = re.compile(r"\s*(?:French version|Version anglaise|Versión en inglés|Englische Version|Versione inglese|"
                            r"Engelse versie|Versão em inglês)\s*:\s*\[[^\]\n]*\]\([^)\n]*\)\.?")


def langue_guide(langue=None):
    """Langue des guides pour une langue de l'interface : la même si elle a ses guides, sinon l'anglais."""
    langue = langue or L.interface()
    return langue if langue in LANGUES_GUIDES else "en"


def guide_du_role(user):
    """Adresse du guide du rôle de la personne (« administrator », « validator »…)."""
    return ROLE_VERS_GUIDE.get("admin" if user.est_admin else user.role, "contributor")


def chemin_guide(guide, langue):
    nom = GUIDES.get(guide, {}).get(langue)
    return (DOCS / "guides" / nom if langue == "en" else DOCS / langue / "guides" / nom) if nom else None


def _rendre(texte, langue):
    """(titre, html, [(ancre, titre de section)]) d'un guide : tout le texte est échappé par ``markdown.rendu``. Les titres
    ``## … {#ancre}`` reçoivent leur ancre, une ligne qui n'est qu'une image de ``docs/screenshots/<langue>/`` devient une
    figure servie par l'outil."""
    titre, sortie, sommaire, tampon = "", [], [], []

    def vider():
        if any(l.strip() for l in tampon):
            sortie.append(str(MD.rendu(_AUTRE_VERSION.sub("", "\n".join(tampon)), niveau_titre=1)))
        tampon.clear()

    for ligne in MD.normaliser(texte).split("\n"):
        m = _ENTETE.match(ligne)
        if m and len(m.group(1)) <= 2:
            vider()
            niveau, nom, ancre = len(m.group(1)), m.group(2), m.group(3)
            if niveau == 1:
                titre = nom
                sortie.append(f"<h1>{html.escape(nom)}</h1>")
            else:
                interne = str(MD.rendu(f"# {nom}", niveau_titre=2))  # <h2>…</h2> avec le texte mis en forme
                if ancre:
                    sommaire.append((ancre, MD.texte_brut(nom)))
                    interne = interne.replace("<h2>", f'<h2 id="{ancre}">', 1)
                sortie.append(interne)
            continue
        m = _IMAGE_SEULE.match(ligne.strip())
        chemin = _CHEMIN_IMAGE.match(m.group(2)) if m else None
        if chemin:
            vider()
            url = reverse("collecte:aide_image", args=[chemin.group(1), chemin.group(2)])
            sortie.append(f'<figure class="guide-figure"><img src="{html.escape(url)}" alt="{html.escape(m.group(1))}" '
                          f'loading="lazy"></figure>')
            continue
        tampon.append(ligne)
    vider()
    return titre, "".join(sortie), sommaire


@lru_cache(maxsize=32)
def _lu(chemin, date_modif, langue):
    return _rendre(Path(chemin).read_text(encoding="utf-8"), langue)


def lire(guide, langue):
    """(titre, html sûr, sommaire) du guide dans la langue donnée (en ou fr) ; Http404 si le guide n'existe pas."""
    chemin = chemin_guide(guide, langue)
    if chemin is None or not chemin.is_file():
        raise Http404
    titre, corps, sommaire = _lu(str(chemin), chemin.stat().st_mtime_ns, langue)
    return titre, mark_safe(corps), sommaire


def ancres(guide, langue):
    return {a for a, _ in lire(guide, langue)[2]}


def lien_aide(user, nom_adresse, langue=None):
    """Adresse du guide du rôle de la personne, à la section de la page où elle se trouve (sans ancre si aucune ne convient)."""
    guide = guide_du_role(user)
    section = SECTIONS.get(nom_adresse or "", {}).get(guide)
    if section is None:
        for prefixe, par_guide in PREFIXES:
            if (nom_adresse or "").startswith(prefixe) and guide in par_guide:
                section = par_guide[guide]
                break
    url = reverse("collecte:aide")
    if section and section in ancres(guide, langue_guide(langue)):
        url += f"#{section}"
    return url


@login_required
@require_GET
def page(request, guide=None):
    """Guide d'un rôle (le sien par défaut), dans la langue de l'interface."""
    if guide is None:
        guide = guide_du_role(request.user)
    if guide not in GUIDES:
        raise Http404
    langue_ui = L.interface()
    titre, corps, sommaire = lire(guide, langue_guide(langue_ui))
    from parametres.libelles import libelle

    autres = [(reverse("collecte:aide_guide", args=[g]), libelle(f"choix.utilisateur.role.{GUIDE_VERS_ROLE[g]}"))
              for g in GUIDES if g != guide]
    return render(request, "collecte/aide.html", {
        "page": "aide", "guide": guide, "titre_guide": titre, "corps": corps, "sommaire": sommaire, "autres": autres,
        "guide_son_role": guide == guide_du_role(request.user), "langue_guide": langue_guide(langue_ui), "langue_hors_guides": langue_ui not in LANGUES_GUIDES,
    })


@login_required
@require_GET
def image(request, langue, nom):
    """Une capture de ``docs/screenshots/<langue>/`` (nom contrôlé : lettres, chiffres, tiret et soulignement, ``.png``)."""
    if langue not in LANGUES_GUIDES or not re.fullmatch(r"[a-z0-9_-]{1,80}\.png", nom):
        raise Http404
    chemin = IMAGES / langue / nom
    if not chemin.is_file():
        raise Http404
    reponse = FileResponse(chemin.open("rb"), content_type="image/png")
    reponse["Cache-Control"] = "private, max-age=3600"
    return reponse


def contexte(request):
    """Lien d'aide de la barre du haut de toutes les pages (personne connectée seulement)."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    correspondance = getattr(request, "resolver_match", None)
    try:
        return {"aide_url": lien_aide(user, correspondance.url_name if correspondance else "")}
    except Http404:
        return {}  # fichiers des guides absents (paquet incomplet) : pas de lien, la page reste utilisable

