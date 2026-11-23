"""Aide à la traduction de l'interface et à sa relecture : contrôle d'une langue, extraction de l'anglais par lots numérotés,
reprise des lots traduits. Sans réglages Django, sans base : il lit seulement ``libelles/``.

    python3 -I qa/translation_check.py check de [--zone cadre] [--ratio 1.8] [--minimum 30] [--tout]
    python3 -I qa/translation_check.py extract admin [--debut 0 --nombre 300]          # anglais numéroté, à traduire
    python3 -I qa/translation_check.py apply de admin lot.txt --travail /dossier       # reprend un lot traduit

``check`` liste, pour une langue : les fichiers et les clés manquants ou en trop, les paramètres ``{nom}``, les balises ou la
forme (texte / pluriel) différents de l'anglais, les textes vides (ce sont des erreurs : code de sortie 1), puis les textes
identiques à l'anglais (suspects : mot oublié en anglais, ou mot qui s'écrit pareil) et les textes beaucoup plus longs que
l'anglais (boutons et en-têtes qui risquent de déborder), qui sont à relire (avertissements). La relecture par retraduction
se fait avec ``extract`` sur la langue traduite : voir docs/translation_glossary.md, « How to translate a language ».

Format d'un lot, une ligne par texte : ``N|texte`` (N : numéro donné par ``extract`` ; un pluriel s'écrit
``un seul ¦¦ plusieurs`` ; un retour à la ligne s'écrit ``\\n``). ``apply`` vérifie chaque ligne (paramètres et balises
identiques à l'anglais), range le résultat dans ``--travail`` (brouillon de la zone) et écrit ``libelles/<zone>.<langue>.json``
dès que toutes les clés de la zone sont traduites (jamais un fichier de zone incomplet dans ``libelles/``).
"""
import argparse
import json
import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from parametres import controle_libelles as C  # noqa: E402
from parametres import zones_langue as Z  # noqa: E402

SEP_PLURIEL = " ¦¦ "
IDENTIQUES_PERMIS = {"KPI", "N/A", "GHG", "ID", "PDF", "JPG", "PNG", "CSV", "XLSX", "Excel", "SMTP", "HTTPS", "URL", "API", "MCP",
                     "SPOC", "Probant", "Docker", "JSON", "Markdown", "Word", "Power BI"}


def vers_ligne(texte):
    """Texte (ou pluriel) sur une ligne : retour à la ligne écrit « \\n », pluriel séparé par « ¦¦ »."""
    return SEP_PLURIEL.join(t.replace("\n", "\\n") for t in C.textes(texte))


def depuis_ligne(ligne, modele):
    """Valeur (texte ou pluriel) d'une ligne traduite, de la même forme que ``modele`` (texte de l'anglais)."""
    morceaux = ligne.split("¦¦")
    morceaux = [m.replace("\\n", "\n") for m in morceaux]
    if isinstance(modele, dict):
        if len(morceaux) != 2:
            raise ValueError("un pluriel s'écrit « un seul ¦¦ plusieurs »")
        return {"one": morceaux[0].strip(), "other": morceaux[1].strip()}
    if len(morceaux) != 1:
        raise ValueError("« ¦¦ » est réservé aux pluriels")
    return morceaux[0]


