"""Réponses rédigées (format « texte rédigé ») : rendu Markdown SÛR, extrait en texte brut, limite de longueur.

Petit rendu maison sur un sous-ensemble du Markdown, sans dépendance :
- blocs : titres ``#``, ``##``, ``###`` (rendus sous le niveau de titre de la page : h4 à h6 par défaut), paragraphes (un
  retour à la ligne simple est gardé), listes à puces (``-``, ``*``, ``+``) et numérotées (``1.`` ou ``1)``), citations
  (``>``), blocs de code (```` ``` ````), trait de séparation (``---``), tableaux simples (``| a | b |`` puis ``|---|---|``) ;
- dans une ligne : gras (``**x**``, ``__x__``), italique (``*x*``, ``_x_``), barré (``~~x~~``), code (`` `x` ``), liens
  ``[texte](https://…)``.

Sécurité : TOUT le texte est échappé (``html.escape``) avant la moindre transformation ; aucun HTML écrit par la personne ne
passe (« <script> » s'affiche tel quel). Les seules balises produites sont celles du rendu, sans attribut venu du texte
sauf l'adresse d'un lien, acceptée seulement en ``http://``, ``https://`` ou ``mailto:`` (sinon le texte du lien reste, sans
lien), et ouverte dans un nouvel onglet avec ``rel="noopener noreferrer"``. Une image (``![texte](adresse)``) n'est jamais
chargée : elle devient un lien (même règle d'adresse). Aucun attribut d'événement (``on…``), de style ou de classe ne peut
venir du texte.
"""
import html
import re

from django.utils.safestring import mark_safe

TEXTE_MAX = 20_000  # caractères d'une réponse rédigée (vérifié au serveur : saisie, imports, fichiers)
EXTRAIT = 80  # caractères de l'extrait montré dans les listes (Saisie, Pour moi, historique)

SCHEMAS_PERMIS = ("http://", "https://", "mailto:")

