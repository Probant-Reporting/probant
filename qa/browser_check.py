"""Recette dans un navigateur, par rôle : pages principales (statut, erreurs JavaScript, temps de réponse, poids),
accessibilité (axe-core, règles WCAG 2.1 et 2.2 A et AA), affichage tablette (768 px) et téléphone (390 px) sans
défilement horizontal, clavier (tabulation, focus visible, ouverture d'une case au clavier), contrôles nommés des
problèmes de la et parcours de saisie.

    qa/disposable_demo.sh --port 8013                        # démo jetable (affiche la base à passer à --base)
    python3 -I qa/browser_check.py --url http://127.0.0.1:8013 --axe /chemin/axe.min.js --sortie /dossier [--dark] \
        --base /chemin/demo.sqlite3 [--base-jetable] [--smtp] [--mot-de-passe demo-probant-2026] \
        [--admin admin --validateur validateur --contributeur contributeur] [--roles admin,lecteur] [--resume]

Parcours long (plus de 900 s sous charge) : --roles limite la recette à certains rôles ; la recette écrit resultats.json
après les contrôles nommés et après chaque rôle (« termine »: false tant qu'elle n'est pas finie), affiche l'avancement
([page n/N], temps écoulé) et --resume reprend un passage arrêté : les contrôles nommés et les rôles déjà faits dans
resultats.json du dossier --sortie ne sont pas refaits (ni leur verdict : il est relu du fichier).

Prévu pour une démo jetable (qa/disposable_demo.sh : charger_demo, démo Exemplia, servie par gunicorn en
mode production). Écrit resultats.json et des captures 1 440 px (bureau_*), 768 px (tab_*) et 390 px (tel_*) dans
--sortie. Code de sortie 1 si une page échoue (statut, erreur JavaScript), si axe trouve une violation « serious » ou
« critical » hors AXE_TOLERES, si une page défile horizontalement à 768 ou 390 px (hors DEBORDEMENTS_TOLERES), si le
parcours de saisie n'aboutit pas, si un contrôle de CONTROLES_BLOQUANTS est rouge ou sauté (sauf quand ce compte n'a
vraiment rien à saisir : il est alors rangé dans « non vérifié »), ou si des tables métier ont changé sans --base-jetable.

Par défaut, la recette n'écrit rien dans les tables métier (valeurs, alertes, relances, journal) : elle ne fait pas le
parcours de saisie et n'ouvre pas la page Cohérence (son ouverture relance le contrôle, qui réécrit les alertes). Ces
deux points sont « sautés » (pas « en échec »), rangés dans resultats.json et rappelés à la fin (« non vérifié dans ce
passage »). Avec --base-jetable (démo jetable seulement), ils sont faits : une recette complète demande donc deux
passages, un par défaut puis un avec --base-jetable. La connexion écrit seulement la session et la date de dernière
connexion ; le choix de la campagne et de l'organisation est gardé dans la session.

Preuve : avec --base (fichier SQLite de la démo, lu en lecture seule), chaque table métier est relue avant et après :
nombre de lignes et empreinte du contenu (SHA-256 de toutes les lignes). Une ligne modifiée est donc vue, pas seulement
une ligne ajoutée ou supprimée ; tout écart sans --base-jetable met la recette en échec. Sans --base, la preuve n'est
pas faite et la recette le dit.
"""
import argparse
import glob
import hashlib
import json
import os
import re
import sqlite3
import sys
import time

from playwright.sync_api import sync_playwright

PAGES = {
    "admin": [
        ("Accueil", "/"), ("Saisie", "/saisie/"), ("Pour moi", "/pour-moi/"), ("Tableau de bord", "/tableau-de-bord/"), ("Consolidation", "/tableau-de-bord/consolidation/"),
        ("Relances", "/tableau-de-bord/relances/"), ("Cohérence", "/coherence/"), ("Import / Export", "/import-export/"),
        ("Listes de KPI", "/import-export/listes-kpi/"), ("Créer une liste de KPI", "/import-export/listes-kpi/?nouvelle=1"),
        ("Visualisation", "/visualisation/"), ("Visualisation d'un thème", "@visu-theme"), ("Visualisation d'un KPI", "@visu-kpi"),
        ("Visualisation en modification", "/visualisation/?modifier=1"),
        ("Catalogue des KPI", "/referentiel/"), ("Administration", "/administration/"), ("Campagnes", "/administration/campagnes/"),
        ("Organisations", "/administration/organisations/"), ("Comptes", "/administration/comptes/"),
        ("Attributions", "/administration/attributions/"), ("Journal", "/administration/journal/"),
        ("Paramètres › Identité", "/administration/parametres/"), ("Paramètres › Visualisation", "/administration/parametres/visualisation/"),
        ("Référentiels", "/administration/referentiels/"),
        ("Ajouter un référentiel", "/administration/referentiels/ajouter/"),
        ("Installer › Modèles", "/administration/referentiels/modeles/"),
        ("Installer › KPI à cocher", "/administration/referentiels/modeles/VS_BASE/"), ("Référentiel › Contenu", "/administration/referentiels/@ref/?ajouter=1"),
        ("Référentiel › Réglages", "/administration/referentiels/@ref/reglages/"),
        ("Référentiel › Versions et partage", "/administration/referentiels/@ref/partage/"),
        ("Unités et formats", "/administration/parametres/referentiel/"),
        ("Paramètres › Hébergement", "/administration/parametres/hebergement/"),
        ("Fichiers de configuration", "/administration/fichiers/"), ("Reprise d'un ancien système", "/administration/fichiers/reprise/"),
        ("Mon compte", "/mon-compte/"),
        # confirmation de restauration (lecture seule en GET) : adresse lue sur Hébergement, sautée sans sauvegarde
        ("Restauration (confirmation)", "@restauration"),
    ],
    "validateur": [
        ("Saisie", "/saisie/"), ("Pour moi", "/pour-moi/"), ("Tableau de bord", "/tableau-de-bord/"), ("Consolidation", "/tableau-de-bord/consolidation/"),
        ("Relances", "/tableau-de-bord/relances/"), ("Cohérence", "/coherence/"), ("Import / Export", "/import-export/"),
        ("Visualisation", "/visualisation/"), ("Visualisation d'un KPI", "@visu-kpi"), ("Mon compte", "/mon-compte/"),
    ],
    "contributeur": [
        ("Saisie", "/saisie/"), ("Pour moi", "/pour-moi/"), ("Tableau de bord", "/tableau-de-bord/"), ("Consolidation", "/tableau-de-bord/consolidation/"), ("Cohérence", "/coherence/"),
        ("Import / Export", "/import-export/"), ("Visualisation", "/visualisation/"),
        ("Visualisation d'un KPI", "@visu-kpi"), ("Mon compte", "/mon-compte/"),
    ],
    "lecteur": [
        ("Visualisation", "/visualisation/"), ("Visualisation d'un KPI", "@visu-kpi"), ("Tableau de bord", "/tableau-de-bord/"), ("Consolidation", "/tableau-de-bord/consolidation/"),
        ("Mon compte", "/mon-compte/"),
    ],
    "auditeur": [
        ("Saisie", "/saisie/"), ("Tableau de bord", "/tableau-de-bord/"), ("Consolidation", "/tableau-de-bord/consolidation/"), ("Cohérence", "/coherence/"), ("Historique", "/historique/"),
        ("Import / Export", "/import-export/"), ("Visualisation", "/visualisation/"), ("Visualisation d'un KPI", "@visu-kpi"),
        ("Mon compte", "/mon-compte/"),
    ],
}
GRAVES = {"serious", "critical"}
AXE_REGLES = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]
AXE_TOLERES = []  # règles axe signalées sans bloquer ; target-size (zones de 24 px) est bloquante depuis l'étape 6
# Pages qui défilent horizontalement, tolérées jusqu'à leur correction : {(largeur, nom de page): raison}. Vide = aucune.
DEBORDEMENTS_TOLERES = {}
ROLES_LECTURE = {"lecteur", "auditeur"}  # comptes en lecture seule : ils n'écrivent rien, même en ouvrant Cohérence
PAGES_QUI_ECRIVENT = {"/coherence/"}  # l'ouverture relance le contrôle de cohérence, qui réécrit les alertes
TABLES_METIER = ["collecte_reponse", "collecte_alerte", "collecte_relance", "collecte_journal"]
TAILLES = {"bureau": {"width": 1440, "height": 900}, "tablette": {"width": 768, "height": 1024},
           "telephone": {"width": 390, "height": 844}}