def ecrire(zone, langue, donnees):
    p = C.chemin(zone, langue)
    p.write_text(json.dumps(donnees, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def mots(texte):
    return re.findall(r"[^\W\d_]{2,}", re.sub(r"\{\w+\}|<[^>]+>", " ", texte))


def suspect_identique(en, autre):
    """Texte identique à l'anglais, avec de vraies lettres, qui n'est pas un sigle ou un nom permis."""
    if en != autre or len(en) < 4:
        return False
    m = mots(en)
    return bool(m) and not all(x in IDENTIQUES_PERMIS or x.isupper() for x in m)


def check(args):
    langue = args.langue
    erreurs = C.problemes(langue)
    if args.zone:
        erreurs = [e for e in erreurs if e[1] == args.zone]
    print(f"== {langue} : {len(erreurs)} erreur(s) de structure (clés, paramètres, balises, formes, textes vides)")
    for type_, zone, cle, detail in erreurs[: args.limite if not args.tout else None]:
        print(f"  [{type_}] {zone} {cle} {detail}".rstrip())
    if len(erreurs) > args.limite and not args.tout:
        print(f"  … {len(erreurs) - args.limite} de plus (--tout)")
    identiques, longs = [], []
    for zone in Z.ZONES:
        if args.zone and zone != args.zone:
            continue
        en, autre = C.lire(zone, C.BASE) or {}, C.lire(zone, langue) or {}
        for cle in sorted(set(en) & set(autre)):
            for te, ta in zip(C.textes(en[cle]), C.textes(autre[cle])):
                if langue != C.BASE and suspect_identique(te, ta):
                    identiques.append((zone, cle, te))
                if len(ta) >= args.minimum and len(ta) > args.ratio * max(len(te), 1):
                    longs.append((zone, cle, len(te), len(ta), ta))
    print(f"\n== textes identiques à l'anglais (suspects) : {len(identiques)}")
    for zone, cle, te in identiques[: args.limite if not args.tout else None]:
        print(f"  {cle} : {te[:80]}")
    print(f"\n== textes plus de {args.ratio} fois plus longs que l'anglais (au moins {args.minimum} signes) : {len(longs)}")
    for zone, cle, le, la, ta in sorted(longs, key=lambda x: -x[3] / max(x[2], 1))[: args.limite if not args.tout else None]:
        print(f"  {cle} ({le} → {la}) : {ta[:80]}")
    return 1 if erreurs else 0


def extract(args):
    base = C.lire(args.zone, C.BASE)
    if base is None:
        print(f"zone inconnue : {args.zone}", file=sys.stderr)
        return 2
    cles = list(base)
    fin = len(cles) if args.nombre is None else args.debut + args.nombre
    aide = C.lire(args.zone, args.aide) if args.aide else None
    for n in range(args.debut, min(fin, len(cles))):
        print(f"{n}|{vers_ligne(base[cles[n]])}")
        if aide and cles[n] in aide:
            print(f"   ({args.aide}) {vers_ligne(aide[cles[n]])}")
    print(f"# {args.zone} : {len(cles)} textes, de {args.debut} à {min(fin, len(cles)) - 1}", file=sys.stderr)
    return 0


def apply(args):
    base = C.lire(args.zone, C.BASE)
    cles = list(base)
    brouillon_p = Path(args.travail) / f"{args.zone}.{args.langue}.brouillon.json"
    brouillon = json.loads(brouillon_p.read_text(encoding="utf-8")) if brouillon_p.exists() else {}
    erreurs = 0
    for numero, ligne in enumerate(Path(args.lot).read_text(encoding="utf-8").split("\n"), start=1):
        if not ligne.strip() or ligne.startswith(("#", "   (")):
            continue
        n, _, texte = ligne.partition("|")
        if not n.strip().isdigit() or int(n) >= len(cles):
            print(f"ligne {numero} : numéro illisible", file=sys.stderr)
            erreurs += 1
            continue
        cle = cles[int(n)]
        try:
            valeur = depuis_ligne(texte, base[cle])
        except ValueError as e:
            print(f"ligne {numero} ({cle}) : {e}", file=sys.stderr)
            erreurs += 1
            continue
        if not all(C.textes(valeur)):
            print(f"ligne {numero} ({cle}) : texte vide", file=sys.stderr)
            erreurs += 1
        elif C.parametres(valeur) != C.parametres(base[cle]):
            print(f"ligne {numero} ({cle}) : paramètres {sorted(C.parametres(base[cle]))} attendus, {sorted(C.parametres(valeur))} trouvés", file=sys.stderr)
            erreurs += 1
        elif C.balises(valeur) != C.balises(base[cle]):
            print(f"ligne {numero} ({cle}) : balises {C.balises(base[cle])} attendues, {C.balises(valeur)} trouvées", file=sys.stderr)
            erreurs += 1
        else:
            brouillon[cle] = valeur
    Path(args.travail).mkdir(parents=True, exist_ok=True)
    brouillon_p.write_text(json.dumps(brouillon, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    manque = [c for c in cles if c not in brouillon]
    print(f"{args.zone} ({args.langue}) : {len(brouillon)}/{len(cles)} textes ; {erreurs} ligne(s) refusée(s)")
    if not manque and not erreurs:
        ecrire(args.zone, args.langue, {c: brouillon[c] for c in cles})
        print(f"écrit : libelles/{args.zone}.{args.langue}.json")
    elif manque:
        n0 = cles.index(manque[0])
        print(f"reste {len(manque)} texte(s) ; premier manquant : {n0}")
    return 1 if erreurs else 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sous = p.add_subparsers(dest="commande", required=True)
    c = sous.add_parser("check", help="contrôler une langue")
    c.add_argument("langue")
    c.add_argument("--zone", choices=list(Z.ZONES))
    c.add_argument("--ratio", type=float, default=1.8, help="seuil de longueur par rapport à l'anglais (1,8)")
    c.add_argument("--minimum", type=int, default=30, help="longueur minimale d'un texte jugé trop long (30 signes)")
    c.add_argument("--limite", type=int, default=40, help="lignes affichées par liste (40)")
    c.add_argument("--tout", action="store_true", help="afficher toutes les lignes")
    c.set_defaults(fonction=check)
    e = sous.add_parser("extract", help="afficher l'anglais d'une zone, numéroté")
    e.add_argument("zone", choices=list(Z.ZONES))
    e.add_argument("--debut", type=int, default=0)
    e.add_argument("--nombre", type=int)
    e.add_argument("--aide", help="langue de secours affichée sous chaque ligne (fr : lever une ambiguïté)")
    e.set_defaults(fonction=extract)
    a = sous.add_parser("apply", help="reprendre un lot traduit")
    a.add_argument("langue")
    a.add_argument("zone", choices=list(Z.ZONES))
    a.add_argument("lot")
    a.add_argument("--travail", required=True, help="dossier des brouillons (hors du dépôt)")
    a.set_defaults(fonction=apply)
    args = p.parse_args(argv)
    return args.fonction(args)


if __name__ == "__main__":
    sys.exit(main())
