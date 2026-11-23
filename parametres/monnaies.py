"""Monnaie de référence d'un espace (Paramètres › Unités et formats).

Les modèles de la bibliothèque écrivent leurs montants en euros (unités « € », « M€ », « €/h »…). Un espace dont les états
financiers sont établis dans une autre monnaie choisit ici sa monnaie de référence : à l'installation ou à la mise à jour
d'un modèle, ces unités deviennent les mêmes dans cette monnaie (« $ », « M$ », « $/h ») pour les KPI nouveaux ; un KPI déjà
dans l'installation garde son unité, qu'il ait des valeurs ou non (``collecte/paquets/analyse_kpis.py``). Aucune valeur n'est convertie, aucun taux de change : hors
périmètre. Changer la monnaie après coup ne change aucun KPI existant.

Liste fermée de monnaies courantes (code ISO 4217 et symbole écrit dans les unités) : pas de texte libre. Un symbole
d'une seule lettre n'est pris que pour l'euro, le dollar américain et la livre sterling ; les autres monnaies s'écrivent
avec leur code (« CHF », « kSEK », « MCHF »), sans ambiguïté (le « ¥ » est à la fois le yen et le yuan, le « $ » de
plusieurs pays). Module sans base de données, sauf ``reference()`` et les noms affichés (fichiers de langue)."""
from parametres.rapprochement_unites import symbole_normalise

MONNAIES = (  # code ISO 4217, symbole écrit dans les unités ; l'ordre est celui de la liste à l'écran
    ("EUR", "€"), ("USD", "$"), ("GBP", "£"), ("CHF", "CHF"), ("SEK", "SEK"), ("NOK", "NOK"), ("DKK", "DKK"),
    ("PLN", "PLN"), ("CZK", "CZK"), ("HUF", "HUF"), ("RON", "RON"), ("CAD", "CAD"), ("AUD", "AUD"), ("JPY", "JPY"),
    ("CNY", "CNY"),
)
PAR_DEFAUT = "EUR"
SYMBOLE_MODELES = "€"  # monnaie dans laquelle les modèles de la bibliothèque sont écrits
SYMBOLES = dict(MONNAIES)
CODES = tuple(SYMBOLES)

# Unités en euros des modèles de la bibliothèque et nom de leur libellé dans une autre monnaie
# (clé ``admin.monnaies.unite.<forme>`` des fichiers de langue) ; une autre unité en euros garde son symbole pour libellé.
FORMES = {"€": "base", "k€": "milliers", "M€": "millions", "Md€": "milliards", "€/h": "par_heure"}
# préfixes et suffixes d'un symbole d'unité monétaire : « k€ », « M$ », « €/h », « CHF/salarié »
PREFIXES = ("", "k", "M", "Md", "Mrd", "bn")


def valide(code):
    return code in SYMBOLES


def symbole(code):
    return SYMBOLES.get(code, SYMBOLES[PAR_DEFAUT])


def nom(code, langue=None):
    """Nom de la monnaie dans la langue demandée (« US dollar », « dollar américain »)."""
    from .libelles import libelle

    return libelle(f"admin.monnaies.nom.{code.lower()}", langue)


def affichee(code, langue=None):
    """« US dollar ($, USD) », « Swiss franc (CHF) » : nom, puis symbole et code quand ils diffèrent."""
    s = symbole(code)
    return f"{nom(code, langue)} ({s}, {code})" if s != code else f"{nom(code, langue)} ({code})"


def choix(langue=None):
    """[(code, texte affiché)] de la liste de l'écran, dans l'ordre de ``MONNAIES``."""
    return [(c, affichee(c, langue)) for c in CODES]


def depuis_texte(texte):
    """Code ISO d'une monnaie écrite par son code (« usd », « USD ») ou son symbole (« $ ») ; ``None`` si elle n'est pas
    dans la liste (fichier de configuration)."""
    t = symbole_normalise(str(texte or ""))
    if t.upper() in SYMBOLES:
        return t.upper()
    return next((c for c, s in MONNAIES if s == t), None)


def reference():
    """Monnaie de référence de l'espace courant (code ISO), « EUR » si le réglage manque ou n'est plus dans la liste."""
    from .models import Instance

    code = Instance.courante().monnaie
    return code if valide(code) else PAR_DEFAUT


def forme(texte):
    """(code ISO, forme en euros) d'une unité monétaire : « M$ » → ("USD", "M€"), « CHF/h » → ("CHF", "€/h »),
    « MEUR » → ("EUR", "M€") (la monnaie s'écrit par son symbole ou son code ISO, après un préfixe k, M, Md… et avant
    « /… ») ; (None, symbole normalisé) pour une autre unité (« kg », « tCO2e/M€ » : la monnaie n'y est pas la grandeur
    mesurée, l'unité n'est pas un montant)."""
    t = symbole_normalise(texte)
    for code, s in MONNAIES:
        for notation in dict.fromkeys((s, code)):
            for p in PREFIXES:
                debut = p + notation
                if t == debut or (t.startswith(debut + "/") and len(t) > len(debut) + 1):
                    return code, p + SYMBOLE_MODELES + t[len(debut):]
    return None, t


