"""Découpage du site en zones de traduction (docs/translation.md) : chaque zone a son fichier de langue
(``libelles/<zone>.<langue>.json``), les préfixes de ses clés et la liste de ses fichiers (gabarits, modules Python,
scripts). Les zones sont disjointes : un fichier n'appartient qu'à une zone, une clé n'appartient qu'à une zone (par son
préfixe) ; plusieurs personnes (ou assistants) traduisent ainsi en même temps sans se gêner.

Règle : la clé d'un texte prend le préfixe de la zone du fichier qui l'affiche (un texte de ``collecte/views.py`` est
dans la zone « saisie », même s'il s'affiche sur le Tableau de bord). Les clés ``commun.*`` (boutons et mots courants) et
``choix.*`` (listes de choix des modèles : statuts, rôles…) sont dans la zone « cadre » : toutes les zones peuvent les
utiliser, seule la zone « cadre » les modifie.

``TRADUITES`` : zones entièrement traduites, dont les gabarits ne doivent plus contenir de texte français en dur
(test ``parametres/test_traduction.py``) ; chaque zone s'y ajoute quand son extraction est finie.
"""
from fnmatch import fnmatch
from pathlib import Path

# zone → (titre, préfixes des clés, fichiers : motifs relatifs à la racine du projet)
ZONES = {
    "cadre": ("Cadre commun et connexion", ("cadre.", "commun.", "choix."), (
        "templates/base.html", "templates/_*.html", "templates/registration/*.html", "templates/4*.html", "templates/5*.html",
        "collecte/templates/collecte/mon_compte.html", "collecte/templates/collecte/_supprimes.html", "collecte/templates/collecte/donnees_confidentialite.html", "collecte/templates/collecte/aide.html",
        "collecte/compte.py", "collecte/visite_guidee.py", "collecte/confidentialite.py", "referentiel/connexion.py", "parametres/contexte.py", "parametres/langues.py",
        "parametres/libelles.py", "parametres/zones_langue.py", "collecte/vues_langue.py",
    )),
    "saisie": ("Saisie (ses deux vues), panneau de saisie, fiche KPI, Cohérence, Historique", ("saisie.",), (
        "collecte/templates/collecte/saisie.html", "collecte/templates/collecte/pour_moi.html",
        "collecte/templates/collecte/aucune_campagne.html", "collecte/templates/collecte/cellule.html",
        "collecte/templates/collecte/kpi_fiche.html", "collecte/templates/collecte/_kpi_fiche.html",
        "collecte/templates/collecte/_panneau.html", "collecte/templates/collecte/_saisie_texte.html", "collecte/templates/collecte/_saisie_tableau.html", "collecte/templates/collecte/_saisie_tableau_ligne.html", "collecte/rendu_ligne.py",
        "collecte/templates/collecte/_forcage.html", "collecte/templates/collecte/forcages.html",
        "collecte/templates/collecte/_sections.html", "collecte/templates/collecte/_sections_corps.html", "collecte/templates/collecte/_vide.html",
        "collecte/templates/collecte/_pour_moi_reste.html",
        "collecte/templates/collecte/_colonnes.html", "collecte/templates/collecte/_choix_campagne.html",
        "collecte/templates/collecte/_choix_campagne_simple.html", "collecte/templates/collecte/_choix_reponse.html", "collecte/templates/collecte/choix_reponse.html",
        "collecte/templates/collecte/_choix_spoc.html", "collecte/templates/collecte/_resume.html", "collecte/templates/collecte/_filtres_saisie.html", "collecte/templates/collecte/_affichage_saisie.html", "collecte/templates/collecte/_selecteur_org.html", "collecte/templates/collecte/_selecteur_org_champ.html",
        "collecte/templates/collecte/_etat_avancement.html", "collecte/templates/collecte/_detail_agregat.html",
        "collecte/templates/collecte/_point_a_verifier.html", "collecte/templates/collecte/_ia_explication.html", "collecte/templates/collecte/_titre_campagne.html",
        "collecte/templates/collecte/_constructeur.html", "collecte/templates/collecte/coherence/*.html",
        "collecte/templates/collecte/_app.js", "collecte/templates/collecte/_app/*.js",
        "collecte/views.py", "collecte/vues_communes.py", "collecte/vues_cellule.py", "collecte/vues_referentiel_kpi.py", "collecte/saisie.py",
        "collecte/vues_coherence.py", "collecte/coherence.py",
        "collecte/contexte.py", "collecte/templatetags/collecte.py",
    )),
    "suivi": ("Tableau de bord, Relances (page), Import / Export, fichiers Excel", ("suivi.",), (
        "collecte/templates/collecte/tableau_de_bord.html", "collecte/templates/collecte/_barre.html", "collecte/templates/collecte/_entetes_barre.html",
        "collecte/templates/collecte/consolidation.html", "collecte/templates/collecte/_vues_tdb.html", "collecte/templates/collecte/_plus_orgs.html", "collecte/templates/collecte/_case_conso.html", "collecte/vues_consolidation.py",
        "collecte/templates/collecte/_restes_sans_spoc.html", "collecte/templates/collecte/relances.html",
        "collecte/templates/collecte/echanges/*.html", "collecte/templates/collecte/certificat/*.html",
        "collecte/vues_certificat.py", "collecte/certificat_cloture.py",
        "collecte/vues_relances.py", "collecte/vues_echanges.py", "collecte/exports.py", "collecte/imports.py", "collecte/imports_modele.py",
        "collecte/echange.py", "collecte/fichiers.py", "collecte/styles_excel.py",
    )),
    "admin": ("Administration et Paramètres", ("admin.",), (
        "collecte/templates/collecte/administration/*.html", "collecte/templates/collecte/_choix_referentiel.html",
        "parametres/templates/parametres/identite.html", "parametres/templates/parametres/_identite.html", "parametres/templates/parametres/_apercu_identite.html",
        "parametres/templates/parametres/_couleur.html", "parametres/templates/parametres/_couleur_viz.html",
        "parametres/templates/parametres/langues.html", "parametres/templates/parametres/ia.html", "parametres/templates/parametres/traductions.html",
        "parametres/templates/parametres/traductions_import.html",
        "parametres/templates/parametres/_menu_fichier_traductions.html",
        "parametres/templates/parametres/niveaux.html", "parametres/templates/parametres/seuils.html",
        "parametres/templates/parametres/_champ_seuil.html", "parametres/templates/parametres/hebergement.html",
        "parametres/templates/parametres/sante_installation.html", "parametres/sante_installation.py",
        "parametres/templates/parametres/restauration.html", "parametres/templates/parametres/visualisation.html",
        "parametres/templates/parametres/_unites.html", "parametres/templates/parametres/_sous_nav.html",
        "collecte/administration.py", "collecte/vues_connexions.py", "collecte/a_traiter.py", "collecte/configuration.py", "collecte/reglages.py", "collecte/reprise.py",
        "collecte/vues_reprise.py", "collecte/mise_a_jour.py",
        "parametres/views.py", "parametres/vues_hebergement.py", "parametres/vues_langues.py",
        "parametres/sauvegardes.py", "parametres/couleurs.py", "parametres/traductions.py",
        "parametres/traductions_fichier.py", "parametres/niveaux.py", "parametres/vues_ia.py", "parametres/ia.py",
    )),
    "referentiels": ("Assistant de mise en place, référentiels, bibliothèque, installation, paquets", ("referentiels.",), (
        "parametres/templates/parametres/mise_en_place/*.html", "parametres/templates/parametres/referentiel*.html",
        "parametres/templates/parametres/installer_*.html", "parametres/templates/parametres/_installer_*.html",
        "parametres/templates/parametres/_etapes_installation.html", "parametres/templates/parametres/paquet_apercu.html",
        "parametres/templates/parametres/_trois_portes.html", "parametres/templates/parametres/_contenu_*.html",
        "parametres/templates/parametres/_entete_referentiel.html", "parametres/templates/parametres/_sources_compo.html",
        "parametres/templates/parametres/_etapes_creation.html", "parametres/templates/parametres/_script_cocher.html",
        "collecte/templates/collecte/referentiel.html",
        "parametres/mise_en_place.py", "parametres/vues_installation.py", "parametres/vues_paquets.py",
        "parametres/vues_referentiels.py", "parametres/referentiel.py", "collecte/configuration_referentiels.py",
        "collecte/paquets/*.py", "referentiel/composition.py", "referentiel/echange.py",
    )),
    "messages": ("E-mails (relances) et messages Python communs (modèles, calculs, formules, droits)", ("messages.",), (
        "collecte/relances.py", "collecte/models.py", "referentiel/models.py", "parametres/models.py",
        "collecte/calcul.py", "collecte/periodes.py", "collecte/signals.py", "collecte/lecture_seule.py",
        "collecte/reponses_script.py", "collecte/corbeille.py", "referentiel/formule.py", "referentiel/plans.py", "referentiel/auth.py",
    )),
    "visualisation": ("Visualisation (déjà en français et en anglais)", ("visu.", "format."), (
        "collecte/templates/collecte/visualisation/*.html", "static/js/visualisation.js",
        "collecte/visuels/*.py", "collecte/vues_visu.py", "collecte/vues_visualisation.py", "collecte/visualisation.py",
        "collecte/visuels_excel.py",
    )),
    "mcp": ("Assistants (serveur MCP) : carte de Mon compte, Paramètres › Assistants, messages des outils", ("mcp.",), (
        "serveur_mcp/templates/serveur_mcp/*.html", "serveur_mcp/*.py",
    )),
    "espaces": ("Espaces (sélecteur de la barre du haut, page Espaces, création, pas d'accès)", ("espaces.",), (
        "espaces/templates/espaces/*.html",
        "espaces/vues.py", "espaces/creation.py", "espaces/intergiciels.py", "espaces/contexte_gabarits.py",
        "espaces/comptes.py",
    )),
}

# zones entièrement traduites : leurs gabarits ne contiennent plus de texte français en dur (test)
TRADUITES = ["cadre", "visualisation", "saisie", "suivi", "admin", "referentiels", "messages", "espaces", "mcp"]


def prefixes(zone):
    return ZONES[zone][1]


def zones_du_fichier(chemin):
    """Zones dont un motif couvre ce fichier (chemin relatif à la racine du projet)."""
    chemin = str(chemin).replace("\\", "/")
    return [z for z, (_, _, motifs) in ZONES.items() if any(fnmatch(chemin, m) for m in motifs)]


def fichiers_de(zone, base):
    """Fichiers existants d'une zone (chemins absolus), triés."""
    base = Path(base)
    return sorted({p for m in ZONES[zone][2] for p in base.glob(m) if p.is_file()})