# Contrôles nommés : un par problème de la. Chacun lit l'écran sans rien enregistrer. Il devient
# bloquant (rouge = recette en échec) quand l'étape qui le corrige est intégrée : ajouter alors son nom à cette liste.
CONTROLES = ["etats_coherents", "panneau_valeur_conservee", "justifier_dans_le_panneau", "relances_sans_smtp",
             "accessibilite_plus", "tdb_personnes", "visualisation"]
# étapes 2 (états fiables), 3 (aucune valeur perdue), 4 (justifier dans le panneau), 5 (relances honnêtes),
# 6 (accessibilité et téléphone) et 7 (retards par organisation, liste « À relancer » sur la page Relances)
CONTROLES_BLOQUANTS = ["etats_coherents", "panneau_valeur_conservee", "justifier_dans_le_panneau", "relances_sans_smtp",
                       "accessibilite_plus", "tdb_personnes", "visualisation"]


def empreinte(base):
    """Nombre de lignes et empreinte du contenu de chaque table métier, lus sans rien écrire (SQLite en lecture seule) ;
    None sans --base."""
    if not base:
        return None
    cnx = sqlite3.connect(f"file:{os.path.abspath(base)}?mode=ro", uri=True)
    try:
        res = {}
        for t in TABLES_METIER:
            h, n = hashlib.sha256(), 0
            for ligne in cnx.execute(f"SELECT * FROM {t} ORDER BY id"):
                h.update(repr(ligne).encode())
                n += 1
            res[t] = {"lignes": n, "empreinte": h.hexdigest()[:16]}
        return res
    finally:
        cnx.close()


def navigateur(p):
    chemins = glob.glob("/opt/pw-browsers/chromium*/chrome-linux*/chrome")
    return p.chromium.launch(executable_path=chemins[0]) if chemins else p.chromium.launch()


def connecter(contexte, url, identifiant, mdp):
    page = contexte.new_page()
    page.goto(url + "/connexion/")
    page.fill("#id_username", identifiant)
    page.fill("#id_password", mdp)
    page.click("button[type=submit]:not([name=langue])")  # pas les boutons FR / EN / ES de la page
    page.wait_for_load_state("networkidle")
    return page


def mesurer(page, url, axe, sortie_axe):
    erreurs = []
    page.on("pageerror", lambda e: erreurs.append(str(e)))
    debut = time.monotonic()
    rep = page.goto(url, wait_until="load")
    total = time.monotonic() - debut
    nav = page.evaluate("""() => { const n = performance.getEntriesByType('navigation')[0];
        return {serveur: n.responseStart - n.requestStart, html: n.encodedBodySize, html_brut: n.decodedBodySize}; }""")
    page.evaluate(axe)  # pas de <script> ajouté : la politique de sécurité des contenus le refuserait (sans jeton)
    res = page.evaluate("""async (regles) => { const r = await axe.run(document, {runOnly: {type: 'tag', values: regles}});
        return r.violations.map(v => ({id: v.id, impact: v.impact, aide: v.help, noeuds: v.nodes.length,
                                       exemples: v.nodes.slice(0, 3).map(n => n.target.join(' '))})); }""", AXE_REGLES)
    sortie_axe.extend(res)
    # balise de gabarit affichée en clair (ex. un commentaire {# … #} écrit sur deux lignes) : la page est en échec
    gabarit = re.findall(r"\{[#%][^\n]{0,60}", page.locator("body").inner_text())
    return {"statut": rep.status, "serveur_ms": round(nav["serveur"]), "total_ms": round(total * 1000), "html_ko": round(nav["html"] / 1024),
            "html_brut_ko": round(nav["html_brut"] / 1024), "erreurs_js": erreurs, "axe": [(v["id"], v["impact"], v["noeuds"]) for v in res],
            "gabarit_visible": gabarit[:3]}


def capture(page, chemin, sortie):
    page.screenshot(path=os.path.join(sortie, chemin), full_page=False)


def debordement(contexte, url, chemin, sortie):
    """Défilement horizontal en px à la largeur du contexte, avec capture. clientWidth (et non innerWidth) : en
    émulation mobile, Chromium élargit la fenêtre de mise en page jusqu'à la largeur du contenu, innerWidth suit."""
    page = contexte.new_page()
    page.goto(url, wait_until="load")
    deborde = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    page.screenshot(path=os.path.join(sortie, chemin), full_page=False)
    page.close()
    return deborde


def clavier(page, url):
    """Tabulation sur la page Saisie : chaque élément atteint a un focus visible ; une case s'ouvre au clavier."""
    page.goto(url + "/saisie/", wait_until="load")
    sans_focus, atteints = [], 0
    for _ in range(40):
        page.keyboard.press("Tab")
        info = page.evaluate("""() => { const e = document.activeElement; if (!e || e === document.body) return null;
            const s = getComputedStyle(e); const visible = (s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0) || s.boxShadow !== 'none';
            return {balise: e.tagName, texte: (e.innerText || e.value || e.getAttribute('aria-label') || '').slice(0, 40), visible}; }""")
        if info:
            atteints += 1
            if not info["visible"]:
                sans_focus.append(f"{info['balise']} « {info['texte']} »")
    # ouvrir une case au clavier
    ligne = page.locator("tr.ligne[data-url]").first
    ouvert = False
    if ligne.count():
        ligne.focus()
        page.keyboard.press("Enter")
        try:
            page.wait_for_selector("body.panneau-ouvert #panneau-contenu [name=valeur]", timeout=4000)
            ouvert = page.evaluate("() => document.activeElement?.name === 'valeur'")  # le curseur est dans la valeur
        except Exception:
            ouvert = False
    return {"elements_atteints": atteints, "sans_focus_visible": sorted(set(sans_focus)), "case_ouverte_au_clavier": ouvert}


def parcours_saisie(page, url):
    """Contributeur : ouvrir une case à saisir, saisir, valider ; la ligne doit passer au statut validé, sans annonce du
    nombre de lignes filtrées (#annonce-filtres reste vide : rien n'est annoncé lors d'un enregistrement).
    Rend {"fait": True, "statut_apres"}, {"fait": False, "saute": motif} (rien à faire ici, ce n'est pas un échec) ou
    {"fait": False, "erreur": motif} (échec)."""
    try:
        page.goto(url + "/pour-moi/", wait_until="load")
        # première case à saisir ou en brouillon (le statut, pas la classe : une case calculée n'a pas ces statuts)
        case = page.locator("tr.ligne[data-url][data-statut=a_saisir], tr.ligne[data-url][data-statut=brouillon]").first
        if not case.count():
            return {"fait": False, "saute": "aucune case à saisir ni brouillon pour ce compte"}
        case.click()
        page.wait_for_selector("#valeur", timeout=6000)
        champ = page.locator("#valeur")
        if champ.is_disabled():
            return {"fait": False, "saute": "saisie fermée (campagne en revue, clôturée ou date de fin passée)"}
        if champ.get_attribute("type") == "radio":
            champ.check()
        elif champ.evaluate("e => e.tagName") == "SELECT":
            champ.select_option(index=1)
        else:
            champ.fill("42")
        commentaire = page.locator("#panneau textarea[name=commentaire]")
        if commentaire.count():
            commentaire.fill("Valeur de recette.")
        cle = case.get_attribute("data-cle")
        page.locator("#panneau button[value=valider]").first.click()
        page.wait_for_timeout(1500)
        statut = page.locator(f'tr.ligne[data-cle="{cle}"]').get_attribute("data-statut")
        # bandeau et liste relus après l'enregistrement : le nombre de lignes filtrées n'est pas annoncé (étape 6)
        annonce = page.evaluate("() => document.getElementById('annonce-filtres')?.textContent || ''")
        if annonce:
            return {"fait": True, "statut_apres": statut, "erreur": f"annonce de filtre après un enregistrement : « {annonce} »"}
        return {"fait": True, "statut_apres": statut}
    except Exception as e:  # délai dépassé, bouton absent… : un échec du parcours, sans perdre les autres mesures
        return {"fait": False, "erreur": str(e)[:300]}


# --- Contrôles nommés --------------------------------------------------------------------------------------------
# Chaque fonction reçoit la page connectée du rôle et l'adresse de la démo, ne fait que des GET et des gestes sans
# enregistrement, et rend une liste de constats (« rouge » | « vert » | « saute », texte). Le contrôle est rouge si un
# constat l'est, vert si au moins un est vert, sinon sauté.

def _reste_pour_moi(page, url):
    """Lignes de Pour moi qui restent à faire : à saisir, brouillon ou avec une alerte de cohérence."""
    page.goto(url + "/pour-moi/", wait_until="load")
    return page.evaluate("""() => { const l = [...document.querySelectorAll('tr.ligne')];
        const vues = new Set(); let valeurs = 0, alertes = 0;
        for (const e of l) { if (vues.has(e)) continue; vues.add(e);
          if (['a_saisir', 'brouillon'].includes(e.dataset.statut)) valeurs++;
          if (e.dataset.alerte === '1') alertes++; }
        return {valeurs, alertes, tout_fait: !!document.querySelector('#resume .tout-fait')}; }""")


