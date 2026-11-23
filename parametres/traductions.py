"""Traductions des contenus : ce qui reste à traduire dans une langue, complétude, enregistrement depuis la page
« Traductions » (Paramètres › Langues).

Un texte est « à traduire » dans une langue s'il existe dans une autre langue (en général la référence) et pas dans
celle-ci. Les valeurs des listes se traduisent une à une ; la réponse enregistrée garde sa valeur de référence.
"""
from dataclasses import dataclass

from . import langues as L
from .libelles import libelle

SECTIONS = [("kpi", "admin.traductions.section.kpi"), ("descriptions", "admin.traductions.section.descriptions"),
            ("themes", "admin.traductions.section.themes"), ("libelles", "admin.traductions.section.libelles")]  # (code, clé du titre)


def titres_sections():
    """[(code, titre)] des sections, dans la langue de la personne."""
    return [(code, libelle(cle)) for code, cle in SECTIONS]


@dataclass
class Element:
    cle: str  # nom du champ de formulaire : « kpi|CODE », « desc|categorie|CODE », « theme|texte », « obj|section|champ|code »…
    quoi: str  # ce qu'on traduit, ex. « ENE-01 · Nom »
    source: str  # texte de référence (ou d'une autre langue si absent)
    actuel: str  # traduction actuelle (vide : à traduire)
    long: bool = False  # zone de texte sur plusieurs lignes
    facultatif: bool = False  # traduction facultative (symbole d'unité) : pas comptée comme manquante


def _kpis():
    from referentiel.models import KPI

    return list(KPI.objects.prefetch_related("descriptions").order_by("ordre", "code"))


def _source(textes, langue):
    """Texte de départ pour traduire : la référence, sinon la langue par défaut, sinon une autre."""
    for l in (L.reference(), L.defaut(), *textes):
        if l != langue and textes.get(l):
            return textes[l]
    return ""


def elements(langue, section, tout=False):
    """Éléments d'une section à traduire dans ``langue`` (tous ceux qui ont un texte si ``tout``)."""
    from parametres.models import CategorieDescription

    sortie = []
    if section == "kpi":
        for k in _kpis():
            source, actuel = L.traduire(k, "libelle", L.reference()), L.texte(k, "libelle", langue)
            if source and (tout or not actuel):
                sortie.append(Element(f"kpi|{k.code}", f"{k.code}", source, actuel))
    elif section == "descriptions":
        categories = {c.code: c for c in CategorieDescription.objects.all()}
        for k in _kpis():
            par_cat = {}
            for d in k.descriptions.all():
                par_cat.setdefault(d.categorie_id, {})[d.langue] = d.texte
            for cat, c in categories.items():
                textes = par_cat.get(cat, {})
                source, actuel = _source(textes, langue), textes.get(langue, "")
                if source and (tout or not actuel):
                    sortie.append(Element(f"desc|{cat}|{k.code}", f"{k.code} · {c.tr('libelle')}", source, actuel, long=True))
    elif section == "themes":
        from referentiel.models import Theme

        themes = {t.id: t for t in Theme.objects.select_related("referentiel")}
        for t in sorted(themes.values(), key=lambda t: (t.referentiel.ordre, t.referentiel_id, _chemin(themes, t))):
            source, actuel = L.traduire(t, "nom", L.reference()), L.texte(t, "nom", langue)
            if source and (tout or not actuel):
                parents = " › ".join(x.nom for x in _chemin_objets(themes, t)[:-1])
                sortie.append(Element(f"theme|{t.id}", f"{t.referentiel} · {parents + ' › ' if parents else ''}{t.code}", source, actuel))
    elif section == "libelles":
        for cle, titre, modele in L.modeles():
            for o in modele.objects.all():
                for champ, nom_champ in o.TRADUITS:
                    source, actuel = L.traduire(o, champ, L.reference()), L.texte(o, champ, langue)
                    facultatif = champ in getattr(o, "FACULTATIFS", ())
                    if source and (tout or not (actuel or facultatif)):
                        sortie.append(Element(f"obj|{cle}|{champ}|{o.pk}", f"{titre} · {o.pk} · {nom_champ}", source, actuel,
                                              facultatif=facultatif))
                cles = L.cles_valeurs(o)
                if cles and langue != L.reference():
                    traduites = L.valeurs_langue(o, langue)
                    for i, v in enumerate(cles):
                        actuel = traduites[i] if i < len(traduites) else ""
                        if tout or not actuel:
                            sortie.append(Element(f"val|{cle}|{i}|{o.pk}", f"{titre} · {o.pk} · " + libelle("admin.traductions.valeur_n", n=i + 1), v, actuel))
    return sortie