def monnaie_du_symbole(texte):
    """Code ISO de la monnaie d'une unité monétaire (« M$ » → USD, « €/h » → EUR, « kCHF » → CHF), sinon ``None``."""
    return forme(texte)[0]


def en_monnaie(texte, code):
    """Symbole (ou code) d'une unité en euros des modèles, écrit dans la monnaie ``code`` (« M€ » → « M$ »)."""
    return (texte or "").replace(SYMBOLE_MODELES, symbole(code))


def variante(voulue, reelle):
    """Vrai si le symbole ``reelle`` est l'unité en euros ``voulue`` d'un modèle écrite dans une autre monnaie de la liste
    (« $/h » pour « €/h ») : l'unité d'un modèle installé avec une autre monnaie de référence n'est pas une erreur."""
    cv, fv = forme(voulue)
    cr, fr = forme(reelle)
    return cv == PAR_DEFAUT and cr not in (None, PAR_DEFAUT) and fv == fr


def autre_monnaie_seule(a, b):
    """Vrai si les symboles ``a`` et ``b`` sont la même unité monétaire dans deux monnaies différentes (« M€ » et « M$ »,
    « €/h » et « CHF/h ») : seule la monnaie change."""
    (ca, fa), (cb, fb) = forme(a), forme(b)
    return bool(ca and cb and ca != cb and fa == fb)


def dans_la_monnaie(symbole_unite, unite_modele, code):
    """Vrai si l'unité ``symbole_unite`` d'un KPI est l'unité en euros ``unite_modele`` du modèle écrite dans la monnaie
    ``code`` (« M$ » pour « M€ » en dollars ; « MUSD » aussi) : un montant qui peut aller tel quel dans un rapport tenu
    dans cette monnaie."""
    return forme(symbole_unite) == (code, forme(unite_modele)[1])


def libelle_unite(code_modele, code, langue, defaut=""):
    """Libellé, dans ``langue``, de l'unité en euros ``code_modele`` d'un modèle écrite dans la monnaie ``code`` : « US
    dollar », « million USD », « USD per hour » ; ``defaut`` pour une autre unité en euros."""
    from .libelles import libelle

    forme = FORMES.get(code_modele)
    if forme is None:
        return defaut
    return libelle(f"admin.monnaies.unite.{forme}", langue, nom=nom(code, langue), code=code)


def adapter_paquet(p, code):
    """Paquet d'un modèle de la bibliothèque (``collecte.paquets.Paquet``) dont les unités en euros (« € », « M€ »,
    « €/h ») sont écrites dans la monnaie ``code`` : code, symbole et libellé des unités, unité des KPI et des colonnes
    de tableau. Rien ne change pour l'euro. Le paquet est modifié en place et renvoyé ; ``p.monnaie`` dit la monnaie, et
    ``p.unites_monnaie`` {nouveau code : code d'origine} les unités réécrites."""
    p.monnaie = code if valide(code) else PAR_DEFAUT
    p.unites_monnaie = {}
    if p.monnaie == PAR_DEFAUT:
        return p
    renommees = {}
    for u in p.unites:
        origine = str(u.get("code") or "")
        if SYMBOLE_MODELES not in origine:
            continue
        nouveau = en_monnaie(origine, p.monnaie)
        renommees[origine] = nouveau
        u["code"] = nouveau
        u["symbole"] = {lg: en_monnaie(t, p.monnaie) for lg, t in (u.get("symbole") or {}).items()} or {p.langue_reference: nouveau}
        langues = list(u.get("libelle") or {p.langue_reference: ""})
        if origine in FORMES:  # libellé dans chaque langue de l'interface, comme l'unité en euros du catalogue
            from .libelles import langues_disponibles

            langues += [lg for lg in langues_disponibles() if lg not in langues]
        u["libelle"] = {lg: libelle_unite(origine, p.monnaie, lg, nouveau) for lg in langues}
    for k in p.kpis:
        if k.get("unite") in renommees:
            k["unite"] = renommees[k["unite"]]
    for t in p.types_reponse:  # colonnes de tableau : leur unité éventuelle
        for col in t.get("colonnes") or []:
            if isinstance(col, dict) and col.get("unite") in renommees:
                col["unite"] = renommees[col["unite"]]
    p.unites_monnaie = {n: o for o, n in renommees.items()}
    return p


def a_des_montants(p):
    """Vrai si un KPI du paquet a une unité monétaire (avant ou après ``adapter_paquet``)."""
    monetaires = {u["code"] for u in p.unites if monnaie_du_symbole(u["code"])}
    return any(k.get("unite") in monetaires for k in p.kpis)