def ctl_etats_coherents(role, page, url, o):
    """P1 : « Tout est fait » seulement quand rien ne reste dans le périmètre (valeurs ni alertes) ; « Campagnes en cours » et
    taux en tête sur les mêmes cases (CALC-13)."""
    constats = []
    if role in ("contributeur", "validateur"):
        reste = _reste_pour_moi(page, url)
        page.goto(url + "/saisie/", wait_until="load")
        tout_fait_saisie = page.locator("#resume .tout-fait").count() > 0
        org = page.locator("#choix-org .org-actuelle strong").first
        org = org.inner_text() if org.count() else "?"
        if tout_fait_saisie and (reste["valeurs"] or reste["alertes"]):
            constats.append(("rouge", f"Saisie ({org}) dit « Tout est fait » alors que Pour moi montre {reste['valeurs']} valeur(s) "
                                      f"à saisir ou à valider et {reste['alertes']} alerte(s)"))
        else:
            constats.append(("vert", f"Saisie ({org}) : « Tout est fait » {'affiché' if tout_fait_saisie else 'absent'}, "
                                      f"reste {reste['valeurs']} valeur(s), {reste['alertes']} alerte(s)"))
        if reste["tout_fait"] and reste["alertes"]:
            constats.append(("rouge", f"Pour moi dit « Tout est fait » avec {reste['alertes']} alerte(s) à traiter"))
        elif reste["alertes"]:
            page.goto(url + "/pour-moi/", wait_until="load")
            onglets = page.locator(".onglets-refs").all_inner_texts()
            if onglets and not re.search(r"alerte", " ".join(onglets), re.I):
                constats.append(("rouge", f"onglets de Pour moi sans les {reste['alertes']} alerte(s) : « {' | '.join(onglets)[:160]} »"))
    if role == "admin":
        page.goto(url + "/tableau-de-bord/", wait_until="load")
        entetes = page.evaluate("""() => { const h = [...document.querySelectorAll('h2')].find(x => /Campagnes en cours/.test(x.textContent));
            const t = h && h.closest('.carte')?.querySelector('table'); return t ? [...t.querySelectorAll('th')].map(x => x.textContent.trim()) : null; }""")
        # CALC-13 : « Campagnes en cours » compte les mêmes cases que le taux en tête (KPI
        # facultatifs exclus des deux) : un seul nom, « Taux », sans « (obligatoires) »
        if entetes is None:
            constats.append(("saute", "tableau de bord sans « Campagnes en cours » (une seule campagne ouverte)"))
        elif any("obligatoires" in e for e in entetes):
            constats.append(("rouge", f"« Campagnes en cours » parle encore des seuls obligatoires : {entetes}"))
        elif "Taux" in entetes:
            constats.append(("vert", "« Campagnes en cours » : « Taux » sur les mêmes cases que le taux en tête (facultatifs exclus)"))
        else:
            constats.append(("rouge", f"colonne « Taux » absente de « Campagnes en cours » : {entetes}"))
    return constats


def _ouvrir_case(page, url, chemin, selecteur):
    page.goto(url + chemin, wait_until="load")
    case = page.locator(selecteur).first
    if not case.count():
        return None
    case.click()
    page.wait_for_selector("body.panneau-ouvert #panneau-contenu", timeout=6000)
    page.wait_for_timeout(300)
    return case


RIEN_A_SAISIR = "aucune case à saisir ni brouillon pour ce compte"  # « sauté » légitime d'un contrôle bloquant
AUCUNE_ALERTE = "aucune ligne en alerte pour ce compte"  # idem pour justifier_dans_le_panneau
CASES_A_SAISIR = "tr.ligne[data-url][data-statut=a_saisir], tr.ligne[data-url][data-statut=brouillon]"


def _taper_sans_enregistrer(page):
    """Modifie la valeur du panneau ouvert sans rien envoyer : nombre tapé, autre option de la liste, autre puce
    oui / non. Rend False si la valeur n'est pas modifiable (saisie fermée, N/A coché, lecture seule)."""
    champ = page.locator("#panneau-contenu form[data-garde] [name=valeur]:not([disabled])")
    if not champ.count():
        return False
    premier = champ.first
    if premier.get_attribute("type") == "radio":
        libre = page.locator("#panneau-contenu form[data-garde] [name=valeur][type=radio]:not([disabled]):not(:checked)")
        if not libre.count():
            return False
        libre.first.locator("xpath=ancestor::label[1]").click()  # la puce (étiquette) recouvre le bouton rond
    elif premier.evaluate("e => e.tagName") == "SELECT":
        autre = premier.evaluate("e => [...e.options].findIndex((o, i) => i > 0 && !o.selected)")
        if autre < 1:
            return False
        premier.select_option(index=autre)
    else:
        premier.fill("123456")
    return True


def _bloquer_enregistrement(page):
    """Brouillon automatique : fermer le panneau enregistre la saisie. Pour vérifier la question sans rien
    écrire en base, les envois du panneau (POST /saisie/…) sont refusés le temps du contrôle : la saisie ne peut pas
    partir, l'outil doit donc poser la question. Rend la fonction qui lève le blocage."""
    def refuser(route):
        if route.request.method == "POST":
            route.abort()
        else:
            route.continue_()
    page.route("**/saisie/**", refuser)
    return lambda: page.unroute("**/saisie/**", refuser)


def ctl_panneau_valeur_conservee(role, page, url, o):
    """P2 : fermer le panneau (Échap, croix) avec une valeur tapée non enregistrée pose la question. Cherche une
    case modifiable dans Pour moi, puis « Tous mes référentiels », puis Saisie ; chaque essai se termine par « Fermer
    sans enregistrer » (rien n'est écrit)."""
    if role != "contributeur":
        return []
    lever = _bloquer_enregistrement(page)
    try:
        return _panneau_valeur_conservee(page, url)
    finally:
        lever()


def _panneau_valeur_conservee(page, url):
    constats, vues = [], 0
    for geste in ("Échap", "croix"):
        trouve = False
        for chemin in ("/pour-moi/", "/pour-moi/?tous=1", "/saisie/"):
            page.goto(url + chemin, wait_until="load")
            n = page.locator(CASES_A_SAISIR).count()
            vues += n
            for i in range(min(n, 8)):
                if i:
                    page.goto(url + chemin, wait_until="load")
                case = page.locator(CASES_A_SAISIR).nth(i)
                case.click()
                page.wait_for_selector("body.panneau-ouvert #panneau-contenu", timeout=6000)
                page.wait_for_timeout(300)
                if _taper_sans_enregistrer(page):
                    trouve = True
                    break
                page.keyboard.press("Escape")  # rien de modifié : le panneau se ferme sans question
                page.wait_for_timeout(200)
            if trouve:
                break
        if not trouve:
            return [("saute", RIEN_A_SAISIR if not vues else
                     f"{vues} case(s) à saisir ou en brouillon, aucune avec une valeur modifiable (saisie fermée ou N/A)")]
        if geste == "Échap":
            page.keyboard.press("Escape")
        else:
            page.locator("#panneau [data-fermer]").first.click()
        page.wait_for_timeout(500)
        ouvert = page.evaluate("() => document.body.classList.contains('panneau-ouvert')")
        question = page.get_by_text(re.compile("Fermer sans enregistrer")).filter(visible=True).count() > 0
        if not ouvert and not question:
            constats.append(("rouge", f"{geste} ({chemin}) : le panneau se ferme et la valeur tapée est perdue, sans question"))
        else:
            constats.append(("vert", f"{geste} ({chemin}) : {'question posée' if question else 'panneau resté ouvert'}"))
            bouton = page.get_by_role("button", name=re.compile("Fermer sans enregistrer"))
            if bouton.count():
                bouton.first.click()  # ne rien enregistrer
    return constats