def kpi_element(element):
    """Code du KPI dont l'élément est le nom ou une description (sections « kpi » et « descriptions »), sinon None."""
    genre, _, reste = element.cle.partition("|")
    if genre == "kpi":
        return reste
    if genre == "desc":
        return reste.partition("|")[2]
    return None


def _chemin_objets(themes, t):
    chemin = []
    while t is not None:
        chemin.insert(0, t)
        t = themes.get(t.parent_id)
    return chemin


def _chemin(themes, t):
    return [(x.ordre, x.id) for x in _chemin_objets(themes, t)]


def completude(langue):
    """{section: (traduits, à traduire en tout)} et le total, pour une langue."""
    if langue == L.reference():
        return {}, (1, 1)
    sortie = {}
    for section, _ in SECTIONS:
        tous = [e for e in elements(langue, section, tout=True) if e.actuel or not e.facultatif]
        sortie[section] = (sum(1 for e in tous if e.actuel), len(tous))
    faits, total = sum(f for f, _ in sortie.values()), sum(t for _, t in sortie.values())
    return sortie, (faits, total)


def kpi_a_traduire(k, langues, categories):
    """Langues (codes) dans lesquelles le nom ou une définition du KPI manque."""
    textes = {}
    for d in k.descriptions.all():
        textes.setdefault(d.categorie_id, set()).add(d.langue)
    manque = []
    for l in langues:
        if L.a_traduire(k, "libelle", l) or any(textes.get(c) and l not in textes[c] for c in categories):
            manque.append(l)
    return manque


def enregistrer(langue, donnees):
    """Enregistre les traductions postées ({clé: texte}). Renvoie le nombre de textes modifiés."""
    from referentiel.echange import enregistrer_descriptions
    from referentiel.models import KPI, Theme

    modeles = {cle: modele for cle, _, modele in L.modeles()}
    n, objets, valeurs = 0, {}, {}
    for cle, texte in donnees.items():
        texte = (texte or "").strip()
        morceaux = cle.split("|")
        genre = morceaux[0]
        if genre == "kpi":
            k = objets.setdefault(("kpi", cle[4:]), KPI.objects.filter(pk=cle[4:]).first())
            if k is not None and L.texte(k, "libelle", langue) != texte:
                L.definir(k, "libelle", langue, texte)
                n += 1
        elif genre == "desc" and len(morceaux) >= 3:
            _, cat, code = cle.split("|", 2)
            k = KPI.objects.filter(pk=code).first()
            if k is not None and k.texte_description(cat, langue, repli=False) != texte:
                enregistrer_descriptions(k, {cat: texte}, langue)
                n += 1
        elif genre == "theme" and cle[6:].isdecimal():
            t = objets.setdefault(("themes", cle[6:]), Theme.objects.filter(pk=cle[6:]).first())
            if t is not None and L.texte(t, "nom", langue) != texte:
                L.definir(t, "nom", langue, texte)
                n += 1
        elif genre == "obj" and len(morceaux) >= 4:
            _, section, champ, code = cle.split("|", 3)
            modele = modeles.get(section)
            o = objets.setdefault((section, code), modele.objects.filter(pk=code).first() if modele else None)
            if o is not None and champ in dict(o.TRADUITS) and L.texte(o, champ, langue) != texte:
                L.definir(o, champ, langue, texte)
                n += 1
        elif genre == "val" and len(morceaux) >= 4:
            _, section, i, code = cle.split("|", 3)
            modele = modeles.get(section)
            o = objets.setdefault((section, code), modele.objects.filter(pk=code).first() if modele else None)
            if o is not None and i.isdecimal():
                valeurs.setdefault((section, code), {})[int(i)] = texte
    for (section, code), textes in valeurs.items():
        o = objets[(section, code)]
        cles = L.cles_valeurs(o)
        actuelles = L.valeurs_langue(o, langue) + [""] * len(cles)
        nouvelles = [textes.get(i, actuelles[i]) for i in range(len(cles))]
        if nouvelles != actuelles[:len(cles)]:
            n += sum(1 for i in range(len(cles)) if nouvelles[i] != actuelles[i])
            L.definir_valeurs(o, langue, nouvelles, len(cles))
    for o in objets.values():
        if o is not None:
            o.save(update_fields=["traductions"])  # jamais la langue de référence ici : elle se règle dans les fiches
    return n
