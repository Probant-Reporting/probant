#!/usr/bin/env python3
"""Liste les classes de static/css/outil.css absentes des gabarits, des .py et des .js.

Usage :  python3 qa/css_orphelins.py            (liste lisible, code de sortie 1 s'il reste des orphelins)
         python3 qa/css_orphelins.py --lignes   (avec les numéros de ligne de la feuille de style)

Une classe est « utilisée » si son nom apparaît comme mot entier dans un gabarit (.html), un fichier Python (hors
migrations et tests) ou un fichier JavaScript. Une classe est « dynamique » si son nom commence par un préfixe que le
code complète à l'exécution (`niveau-{{ code }}`, `'statut-' + x`, `f"role-{…}"`…) : elle est gardée, jamais listée
comme orpheline. Le script ne supprime rien : il sert de contrôle avant un ménage, et de test (aucun orphelin).
"""
import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
FEUILLE = RACINE / "static" / "css" / "outil.css"
DOSSIERS_EXCLUS = {".git", "node_modules", "staticfiles", "local-data", "migrations", "qa", ".claude", "__pycache__"}
# Classes posées par une bibliothèque ou par Django (formulaires, messages), hors de nos gabarits.
TOUJOURS_GARDEES = {"errorlist", "nonfield", "success", "error", "warning", "info", "debug"}
# Les sept teintes d'étiquette de DESIGN.md (« Chips ») : vocabulaire offert aux nouvelles pages, même sans emploi.
TOUJOURS_GARDEES |= {"e-neutre", "e-vert", "e-jaune", "e-orange", "e-rouge", "e-bleu", "e-accent"}
# Préfixes complétés à l'exécution que la recherche automatique ne voit pas : classes posées par JavaScript
# (static/js/visualisation.js : `l-${largeur}`, `h-${hauteur}`, `forme-${type}`, `etat-${e}`, `sens-${s}`) et valeurs
# calculées loin de l'attribut class (rôle, type, statut, teinte de fiche « rf- »).
PREFIXES_CONNUS = {"niveau-", "role-", "type-", "statut-", "rf-", "l-", "h-", "forme-", "etat-", "sens-"}

CLASSE = re.compile(r"([.#])(-?[A-Za-z_][\w-]*)")  # classe (.nom) ou identifiant (#nom, gardé avec son dièse)
# préfixe suivi d'une partie calculée, dans un attribut class d'un gabarit : class="… niveau-{{ code }}"
ATTRIBUT_CLASS = re.compile(r'class\s*=\s*"([^"]*)"')
DYNAMIQUE_GABARIT = re.compile(r"([A-Za-z_][\w-]*-)\{[{%]")
# … ou dans du HTML produit par un fichier Python : class="niveau-{code}", class="x-%s"
DYNAMIQUE_PYTHON = re.compile(r"""class=\\?["'][^"']*?([a-z][\w-]*-)(?:\{|%s|["']\s*\+)""")


def classes_de_la_feuille(texte):
    """{classe: première ligne} pour chaque classe citée dans un sélecteur (pas dans une déclaration)."""
    sans_commentaires = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), texte, flags=re.S)
    trouvees = {}
    # un sélecteur est ce qui précède une accolade ouvrante ; on saute le contenu des blocs de déclarations
    for morceau in re.finditer(r"([^{}]*)\{([^{}]*)(\}|(?=\{))|([^{}]*)\}", sans_commentaires):
        selecteur = morceau.group(1) or ""
        depart = sans_commentaires.count("\n", 0, morceau.start()) + 1
        if selecteur.strip().startswith("@") and not selecteur.strip().startswith(("@media", "@supports")):
            continue
        for m in CLASSE.finditer(selecteur):
            # « .5s » ou « 0.5 » ne sont pas des classes (le motif exige une lettre, donc rien à filtrer ici)
            nom = m.group(2) if m.group(1) == "." else "#" + m.group(2)
            trouvees.setdefault(nom, depart + selecteur.count("\n", 0, m.start()))
        # bloc @media : le « contenu » capturé est en fait le premier sélecteur intérieur
        if selecteur.strip().startswith(("@media", "@supports")):
            interieur = morceau.group(2) or ""
            for m in CLASSE.finditer(interieur):
                trouvees.setdefault(m.group(2) if m.group(1) == "." else "#" + m.group(2), depart)
    return trouvees


def sources():
    for chemin in RACINE.rglob("*"):
        if chemin.suffix not in {".html", ".py", ".js"} or not chemin.is_file():
            continue
        parties = set(chemin.relative_to(RACINE).parts)
        if parties & DOSSIERS_EXCLUS:
            continue
        if chemin.suffix == ".py" and (chemin.name.startswith("test") or chemin.name == "tests.py"):
            continue
        yield chemin


def analyser():
    classes = classes_de_la_feuille(FEUILLE.read_text(encoding="utf-8"))
    mots = set()
    prefixes = set(PREFIXES_CONNUS)
    for chemin in sources():
        texte = chemin.read_text(encoding="utf-8", errors="ignore")
        mots.update(re.findall(r"-?[A-Za-z_][\w-]*", texte))
        if chemin.suffix == ".html":
            for attribut in ATTRIBUT_CLASS.finditer(texte):
                prefixes.update(m.group(1) for m in DYNAMIQUE_GABARIT.finditer(attribut.group(1)))
        elif chemin.suffix == ".py":
            prefixes.update(m.group(1) for m in DYNAMIQUE_PYTHON.finditer(texte))
    orphelines, dynamiques = {}, {}
    for nom, ligne in classes.items():
        if nom.lstrip("#") in mots or nom in TOUJOURS_GARDEES:
            continue
        # un mot « a-b-c » du code contient aussi « a-b » : on ne garde que les mots entiers, donc rien à faire ici
        prefixe = next((p for p in sorted(prefixes, key=len, reverse=True) if nom.lstrip("#").startswith(p)), None)
        if prefixe:
            dynamiques[nom] = (ligne, prefixe)
        else:
            orphelines[nom] = ligne
    return classes, orphelines, dynamiques


def main(argv):
    avec_lignes = "--lignes" in argv
    classes, orphelines, dynamiques = analyser()
    print(f"{len(classes)} classes dans {FEUILLE.relative_to(RACINE)} "
          f"({FEUILLE.stat().st_size} octets, {len(FEUILLE.read_text(encoding='utf-8').splitlines())} lignes)")
    print(f"{len(dynamiques)} classes gardées car construites à l'exécution (préfixe)")
    if "--dynamiques" in argv:
        for nom, (ligne, prefixe) in sorted(dynamiques.items()):
            print(f"  {nom}  (préfixe {prefixe}, ligne {ligne})")
    print(f"{len(orphelines)} classes absentes des gabarits, des .py et des .js :")
    for nom, ligne in sorted(orphelines.items(), key=lambda c: c[1]):
        print(f"  {nom}" + (f"  (ligne {ligne})" if avec_lignes else ""))
    return 1 if orphelines else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