def ctl_justifier_dans_le_panneau(role, page, url, o):
    """P3 : l'alerte se justifie dans le panneau (« C'est juste ? J'explique pourquoi », ou, pour un écart avec N-1, le
    renvoi au commentaire), avec un constat lisible dans la liste ; aucune fiche d'alerte refusée depuis le panneau ;
    « Justifier » du bandeau ouvre la première ligne en alerte, sans quitter la saisie. Rien n'est enregistré."""
    if role != "contributeur":
        return []
    constats = []
    case = _ouvrir_case(page, url, "/pour-moi/", "tr.ligne[data-url][data-alerte='1']")
    if case is None:
        return [("saute", AUCUNE_ALERTE)]
    constat = case.locator(".constat-ligne")
    if not constat.count() or not constat.first.is_visible() or not constat.first.inner_text().strip():
        constats.append(("rouge", "le constat de l'alerte n'est pas visible dans la liste (seulement dans une infobulle)"))
    else:
        constats.append(("vert", f"constat visible dans la liste : « {constat.first.inner_text().strip()[:80]} »"))
    panneau = page.locator("#panneau-contenu")
    if panneau.locator("textarea[name=justification]").count():
        constats.append(("vert", "champ « C'est juste ? J'explique pourquoi » dans le panneau"))
    elif panneau.locator("[data-vers-commentaire]").count():
        constats.append(("vert", "écart avec N-1 : « J'explique dans le commentaire » dans le panneau"))
    elif "L'administrateur traite cette alerte" in panneau.inner_text():
        constats.append(("vert", "alerte hors des cases de la personne : l'administrateur la traite"))
    else:
        constats.append(("rouge", "le panneau n'a pas de champ pour expliquer l'alerte (seulement un lien vers sa fiche)"))
    for href in panneau.locator("a.pa-fiche, a[href*='/coherence/alerte/']").evaluate_all("l => l.map(a => a.href)"):
        statut = page.request.get(href).status  # lecture de la fiche : n'écrit rien
        if statut != 200:
            constats.append(("rouge", f"le panneau mène à une fiche d'alerte refusée ({statut}) : {href}"))
    resume = page.locator("#resume")
    texte = panneau.inner_text() + " " + case.inner_text() + " " + (resume.first.inner_text() if resume.count() else "")
    if re.search(r"×\s*la médiane", texte):
        constats.append(("rouge", "constat opaque « … × la médiane »"))
    if re.search(r"\{[#%]", texte):
        constats.append(("rouge", "balise de gabarit affichée en clair (« {# » ou « {% ») dans le bandeau, la ligne ou le panneau"))
    page.keyboard.press("Escape")
    page.goto(url + "/saisie/", wait_until="load")
    justifier = page.locator("#resume a", has_text=re.compile(r"^\s*Justifier\s*$"))
    if justifier.count():
        lien = justifier.first
        if lien.get_attribute("data-justifier") is None and re.match(r"^(https?://[^/]+)?/coherence/", lien.get_attribute("href") or ""):
            constats.append(("rouge", "« Justifier » du bandeau mène à la page Cohérence, hors de la saisie"))
        elif page.locator("#liste tr.ligne[data-url][data-alerte='1']").count():
            avant = page.url
            lien.click()
            try:
                page.wait_for_selector("body.panneau-ouvert #panneau-contenu [data-points]", timeout=6000)
                constats.append(("vert", "« Justifier » ouvre la première ligne en alerte dans le panneau"))
            except Exception:  # noqa: BLE001 - panneau resté fermé ou page quittée
                constats.append(("rouge", f"« Justifier » n'ouvre pas le panneau de la première ligne en alerte ({page.url})"))
            if page.url == avant:
                page.keyboard.press("Escape")
    return constats


def ctl_relances_sans_smtp(role, page, url, o):
    """P4 : sans serveur d'e-mails, la page Relances ne propose pas d'envoyer ; dernière relance visible."""
    if role != "admin":
        return []
    if o.smtp:
        return [("saute", "démo branchée sur un serveur d'e-mails (--smtp) : l'envoi réel se vérifie avec --base-jetable")]
    page.goto(url + "/tableau-de-bord/relances/", wait_until="load")
    constats = []
    envoyer = page.locator("button[value=envoyer]:not([disabled]), button[value=essai]:not([disabled])")
    if envoyer.count():
        constats.append(("rouge", f"sans SMTP, {envoyer.count()} bouton(s) « Envoyer la relance » / « M'envoyer un essai » actifs : "
                                  "des relances seraient notées « envoyées » sans rien envoyer"))
    else:
        constats.append(("vert", "sans SMTP, aucun bouton d'envoi actif"))
    encart = page.locator(".encart.encart-avertissement[role=status]")
    constats.append(("vert", "encart orange « e-mails pas encore activés » en tête") if encart.count()
                    else ("rouge", "sans SMTP, pas d'encart qui dit que rien ne part"))
    if page.locator("table.table-relances").count():
        ecrire = page.locator("table.table-relances a.lien-action[aria-label^='Écrire à']").count()
        lignes = page.locator("table.table-relances tbody tr").count()
        constats.append(("vert", f"« Écrire à … » sur chaque ligne ({ecrire})") if ecrire and ecrire >= lignes
                        else ("rouge", f"« Écrire à … » sur {ecrire} ligne(s) sur {lignes}"))
        copier = page.locator("#apercu [data-copier='#ecrire-message']").count()
        constats.append(("vert", "message à copier pour la personne choisie") if copier
                        else ("rouge", "pas de bouton « Copier le message » dans « Écrire à … »"))
    page.goto(url + "/tableau-de-bord/", wait_until="load")
    faux = page.locator("main .entete-page a.bouton:not(.secondaire)", has_text="Relancer…").count()
    constats.append(("rouge", "tableau de bord : bouton principal « Relancer… » alors que rien ne part") if faux
                    else ("vert", "tableau de bord : pas de bouton « Relancer… » trompeur"))
    return constats


def _hauteur_min(page, selecteur):
    """Hauteur (px) de la plus petite zone visible qui répond au sélecteur, et leur nombre ; (None, 0) sans zone visible."""
    h = page.evaluate("""(sel) => [...document.querySelectorAll(sel)].filter(e => e.offsetParent !== null)
        .map(e => e.getBoundingClientRect().height)""", selecteur)
    return (round(min(h), 1) if h else None), len(h)


def _zone(constats, nom, hauteur, n):
    if hauteur is None:
        constats.append(("saute", f"{nom} : absent de cette démo"))
    else:
        constats.append(("vert" if hauteur >= 24 else "rouge", f"{nom} : {n} zone(s), {hauteur:g} px de haut au moins (24 attendus)"))