# Motifs sans retour en arrière coûteux : un texte piégé (des milliers d'espaces, de « ** » ou de « [ ») ne doit pas
# bloquer le serveur. Les « # » de fin d'un titre sont retirés par ``_texte_titre``, pas par le motif.
_TITRE = re.compile(r"^(#{1,6})[ \t]+(.*)$")
_PUCE = re.compile(r"^\s{0,3}[-*+]\s+(.*)$")
_NUMERO = re.compile(r"^\s{0,3}(\d{1,9})[.)]\s+(.*)$")
_CITATION = re.compile(r"^\s{0,3}>\s?(.*)$")
_TRAIT = re.compile(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$")
_CLOTURE = re.compile(r"^\s{0,3}```")
_LIGNE_TABLEAU = re.compile(r"^\s*\|.*\|\s*$")
_SEPARATEUR_TABLEAU = re.compile(r"^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$")

# dans une ligne (appliqués au texte déjà échappé : « " » est devenu « &quot; », « < » « &lt; »…)
_CODE = re.compile(r"`([^`\n]+)`")
_IMAGE = re.compile(r"!\[([^\[\]\n]{0,500})\]\(\s*([^()\s]{1,2000})\s*\)")
_LIEN = re.compile(r"\[([^\[\]\n]{1,500})\]\(\s*([^()\s]{1,2000})\s*\)")
_GRAS = re.compile(r"(\*\*|__)(?=\S)(.{1,1000}?)(?<=\S)\1")
_ITALIQUE_ETOILE = re.compile(r"(?<![*\w])\*(?=\S)(.{1,1000}?)(?<=\S)\*(?![*\w])")
_ITALIQUE_SOULIGNE = re.compile(r"(?<![_\w])_(?=\S)(.{1,1000}?)(?<=\S)_(?![_\w])")
_BARRE = re.compile(r"~~(?=\S)(.{1,1000}?)(?<=\S)~~")
_JETON = "\x00{}\x00"
_JETONS = re.compile("\x00(\\d+)\x00")
_CONTROLE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _texte_titre(m):
    """Texte d'un titre reconnu par ``_TITRE``, sans les « # » de fermeture (« ## Titre ## »)."""
    return m.group(2).rstrip().rstrip("#").rstrip()


def normaliser(texte):
    """Texte rédigé tel qu'il est enregistré : retours à la ligne « \\n », sans caractère de contrôle (sauf tabulation et
    retour à la ligne), sans espaces au bout des lignes ni lignes vides au début ou à la fin."""
    t = (texte or "").replace("\r\n", "\n").replace("\r", "\n")
    t = "\n".join(l.rstrip() for l in _CONTROLE.sub("", t).split("\n")).strip("\n")
    return t if t.strip() else ""


def adresse_permise(adresse_echappee):
    """Adresse d'un lien (texte échappé) acceptée : http, https ou mailto seulement (pas de javascript:, data:, vbscript:,
    ni d'adresse relative). Renvoie l'adresse échappée à mettre dans ``href``, ou None."""
    brute = html.unescape(adresse_echappee)
    nette = re.sub(r"[\x00-\x20\x7f]", "", brute).lower()
    if not nette.startswith(SCHEMAS_PERMIS) or nette in SCHEMAS_PERMIS:
        return None
    return html.escape(brute, quote=True)


def _lien(texte, adresse):
    href = adresse_permise(adresse)
    if href is None:
        return texte
    return f'<a href="{href}" target="_blank" rel="noopener noreferrer">{texte}</a>'


def _en_ligne(brut):
    """Mise en forme dans une ligne : le texte est d'abord échappé, puis mis en forme."""
    texte, gardes = html.escape(brut, quote=True), []

    def garder(fragment):
        gardes.append(fragment)
        return _JETON.format(len(gardes) - 1)

    t = _CODE.sub(lambda m: garder(f"<code>{m.group(1)}</code>"), texte)  # rien ne se transforme dans du code
    t = _IMAGE.sub(lambda m: garder(_lien(m.group(1) or m.group(2), m.group(2))), t)
    t = _LIEN.sub(lambda m: garder(_lien(_mise_en_forme(m.group(1)), m.group(2))), t)
    t = _mise_en_forme(t)
    while _JETONS.search(t):
        t = _JETONS.sub(lambda m: gardes[int(m.group(1))], t)
    return t


def _mise_en_forme(t):
    t = _GRAS.sub(r"<strong>\2</strong>", t)
    t = _BARRE.sub(r"<del>\1</del>", t)
    t = _ITALIQUE_ETOILE.sub(r"<em>\1</em>", t)
    return _ITALIQUE_SOULIGNE.sub(r"<em>\1</em>", t)


def _cellules(ligne):
    return [c.strip() for c in ligne.strip().strip("|").split("|")]


def rendu(texte, niveau_titre=4):
    """HTML sûr d'une réponse rédigée en Markdown (voir l'en-tête du module). ``niveau_titre`` : niveau HTML du titre
    « # » (les suivants en dessous, h6 au plus)."""
    lignes = normaliser(texte).split("\n")  # structure lue sur le texte brut ; chaque morceau est échappé (_en_ligne)
    sortie, i, n = [], 0, len(lignes)
    while i < n:
        ligne = lignes[i]
        if not ligne.strip():
            i += 1
            continue
        if _CLOTURE.match(ligne):  # bloc de code : tel quel jusqu'à la clôture
            i += 1
            code = []
            while i < n and not _CLOTURE.match(lignes[i]):
                code.append(lignes[i])
                i += 1
            i += 1
            sortie.append("<pre><code>" + html.escape("\n".join(code), quote=True) + "</code></pre>")
            continue
        m = _TITRE.match(ligne)
        if m:
            h = min(6, niveau_titre + len(m.group(1)) - 1)
            sortie.append(f"<h{h}>{_en_ligne(_texte_titre(m))}</h{h}>")
            i += 1
            continue
        if _TRAIT.match(ligne):
            sortie.append("<hr>")
            i += 1
            continue
        if _CITATION.match(ligne):
            bloc = []
            while i < n and _CITATION.match(lignes[i]):
                bloc.append(_CITATION.match(lignes[i]).group(1))
                i += 1
            sortie.append("<blockquote>" + _paragraphes(bloc) + "</blockquote>")
            continue
        if _PUCE.match(ligne) or _NUMERO.match(ligne):
            ordonnee = bool(_NUMERO.match(ligne)) and not _PUCE.match(ligne)
            motif = _NUMERO if ordonnee else _PUCE
            elements, debut = [], _NUMERO.match(ligne).group(1) if ordonnee else None
            while i < n and lignes[i].strip():
                m = motif.match(lignes[i])
                if m:
                    elements.append(m.group(2) if ordonnee else m.group(1))
                elif elements and lignes[i].startswith((" ", "\t")):  # suite de l'élément (ligne en retrait)
                    elements[-1] += "\n" + lignes[i].strip()
                else:
                    break
                i += 1
            balise = "ol" if ordonnee else "ul"
            depart = f' start="{int(debut)}"' if ordonnee and int(debut) != 1 else ""
            sortie.append(f"<{balise}{depart}>" + "".join("<li>" + "<br>".join(_en_ligne(x) for x in e.split("\n")) + "</li>"
                                                          for e in elements)
                          + f"</{balise}>")
            continue
        if _LIGNE_TABLEAU.match(ligne) and i + 1 < n and _SEPARATEUR_TABLEAU.match(lignes[i + 1]) and "|" in lignes[i + 1]:
            entete = _cellules(ligne)
            i += 2
            corps = []
            while i < n and _LIGNE_TABLEAU.match(lignes[i]):
                corps.append(_cellules(lignes[i]))
                i += 1
            th = "".join(f'<th scope="col">{_en_ligne(c)}</th>' for c in entete)
            # data-label : le libellé de la colonne, que la feuille de style écrit devant chaque cellule quand le tableau
            # est présenté en cartes sur téléphone (texte échappé : l'attribut ne porte jamais de balise)
            etiquettes = [html.escape(c.replace("**", "").replace("`", "").strip(), quote=True) for c in entete]
            tr = "".join("<tr>" + "".join(f'<td data-label="{etiquettes[k]}">{_en_ligne(c)}</td>'
                                          for k, c in enumerate((r + [""] * len(entete))[:len(entete)])) + "</tr>"
                         for r in corps)
            sortie.append(f'<div class="md-tableau"><table><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>')
            continue
        bloc = []
        while i < n and lignes[i].strip() and not _debut_de_bloc(lignes, i):
            bloc.append(lignes[i])
            i += 1
        if not bloc:  # ligne qui ressemble à un début de bloc sans en être un (tableau sans séparateur)
            bloc.append(lignes[i])
            i += 1
        sortie.append(_paragraphes(bloc))
    return mark_safe("".join(sortie))


def _debut_de_bloc(lignes, i):
    l = lignes[i]
    return bool(_TITRE.match(l) or _PUCE.match(l) or _NUMERO.match(l) or _CITATION.match(l) or _CLOTURE.match(l)
                or _TRAIT.match(l) or (_LIGNE_TABLEAU.match(l) and i + 1 < len(lignes) and _SEPARATEUR_TABLEAU.match(lignes[i + 1])))


def _paragraphes(lignes):
    """Paragraphes d'un bloc (séparés par une ligne vide) ; un retour à la ligne simple est gardé (<br>)."""
    sortie, courant = [], []
    for l in lignes + [""]:
        if l.strip():
            courant.append(_en_ligne(l.strip()))
        elif courant:
            sortie.append("<p>" + "<br>".join(courant) + "</p>")
            courant = []
    return "".join(sortie)


_MARQUES_BLOC = re.compile(r"^\s{0,3}(#{1,6}\s+|[-*+]\s+|\d{1,9}[.)]\s+|>\s?)")


def texte_brut(texte):
    """Texte sans balises Markdown (titres, listes, emphase, liens réduits à leur texte), sur une ligne."""
    lignes = []
    for l in normaliser(texte).split("\n"):
        if _CLOTURE.match(l) or _TRAIT.match(l) or _SEPARATEUR_TABLEAU.match(l) and "-" in l:
            continue
        l = _MARQUES_BLOC.sub("", l)
        if _LIGNE_TABLEAU.match(l):
            l = " · ".join(c for c in _cellules(l) if c)
        lignes.append(l)
    t = " ".join(x.strip() for x in lignes if x.strip())
    t = _IMAGE.sub(lambda m: m.group(1) or m.group(2), t)
    t = _LIEN.sub(r"\1", t)
    t = _CODE.sub(r"\1", t)
    t = _GRAS.sub(r"\2", t)
    for motif in (_BARRE, _ITALIQUE_ETOILE, _ITALIQUE_SOULIGNE):
        t = motif.sub(r"\1", t)
    return re.sub(r"\s+", " ", t).strip()


def texte_lisible(texte):
    """Réponse rédigée en texte simple, ligne par ligne, pour les fichiers à lire (tableau, rapport de revue) : titres et
    paragraphes gardés, puces « • », tableaux « cellule · cellule », emphase, liens et code réduits à leur texte. Le
    Markdown brut reste dans les fichiers qui se réimportent (base de données, valeur du fichier à remplir)."""
    sortie = []
    for l in normaliser(texte).split("\n"):
        if _CLOTURE.match(l) or _TRAIT.match(l) or _SEPARATEUR_TABLEAU.match(l) and "-" in l:
            continue
        puce = _PUCE.match(l)
        if _LIGNE_TABLEAU.match(l):
            l = " · ".join(c for c in _cellules(l) if c)
        else:
            l = _MARQUES_BLOC.sub("", l)
        l = _IMAGE.sub(lambda m: m.group(1) or m.group(2), l)
        l = _LIEN.sub(r"\1", l)
        l = _CODE.sub(r"\1", l)
        l = _GRAS.sub(r"\2", l)
        for motif in (_BARRE, _ITALIQUE_ETOILE, _ITALIQUE_SOULIGNE):
            l = motif.sub(r"\1", l)
        l = l.strip()
        if puce and l:
            l = "• " + l
        if l or (sortie and sortie[-1]):
            sortie.append(l)
    return "\n".join(sortie).strip()


def extrait(texte, longueur=EXTRAIT):
    """Début d'une réponse rédigée en texte brut (listes : Saisie, Pour moi, historique), coupé à un mot avec « … »."""
    t = texte_brut(texte)
    if len(t) <= longueur:
        return t
    coupe = t[:longueur]
    espace = coupe.rfind(" ")
    if espace > longueur * 0.6:
        coupe = coupe[:espace]
    return coupe.rstrip(" ,;:.·-") + "…"