def ctl_accessibilite_plus(role, page, url, o, tel=None):
    """P5 accessibilité et téléphone (étape 6) : lien d'évitement puis contenu en peu de tabulations, vrais titres de
    section (arbre d'accessibilité), pastilles avec aria-pressed et nombre de lignes annoncé à l'action seulement,
    question du panneau qui garde puis rend le focus, focus sur l'explication après « Justifier », marge de 16 px et
    écart N-1 visible sur téléphone, marqueurs des sections visibles ; pour l'admin, libellés Import / Export et
    Administration visibles à 1 440 px, zones à toucher de 24 px (arbre du tableau de bord, « Pleine page », « Rouvrir la
    saisie », aides repliables), colonne « Indicateur » de Saisie lisible à 390 et 360 px ; pour chaque rôle, onglets
    jamais coupés au-dessus de 800 px (tablette comprise). Rien n'est enregistré (la question se règle par « Fermer sans
    enregistrer »)."""
    constats = []
    # onglets jamais coupés au-dessus de 800 px : serrerOnglets (_app/01_socle.js) retire ce qui ne tient pas, puis les fait passer
    # sur leur propre rangée ; sous 800 px ils défilent avec un fondu
    debords = {}
    for largeur in (820, 900, 1024):
        page.set_viewport_size({"width": largeur, "height": 900})
        page.goto(url + "/tableau-de-bord/", wait_until="load")
        page.wait_for_timeout(100)
        debords[largeur] = page.evaluate("() => (n => n ? n.scrollWidth - n.clientWidth : 0)(document.querySelector('nav.onglets'))")
    page.set_viewport_size(TAILLES["bureau"])
    trop = {k: v for k, v in debords.items() if v > 0}
    constats.append(("rouge" if trop else "vert", "onglets coupés sur tablette : " + ", ".join(f"{v} px de trop à {k} px" for k, v in trop.items())
                     if trop else "onglets entiers dans le bandeau à 820, 900 et 1 024 px"))
    if role == "admin" and tel is not None:
        # colonne « Indicateur » de Saisie (case, valeur, statut et SPOC ont une largeur fixe) : 72 px au moins à 390 px
        for largeur, minimum in ((390, 72), (360, 40)):
            pg = tel.new_page()
            pg.set_viewport_size({"width": largeur, "height": 844})
            pg.goto(url + "/saisie/", wait_until="load")
            l = pg.evaluate("""() => { const th = [...document.querySelectorAll('#liste table.cellules thead th')].find(t => /Indicateur/.test(t.textContent));
                return th ? Math.round(th.getBoundingClientRect().width) : null; }""")
            pg.close()
            if l is None:
                constats.append(("saute", f"colonne « Indicateur » à {largeur} px : pas de liste sur Saisie"))
            else:
                constats.append(("vert" if l >= minimum else "rouge", f"colonne « Indicateur » de Saisie à {largeur} px : {l} px ({minimum} attendus au moins)"))
    if role == "admin":
        page.goto(url + "/saisie/", wait_until="load")
        libelles = page.evaluate("""() => [...document.querySelectorAll('nav.onglets .libelle-onglet')]
            .map(l => [l.textContent.trim(), l.offsetWidth > 0])""")
        caches = [t for t, vu in libelles if not vu]
        constats.append(("rouge" if caches or not libelles else "vert",
                         f"libellés cachés à 1 440 px : {', '.join(caches)}" if caches else
                         f"libellés visibles à 1 440 px : {', '.join(t for t, _ in libelles)}" if libelles else "aucun onglet Import / Export ni Administration"))
        # onglets jamais coupés (nom de l'outil réglable : serrerOnglets retire ce qui ne tient pas), y compris à 1 536 px
        debords = {}
        for largeur in (1440, 1536, 1600):
            page.set_viewport_size({"width": largeur, "height": 900})
            page.goto(url + "/administration/", wait_until="load")
            debords[largeur] = page.evaluate("() => (n => n ? n.scrollWidth - n.clientWidth : 0)(document.querySelector('nav.onglets'))")
        page.set_viewport_size(TAILLES["bureau"])
        trop = {k: v for k, v in debords.items() if v > 0}
        constats.append(("rouge" if trop else "vert", "onglets coupés dans le bandeau : " + ", ".join(f"{v} px de trop à {k} px" for k, v in trop.items())
                         if trop else "onglets entiers dans le bandeau à 1 440, 1 536 et 1 600 px"))
        # chaque ligne qui ouvre un panneau (tr[data-url]) est atteignable au clavier (Tab, puis Entrée)
        hors_clavier = {}
        for chemin in ("/saisie/", "/referentiel/", "/coherence/", "/coherence/regles/", "/administration/campagnes/",
                       "/administration/comptes/", "/administration/organisations/"):
            if chemin in PAGES_QUI_ECRIVENT and not o.base_jetable:
                continue  # l'ouverture de Cohérence réécrit les alertes : seulement sur une démo jetable
            page.goto(url + chemin, wait_until="load")
            n = page.evaluate("() => [...document.querySelectorAll('tr[data-url]')].filter(t => t.tabIndex < 0).length")
            if n:
                hors_clavier[chemin] = n
        constats.append(("rouge" if hors_clavier else "vert", "lignes hors d'atteinte au clavier : "
                         + ", ".join(f"{k} ({v})" for k, v in hors_clavier.items()) if hors_clavier else
                         "lignes atteignables au clavier (Saisie, Catalogue, Cohérence, Règles, Campagnes, Comptes, Organisations)"))
        # zones à toucher, sur ordinateur puis sur téléphone
        for nom_ctx, pg in (("1 440 px", page), ("390 px", tel.new_page() if tel is not None else None)):
            if pg is None:
                continue
            pg.goto(url + "/tableau-de-bord/", wait_until="load")
            _zone(constats, f"liens d'organisation du tableau de bord ({nom_ctx})", *_hauteur_min(pg, "td.retrait-arbre a"))
            pg.goto(url + "/administration/parametres/hebergement/", wait_until="load")
            _zone(constats, f"aides repliables d'Hébergement ({nom_ctx})", *_hauteur_min(pg, ".aide-repliable > summary"))
            marqueur = pg.evaluate("""() => [...document.querySelectorAll('.aide-repliable > summary')].filter(e => e.offsetParent !== null)
                .every(e => { const c = getComputedStyle(e, '::before'); return c.content !== 'none' && parseFloat(c.width) >= 10; })""")
            # depuis l' : un chevron dessiné (:before) à la place du triangle du navigateur
            constats.append(("vert" if marqueur else "rouge", f"aides repliables ({nom_ctx}) : chevron "
                             + ("visible" if marqueur else "perdu (le summary n'a plus de repère)")))
            pg.goto(url + "/saisie/", wait_until="load")
            case = pg.locator("tr.ligne[data-url][data-statut=valide]:not(.calculee)").first
            if case.count():
                case.click()
                pg.wait_for_selector("body.panneau-ouvert #panneau-contenu", timeout=6000)
                pg.wait_for_timeout(300)
                _zone(constats, f"« Pleine page » ({nom_ctx})", *_hauteur_min(pg, "#panneau-contenu .lien-pleine-page"))
                _zone(constats, f"« Repasser en brouillon » ({nom_ctx})", *_hauteur_min(pg, "#panneau-contenu .retour-saisie button"))
                pg.keyboard.press("Escape")  # rien de modifié : le panneau se ferme sans question
            else:
                constats.append(("saute", f"aucune valeur validée sur Saisie pour mesurer « Pleine page » ({nom_ctx})"))
            if pg is not page:
                pg.close()
        return constats
    if role != "contributeur":
        return constats
    page.goto(url + "/saisie/", wait_until="load")
    page.keyboard.press("Tab")
    evitement = page.evaluate("""() => { const e = document.activeElement; const h = e && e.getAttribute('href');
        return !!(e && e.tagName === 'A' && h && h.startsWith('#') && h.length > 1 && document.getElementById(h.slice(1))); }""")
    constats.append(("vert" if evitement else "rouge", "lien « Aller au contenu » en premier" if evitement else "pas de lien d'évitement en premier"))
    if evitement:
        page.keyboard.press("Enter")
        page.wait_for_timeout(100)
        sur_main = page.evaluate("() => document.activeElement?.tagName === 'MAIN'")
        constats.append(("vert" if sur_main else "rouge", "Entrée sur « Aller au contenu » : le focus va au contenu (main)" if sur_main
                         else "Entrée sur « Aller au contenu » ne met pas le focus sur le contenu"))
    # première ligne de la liste en 3 tabulations au plus : depuis le second lien d'évitement, « Aller aux KPI »
    # (Saisie et Pour moi), quel que soit l'état du bandeau (Commencer, Justifier, tout fait, saisie fermée)
    for chemin in ("/saisie/", "/pour-moi/"):
        page.goto(url + chemin, wait_until="load")
        if not page.locator("#liste tr.ligne").count():
            constats.append(("saute", f"{chemin} : aucune ligne dans la liste pour ce compte"))
            continue
        page.keyboard.press("Tab")
        page.keyboard.press("Tab")
        lien = page.evaluate("() => document.activeElement?.matches('a.lien-evitement[href=\"#liste\"]') ? document.activeElement.textContent.trim() : ''")
        if not lien:
            constats.append(("rouge", f"{chemin} : pas de lien « Aller aux KPI » au deuxième arrêt du clavier"))
            continue
        page.keyboard.press("Enter")
        page.wait_for_timeout(100)
        atteinte = None
        for n in range(1, 4):
            page.keyboard.press("Tab")
            if page.evaluate("() => !!document.activeElement?.matches('tr.ligne')"):
                atteinte = n
                break
        constats.append(("vert", f"{chemin} : première ligne en {atteinte} tabulation(s) après « {lien} »") if atteinte
                        else ("rouge", f"{chemin} : plus de 3 tabulations entre « {lien} » et la première ligne"))
    page.goto(url + "/saisie/", wait_until="load")
    titres = page.locator("#liste").aria_snapshot() if page.locator("#liste").count() else ""
    n2 = len(re.findall(r"heading .*\[level=2\]", titres))
    constats.append(("vert" if n2 else "rouge", f"{n2} titre(s) de section de niveau 2 dans l'arbre d'accessibilité de Saisie"))
    pastilles = page.evaluate("() => [...document.querySelectorAll('[data-filtre-statut]')].map(b => b.getAttribute('aria-pressed'))")
    if pastilles and None in pastilles:
        constats.append(("rouge", f"pastilles de filtre sans aria-pressed ({pastilles.count(None)} sur {len(pastilles)})"))
    elif pastilles:
        annonce_avant = page.evaluate("() => document.getElementById('annonce-filtres')?.textContent ?? null")
        page.locator("[data-filtre-statut=valide]").first.click()
        page.wait_for_timeout(200)
        etat = page.evaluate("""() => ({presse: [...document.querySelectorAll('[data-filtre-statut]')].filter(b => b.getAttribute('aria-pressed') === 'true')
            .map(b => b.dataset.filtreStatut), annonce: document.getElementById('annonce-filtres')?.textContent || '',
            dans_resume: !!document.querySelector('#resume #annonce-filtres')})""")
        page.locator("[data-filtre-statut='']").first.click()  # retour à « Total »
        bon = etat["presse"] == ["valide"]
        constats.append(("vert" if bon else "rouge", f"pastilles avec aria-pressed (« Validé » choisie : {etat['presse']})"))
        annonce_ok = re.match(r"^(\d+ KPI affichés?|Aucun KPI ne correspond aux filtres\.)$", etat["annonce"]) and not etat["dans_resume"]
        constats.append(("vert" if annonce_ok else "rouge", f"nombre de lignes annoncé au filtrage : « {etat['annonce']} »"
                         + (" (dans #resume, relu à chaque enregistrement)" if etat["dans_resume"] else "")))
        constats.append(("vert" if annonce_avant == "" else "rouge", "aucune annonce de filtre au chargement" if annonce_avant == ""
                         else f"annonce au chargement, sans action de la personne : « {annonce_avant} »"))
    # « Justifier » : le focus va à l'explication de l'alerte, dans le panneau (avant Pour moi : « Tous mes
    # référentiels » change la campagne gardée dans la session)
    page.goto(url + "/saisie/", wait_until="load")
    justifier = page.locator("#resume a[data-justifier]")
    if justifier.count() and page.locator("#liste tr.ligne[data-url][data-alerte='1']").count():
        justifier.first.click()
        try:
            page.wait_for_selector("body.panneau-ouvert #panneau-contenu [data-points]", timeout=6000)
            page.wait_for_timeout(300)
            message = page.evaluate("() => !!document.activeElement?.closest('#panneau-contenu [data-points]')")
        except Exception:  # noqa: BLE001 - panneau resté fermé
            message = False
        constats.append(("vert" if message else "rouge", "après « Justifier », le focus est sur l'explication de l'alerte" if message
                         else "après « Justifier », le focus n'est pas sur l'explication de l'alerte"))
        page.keyboard.press("Escape")
    else:
        constats.append(("saute", "focus après « Justifier » : pas de « Justifier » ni de ligne en alerte sur Saisie pour ce compte"))
    # Pour moi, tous les référentiels : titres de section en h3, sous le titre (h2) de chaque référentiel
    page.goto(url + "/pour-moi/?tous=1", wait_until="load")
    if not page.locator("#liste .titre-bloc-ref").count():  # une seule campagne : pas de vue d'ensemble, titres en h2
        constats.append(("saute", "Pour moi : pas de vue « Tous mes référentiels » (une seule campagne en cours)"))
    elif page.locator("#liste details.section").count():
        arbre = page.locator("#liste").aria_snapshot()
        n3 = len(re.findall(r"heading .*\[level=3\]", arbre))
        constats.append(("vert" if n3 else "rouge", f"Pour moi, tous mes référentiels : {n3} titre(s) de section de niveau 3"))
    # question du panneau : garde le focus (Tab y tourne) et le rend au champ (« Continuer la saisie ») ; enregistrement
    # bloqué pendant ce contrôle, sinon le brouillon automatique enregistrerait la saisie au lieu de poser la question
    lever = _bloquer_enregistrement(page)
    for chemin in ("/pour-moi/", "/saisie/"):
        page.goto(url + chemin, wait_until="load")
        cases = page.locator(CASES_A_SAISIR)
        tape = False
        for i in range(min(cases.count(), 6)):
            cases.nth(i).click()
            page.wait_for_selector("body.panneau-ouvert #panneau-contenu", timeout=6000)
            page.wait_for_timeout(300)
            if _taper_sans_enregistrer(page):
                tape = True
                break
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)
        if tape:
            break
    if tape:
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        dans_question = []
        for _ in range(5):
            dans_question.append(page.evaluate("() => !!document.activeElement?.closest('[data-question]:not([hidden])')"))
            page.keyboard.press("Tab")
        constats.append(("vert" if all(dans_question) else "rouge", "la question garde le focus (Tab tourne dans ses boutons)"
                         if all(dans_question) else f"le focus sort de la question ({dans_question})"))
        page.get_by_role("button", name=re.compile("^Continuer la saisie$")).first.click()
        page.wait_for_timeout(200)
        rendu = page.evaluate("() => !!document.activeElement?.closest('#panneau-contenu form[data-garde]') && document.activeElement.matches('input, select, textarea')")
        constats.append(("vert" if rendu else "rouge", "« Continuer la saisie » rend le focus au champ" if rendu
                         else "« Continuer la saisie » ne rend pas le focus au champ"))
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        bouton = page.get_by_role("button", name=re.compile("Fermer sans enregistrer"))
        if bouton.count():
            bouton.first.click()  # ne rien enregistrer
    else:
        constats.append(("saute", "question du panneau : " + RIEN_A_SAISIR))
    lever()
    if tel is not None:
        p2 = tel.new_page()
        p2.goto(url + "/saisie/", wait_until="load")
        mesure = p2.evaluate("""() => ({marge: parseFloat(getComputedStyle(document.querySelector('main')).paddingLeft),
            bandeau: parseFloat(getComputedStyle(document.querySelector('.barre-haut')).paddingLeft),
            marqueurs: [...document.querySelectorAll('#liste details.section > summary')].map(s => parseFloat(getComputedStyle(s, '::before').width) || 0)})""")
        constats.append(("vert" if mesure["marge"] >= 16 and mesure["bandeau"] >= 16 else "rouge",
                         f"marge latérale sur téléphone : contenu {mesure['marge']:g} px, bandeau {mesure['bandeau']:g} px (16 attendus)"))
        # E13 : écart au-delà du seuil sous la valeur sur téléphone (Saisie, sinon Pour moi), lu en entier dans sa cellule ;
        # absent à 1 440 px (il est dans sa colonne)
        js_ecarts = """() => [...document.querySelectorAll('.ecart-sous')].map(e => { const td = e.closest('td');
            return {vu: e.offsetParent !== null, dedans: e.getBoundingClientRect().right <= td.getBoundingClientRect().right + 0.5,
                    lu: /^Écart avec .+ au-delà du seuil/.test(e.querySelector('.visuellement-cache')?.textContent || '')}; })"""
        ecarts, ou = [], ""
        for chemin in ("/saisie/", "/pour-moi/", "/pour-moi/?tous=1"):
            p2.goto(url + chemin, wait_until="load")
            ecarts = p2.evaluate(js_ecarts)
            if ecarts:
                ou = chemin
                break
        p2.close()
        if ecarts:
            page.goto(url + ou, wait_until="load")
            au_bureau = sum(e["vu"] for e in page.evaluate(js_ecarts))
            bon = all(e["vu"] and e["dedans"] and e["lu"] for e in ecarts) and not au_bureau
            constats.append(("vert" if bon else "rouge", f"écart N-1 au-delà du seuil sous la valeur ({ou}) : {sum(e['vu'] for e in ecarts)} visible(s) "
                             f"sur {len(ecarts)} à 390 px, {sum(e['dedans'] for e in ecarts)} dans leur cellule, {sum(e['lu'] for e in ecarts)} avec "
                             f"leur texte lu ; {au_bureau} visible(s) à 1 440 px (0 attendu)"))
        else:
            constats.append(("saute", "écart N-1 sous la valeur : aucun écart au-delà du seuil sur Saisie ni Pour moi pour ce compte"))
        if mesure["marqueurs"]:
            constats.append(("vert" if min(mesure["marqueurs"]) > 0 else "rouge", "repère (chevron) des sections visible sur téléphone"))
    return constats


def ctl_tdb_personnes(role, page, url, o):
    """P5 relances par personne. La colonne « À relancer » a été retirée du tableau de bord à la 
    (commit b4d8f77 : « À traiter » porte les alertes, un seul bouton ouvre la page Relances). Le tableau de bord doit donc
    mener à la page Relances, et la liste des personnes y est : un seul lien « Écrire à » par personne."""
    if role != "admin":
        return []
    constats = []
    page.goto(url + "/tableau-de-bord/", wait_until="load")
    acces = page.evaluate("""() => [...document.querySelectorAll('main a')]
        .filter(a => (a.getAttribute('href') || '').includes('/tableau-de-bord/relances/')).length""")
    constats.append(("vert", "le tableau de bord ouvre la page Relances") if acces
                    else ("rouge", "aucun lien du tableau de bord vers la page Relances"))
    page.goto(url + "/tableau-de-bord/relances/", wait_until="load")
    info = page.evaluate("""() => { const t = [...document.querySelectorAll('main h2')].map(h => h.textContent.trim());
        const liens = [...document.querySelectorAll('main a')].filter(a => /^Écrire à /.test((a.getAttribute('aria-label') || a.textContent).trim()));
        const personnes = liens.map(a => new URLSearchParams((a.getAttribute('href') || '').split('?')[1] || '').get('apercu'));
        return {titres: t, liens: liens.length, sans_personne: personnes.filter(p => !p).length,
                doublons: personnes.filter(p => p).length - new Set(personnes.filter(p => p)).size}; }""")
    if not any(re.match(r"À relancer", t) for t in info["titres"]):
        constats.append(("rouge", f"pas de liste « À relancer » sur la page Relances (titres : {', '.join(info['titres']) or '—'})"))
    else:
        constats.append(("vert", "la liste « À relancer » est sur la page Relances"))
    if not info["liens"]:  # « \\b » ne marche pas après « à » : ne jamais rendre vert un contrôle qui n'a rien compté
        constats.append(("rouge", "aucun lien « Écrire à » sur la page Relances"))
    elif info["sans_personne"] or info["doublons"]:
        constats.append(("rouge", f"{info['liens']} liens « Écrire à » dont {info['sans_personne']} sans personne "
                                  f"et {info['doublons']} en double pour une même personne"))
    else:
        constats.append(("vert", f"{info['liens']} lien(s) « Écrire à », un par personne"))
    return constats


def ctl_visualisation(role, page, url, o, tel=None):
    """Visualisation v2 : la vue par défaut dessine ses graphiques ; flèches au clavier sur un graphique (la zone d'annonce
    lit la valeur) ; « Voir les données » ouvre un vrai tableau ; aucune défilement horizontal à 390 px."""
    constats = []
    page.goto(url + "/visualisation/", wait_until="load")
    page.wait_for_timeout(800)
    n = page.evaluate("document.querySelectorAll('[data-visuel]').length")
    g = page.locator(".graphique").first
    if not n:
        return [("saute", "aucun visuel dans la vue par défaut")]
    constats.append(("vert", f"{n} visuel(s) dans la vue par défaut"))
    if g.count():
        g.scroll_into_view_if_needed()
        page.wait_for_timeout(400)
        g.focus()
        page.keyboard.press("ArrowRight")
        page.wait_for_timeout(300)
        lu = page.evaluate("(document.getElementById('annonce-visu') || {}).textContent || ''")
        constats.append(("vert" if lu.strip() else "rouge", f"flèche sur un graphique : annonce « {lu.strip()[:80]} »"))
        b = page.locator(".lien-donnees").first
        if b.count():
            b.click()
            ouvert = b.get_attribute("aria-expanded") == "true" and page.locator(".donnees-visuel.ouvert table").count() > 0
            constats.append(("vert" if ouvert else "rouge", "« Voir les données » ouvre le tableau de données"))
    if tel is not None:
        pt = tel.new_page()
        try:
            pt.goto(url + "/visualisation/", wait_until="load")
            pt.wait_for_timeout(600)
            deb = pt.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        finally:
            pt.close()
        constats.append(("vert" if deb <= 1 else "rouge", f"téléphone 390 px : débordement {deb} px"))
    return constats


FONCTIONS_CONTROLES = {"etats_coherents": ctl_etats_coherents, "panneau_valeur_conservee": ctl_panneau_valeur_conservee,
                       "justifier_dans_le_panneau": ctl_justifier_dans_le_panneau, "relances_sans_smtp": ctl_relances_sans_smtp,
                       "accessibilite_plus": ctl_accessibilite_plus, "tdb_personnes": ctl_tdb_personnes,
                       "visualisation": ctl_visualisation}


ETATS_EN = {"rouge": "red", "vert": "green", "saute": "skipped"}  # état d'un contrôle, affiché en anglais


def controler(sessions, url, o):
    """Lance les 6 contrôles nommés pour chaque rôle, AVANT toute ouverture de Cohérence et tout parcours de saisie."""
    resultats = []
    for nom in CONTROLES:
        constats = []
        for role, (page, tel) in sessions.items():
            if role in ROLES_LECTURE:  # lecteur et auditeur : pages et écriture vérifiées à part (rien à saisir)
                continue
            try:
                f = FONCTIONS_CONTROLES[nom]
                faits = f(role, page, url, o, tel) if nom in ("accessibilite_plus", "visualisation") else f(role, page, url, o)
            except Exception as e:
                faits = [("rouge", f"le contrôle a échoué : {str(e)[:200]}")]
            constats += [(etat, f"[{role}] " + " ".join(texte.split())) for etat, texte in faits]
        etats = {e for e, _ in constats}
        etat = "rouge" if "rouge" in etats else "vert" if "vert" in etats else "saute"
        resultats.append({"nom": nom, "etat": etat, "bloquant": nom in CONTROLES_BLOQUANTS,
                          "preuve": "; ".join(t for e, t in constats if e == etat) or "aucun rôle concerné",
                          "constats": [{"etat": e, "texte": t} for e, t in constats]})
        print(f"check {nom:26} {ETATS_EN[etat]:7}{' (blocking)' if nom in CONTROLES_BLOQUANTS else ''}  {resultats[-1]['preuve'][:220]}", flush=True)
    return resultats


def premier_referentiel(page, url):
    """Code du premier référentiel (Administration › Référentiels), ou ""."""
    page.goto(url + "/administration/referentiels/", wait_until="domcontentloaded")
    lien = page.evaluate("document.querySelector('.ligne-referentiel .nom-ligne-ref')?.getAttribute('href') || ''")
    m = re.search(r"/administration/referentiels/([^/]+)/", lien)
    return m.group(1) if m else ""


def adresse_restauration(page, url):
    """Adresse de la confirmation de restauration de la première sauvegarde listée sur Hébergement, ou None."""
    page.goto(url + "/administration/parametres/hebergement/", wait_until="load")
    lien = page.locator("a[href*='/hebergement/restaurer/']").first
    return lien.get_attribute("href") if lien.count() else None


def adresse_visu(page, url, quoi):
    """Adresse du premier thème (« @visu-theme ») ou du premier KPI (« @visu-kpi ») que la personne voit, lus dans le
    catalogue de la Visualisation (celui du panneau des KPI)."""
    rep = page.request.get(url + "/visualisation/donnees/catalogue/")
    if not rep.ok:
        return None
    c = rep.json()
    if quoi == "@visu-theme":
        theme = next((t for r in c["referentiels"] for t in r["themes"] if t["prof"] == 0), None)
        return f"/visualisation/theme/{theme['id']}/" if theme else None
    return f"/visualisation/kpi/{c['kpis'][0]['code']}/" if c["kpis"] else None


def main():
    a = argparse.ArgumentParser(description="Browser acceptance check by role (see the docstring of qa/browser_check.py).")
    # noms anglais ; les anciens noms français restent acceptés
    a.add_argument("--url", default="http://127.0.0.1:8013")
    a.add_argument("--axe", required=True, help="axe.min.js file (axe-core)")
    a.add_argument("--output", "--sortie", dest="sortie", required=True, help="folder for resultats.json and the screenshots")
    a.add_argument("--password", "--mot-de-passe", dest="mot_de_passe", default="demo-probant-2026")
    a.add_argument("--base", default="", help="SQLite file of the demo, read-only, to prove that no business row is written")
    a.add_argument("--disposable-base", "--base-jetable", dest="base_jetable", action="store_true",
                   help="disposable demo: also do the data entry walkthrough and open Consistency (they write to the database)")
    a.add_argument("--smtp", action="store_true", help="the demo is connected to an e-mail server (disposable_demo.sh --smtp)")
    a.add_argument("--dark", "--sombre", dest="sombre", action="store_true",
                   help="dark appearance: the browser reports prefers-color-scheme: dark (contrasts of the dark palette)")
    a.add_argument("--roles", default="", help="only these roles, separated by commas (default: all; e.g. admin,lecteur)")
    a.add_argument("--resume", action="store_true",
                   help="continue a stopped run: reads resultats.json of --output, does not redo the named checks nor the roles already done")
    for role in PAGES:
        a.add_argument(f"--{role}", default=role)
    o = a.parse_args()
    roles = [r for r in (x.strip() for x in o.roles.split(",")) if r] or list(PAGES)
    inconnus = [r for r in roles if r not in PAGES]
    if inconnus:
        a.error(f"unknown role(s): {', '.join(inconnus)} (roles: {', '.join(PAGES)})")
    os.makedirs(o.sortie, exist_ok=True)
    axe = open(o.axe, encoding="utf-8").read()
    resultats, echec, non_verifie = {}, False, []
    chemin_json = os.path.join(o.sortie, "resultats.json")
    if o.resume and os.path.exists(chemin_json):
        with open(chemin_json, encoding="utf-8") as f:
            resultats = json.load(f)
        passage = resultats.get("passage", {})
        echec, non_verifie = bool(passage.get("echec")), list(passage.get("non_verifie", []))
        print(f"resuming: roles already done: {', '.join(r for r in PAGES if r in resultats) or 'none'}; "
              f"named checks {'done' if 'controles' in resultats else 'to do'}", flush=True)
    faits = [r for r in roles if r in resultats and o.resume]
    a_faire = [r for r in roles if r not in faits]
    avant = empreinte(o.base)
    debut = time.monotonic()

    def enregistrer(termine):
        """resultats.json à jour : un passage arrêté se reprend avec --resume."""
        resultats["passage"] = {"termine": termine, "echec": echec, "non_verifie": non_verifie,
                                "roles": [r for r in PAGES if r in resultats]}
        with open(chemin_json, "w", encoding="utf-8") as f:
            json.dump(resultats, f, ensure_ascii=False, indent=1)
    with sync_playwright() as p:
        nav = navigateur(p)
        sessions, contextes = {}, []
        for role in a_faire:
            schema = "dark" if o.sombre else "light"  # apparence sombre (--dark) : mêmes contrôles, palette sombre
            ctx = nav.new_context(viewport=TAILLES["bureau"], color_scheme=schema)
            page = connecter(ctx, o.url, getattr(o, role), o.mot_de_passe)
            tab = nav.new_context(viewport=TAILLES["tablette"], has_touch=True, color_scheme=schema)
            tel = nav.new_context(viewport=TAILLES["telephone"], is_mobile=True, has_touch=True, color_scheme=schema)
            tab.add_cookies(ctx.cookies())
            tel.add_cookies(ctx.cookies())
            sessions[role] = (page, tel)
            contextes.append((role, ctx, page, tab, tel))
        if "controles" not in resultats:  # (reprise : déjà faits, avec leur verdict)
            resultats["controles"] = controler(sessions, o.url, o)
            echec |= any(c["etat"] == "rouge" and c["nom"] in CONTROLES_BLOQUANTS for c in resultats["controles"])
            # contrôle bloquant sauté : non vérifié ; c'est un échec, sauf s'il n'y avait vraiment rien à saisir pour ce compte
            for c in resultats["controles"]:
                if c["etat"] == "saute" and c["nom"] in CONTROLES_BLOQUANTS:
                    non_verifie.append(f"contrôle bloquant {c['nom']} : {c['preuve']}")
                    echec |= any(x["etat"] == "saute" and not x["texte"].endswith((RIEN_A_SAISIR, AUCUNE_ALERTE)) for x in c["constats"])
            enregistrer(False)
        total = sum(len(PAGES[r]) for r in a_faire)
        fait = 0
        for n_role, (role, ctx, page, tab, tel) in enumerate(contextes, 1):
            print(f"--- role {role} ({n_role}/{len(contextes)}), {len(PAGES[role])} pages, {int(time.monotonic() - debut)} s elapsed", flush=True)
            r = {"pages": {}, "axe_detail": {}}
            for nom, chemin in PAGES[role]:
                fait += 1
                if chemin == "@restauration":
                    chemin = adresse_restauration(page, o.url)
                    if not chemin:
                        r["pages"][nom] = {"saute": "aucune sauvegarde dans la démo"}
                        non_verifie.append(f"{nom} ({role}) : aucune sauvegarde dans la démo")
                        print(f"{role:13} {nom:28} skipped (no backup in the demo)", flush=True)
                        continue
                    chemin = re.sub(r"^https?://[^/]+", "", chemin)
                if "@ref" in chemin:  # premier référentiel de la démo (son code dépend du client)
                    code = premier_referentiel(page, o.url)
                    if not code:
                        r["pages"][nom] = {"saute": "aucun référentiel dans la démo"}
                        non_verifie.append(f"{nom} ({role}) : aucun référentiel")
                        continue
                    chemin = chemin.replace("@ref", code)
                if chemin in ("@visu-theme", "@visu-kpi"):
                    chemin = adresse_visu(page, o.url, chemin)
                    if not chemin:
                        r["pages"][nom] = {"saute": "aucun thème à visualiser dans la démo"}
                        non_verifie.append(f"{nom} ({role}) : aucun thème à visualiser")
                        continue
                if chemin in PAGES_QUI_ECRIVENT and not o.base_jetable and role not in ROLES_LECTURE:
                    r["pages"][nom] = {"saute": "son ouverture écrit en base (alertes) : seulement avec --base-jetable"}
                    non_verifie.append(f"{nom} ({role})")
                    print(f"{role:13} {nom:28} skipped (writes to the database; --disposable-base to open it)", flush=True)
                    continue
                detail = []
                m = mesurer(page, o.url + chemin, axe, detail)
                fichier = f"{role}_{chemin.strip('/').replace('/', '_').replace('?', '_').replace('=', '-') or 'accueil'}.png"
                capture(page, "bureau_" + fichier, o.sortie)
                m["debordement_tablette_px"] = debordement(tab, o.url + chemin, "tab_" + fichier, o.sortie)
                m["debordement_telephone_px"] = debordement(tel, o.url + chemin, "tel_" + fichier, o.sortie)
                r["pages"][nom] = m
                for v in detail:
                    d = r["axe_detail"].setdefault(v["id"], {"impact": v["impact"], "aide": v["aide"], "pages": [], "exemples": v["exemples"],
                                                             "tolere": v["id"] in AXE_TOLERES})
                    d["pages"].append(nom)
                deborde = [f"{largeur} px" for largeur, cle in ((768, "debordement_tablette_px"), (390, "debordement_telephone_px"))
                           if m[cle] > 1 and (largeur, nom) not in DEBORDEMENTS_TOLERES]
                echec |= m["statut"] >= 400 or bool(m["erreurs_js"]) or any(i in GRAVES and v not in AXE_TOLERES for v, i, _ in m["axe"]) \
                    or bool(deborde) or bool(m["gabarit_visible"])
                print(f"[{fait}/{total} · {int(time.monotonic() - debut)} s] {role:13} {nom:28} {m['statut']} server {m['serveur_ms']:5} ms  total {m['total_ms']:5} ms  "
                      f"{m['html_ko']:4} KB ({m['html_brut_ko']} KB)  axe {m['axe']}  "
                      f"tablet {m['debordement_tablette_px']} px  phone {m['debordement_telephone_px']} px"
                      + (f"  SCROLLS at {', '.join(deborde)}" if deborde else "")
                      + (f"  JS {m['erreurs_js']}" if m["erreurs_js"] else "")
                      + (f"  TEMPLATE VISIBLE {m['gabarit_visible']}" if m["gabarit_visible"] else ""), flush=True)
            r["clavier"] = clavier(page, o.url) if role != "lecteur" else {}  # le lecteur n'a pas de page Saisie
            if role == "contributeur":
                if o.base_jetable:
                    r["parcours"] = parcours_saisie(page, o.url)
                    pc = r["parcours"]
                    echec |= bool(pc.get("erreur")) or (pc.get("fait") and pc.get("statut_apres") != "valide")
                    if pc.get("saute"):
                        non_verifie.append(f"parcours de saisie : {pc['saute']}")
                else:
                    r["parcours"] = {"fait": False, "saute": "le parcours enregistre une valeur : seulement avec --base-jetable"}
                    non_verifie.append("parcours de saisie (contributeur)")
            print(role, "keyboard", r["clavier"], r.get("parcours", ""), flush=True)
            resultats[role] = r
            enregistrer(False)
        for _, ctx, _, tab, tel in contextes:
            ctx.close()
            tab.close()
            tel.close()
        nav.close()
    apres = empreinte(o.base)
    if avant is None:
        resultats["ecritures_metier"] = {"verifie": False}
        print("business tables: not checked (add --base <SQLite file of the demo>)", flush=True)
    else:
        ecarts = {t: {"lignes": [avant[t]["lignes"], apres[t]["lignes"]]} for t in TABLES_METIER if avant[t] != apres[t]}
        resultats["ecritures_metier"] = {"verifie": True, "avant": avant, "apres": apres, "ecarts": ecarts, "base_jetable": o.base_jetable}
        print("business tables", "unchanged (rows and content)" if not ecarts else
              "modified: " + ", ".join(f"{t} ({v['lignes'][0]} → {v['lignes'][1]} rows)" for t, v in ecarts.items()), flush=True)
        echec |= bool(ecarts) and not o.base_jetable
    resultats["non_verifie"] = non_verifie
    if non_verifie:
        print("Not checked in this run:", "; ".join(non_verifie)
              + (" — run again with --disposable-base on a disposable demo (qa/disposable_demo.sh)" if not o.base_jetable else ""), flush=True)
    rouges = [c["nom"] for c in resultats["controles"] if c["etat"] == "rouge"]
    print("red checks:", ", ".join(rouges) or "none", "· blocking:", ", ".join(CONTROLES_BLOQUANTS) or "none", flush=True)
    enregistrer(True)
    print("exit code", 1 if echec else 0, flush=True)
    return 1 if echec else 0


if __name__ == "__main__":
    sys.exit(main())
