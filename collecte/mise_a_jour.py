"""Travaux à faire une seule fois après une mise à jour de l'outil (``referentiel.TravailApresMiseAJour``).

Une migration ne doit pas appeler le moteur de calcul : lors d'une montée de plusieurs versions d'un coup, son code (celui
d'aujourd'hui) ne correspondrait plus à la base du moment. Elle pose donc seulement le travail ; il est fait ici, à la fin
de « migrate » (démarrage de l'image Docker, Clever Cloud, version portable, Codespace), avec le code installé et une base
entièrement à jour, puis effacé. Une base pas encore à jour (migration partielle) le garde pour le prochain « migrate » ;
un travail qui échoue reste posé et sera refait au prochain démarrage (message dans le journal du serveur).
"""
import logging

journal = logging.getLogger("reporting.mise_a_jour")


def _recalcul():
    """Calculs et alertes des campagnes non clôturées refaits avec les règles de la version installée. Renvoie False s'il
    n'y avait rien à refaire (aucune campagne non clôturée, ex. une installation neuve) : rien n'est alors annoncé."""
    from .calcul import recalculer_en_cours
    from .models import Campagne

    if not Campagne.objects.exclude(statut=Campagne.Statut.CLOTUREE).exists():
        return False
    recalculer_en_cours()
    return True


def _geler_periodes():
    """Périmètre des exercices déjà clos noté une fois (``calcul.geler_periodes_closes``)."""
    from .calcul import geler_periodes_closes

    return geler_periodes_closes() > 0


def _noter_arbres():
    """Arbre des organisations des exercices déjà clos noté une fois, celui du jour de la mise à jour (``calcul.noter_arbres_clos``) ; rien n'est recalculé."""
    from .calcul import noter_arbres_clos

    return noter_arbres_clos() > 0


def _noter_figes_partiels():
    """KPI des campagnes déjà clôturées à côté d'une campagne ouverte de la même période figés une fois, avec l'arbre du
    jour de la mise à jour (règle « Figer ses chiffres », ``calcul.noter_figes_partiels_existants``) ;
    rien n'est recalculé."""
    from .calcul import noter_figes_partiels_existants

    return noter_figes_partiels_existants() > 0


def _corriger_unites():
    """Unité des KPI mal rangée à l'installation d'un modèle de la bibliothèque (rapprochement fautif d'avant la mise à jour), corrigée pour les seuls cas prouvés (``unites_mal_rapprochees.corriger``) ; aucune valeur changée."""
    from .unites_mal_rapprochees import corriger

    return corriger() > 0


TRAVAUX = {"recalcul": _recalcul, "geler_perimetres": _geler_periodes, "noter_arbres": _noter_arbres,
           "corriger_unites": _corriger_unites, "noter_figes_partiels": _noter_figes_partiels}

# motifs posés par les migrations (en français, dans la base) : version anglaise pour le journal du serveur (IT)
MOTIFS_EN = {
    "KPI des campagnes clôturées à côté d'une campagne ouverte figés (arbre du jour de la mise à jour).":
        "KPIs of the campaigns closed next to an open campaign frozen (tree on the day of the update).",
    "unité des KPI mal rangée à l'installation d'un modèle de la bibliothèque corrigée (aucune valeur changée).":
        "unit of the KPIs put in the wrong unit when a library template was installed corrected (no value changed).",
    "arbre des organisations des exercices clos noté (celui du jour de la mise à jour).":
        "organisation tree of the closed years recorded (the tree on the day of the update).",
    "périmètre des exercices clos noté (un KPI ajouté depuis n'y crée plus de case).":
        "scope of the closed years recorded (a KPI added since no longer creates a cell in them).",
    "calculs des campagnes non clôturées refaits (une source N/A compte désormais comme 0 dans les sommes : case de la "
    "fiche KPI).": "calculations of the campaigns not yet closed redone (an N/A source now counts as 0 in sums: box on "
                   "the KPI sheet).",
    "calculs des campagnes non clôturées refaits (un mois ne calcule plus que les KPI du périmètre de ses campagnes : "
    "cases sans objet retirées).": "calculations of the campaigns not yet closed redone (a month now calculates only "
                                   "the KPIs in the scope of its campaigns: cells with no purpose removed).",
    "calculs des campagnes non clôturées refaits (une année, un semestre ou un trimestre ne calcule plus que les KPI du "
    "périmètre de ses campagnes : cases sans objet retirées).": "calculations of the campaigns not yet closed redone (a "
                                                                "year, half-year or quarter now calculates only the KPIs in "
                                                                "the scope of its campaigns: cells with no purpose removed).",
    "calculs des campagnes non clôturées refaits (cumul des mois : seulement les mois où l'organisation est ouverte "
    "et le KPI demandé ; [X@N-1] d'une organisation pas ouverte : source manquante).": "calculations of the campaigns "
    "not yet closed redone (cumulation of the months: only the months in which the organisation is open and the KPI "
    "requested; [X@N-1] of an organisation not open: missing source).",
}


def base_a_jour(connexion):
    from django.db.migrations.executor import MigrationExecutor

    executeur = MigrationExecutor(connexion)
    return not executeur.migration_plan(executeur.loader.graph.leaf_nodes())


def faire_les_travaux(using="default", stdout=None, verbosity=1):
    """Fait les travaux posés, dans l'ordre de leur pose, puis les efface. Renvoie les codes faits."""
    from django.db import connections

    from parametres import langues as L
    from referentiel.models import TravailApresMiseAJour

    connexion = connections[using]
    if TravailApresMiseAJour._meta.db_table not in connexion.introspection.table_names():
        return []  # table pas encore créée (migration partielle)
    travaux = list(TravailApresMiseAJour.objects.using(using).order_by("date", "code"))
    if not travaux or not base_a_jour(connexion):
        return []
    faits = []
    for t in travaux:
        code, texte = t.code, MOTIFS_EN.get(t.motif, t.motif or t.code)
        faire = TRAVAUX.get(code)
        if faire is None:  # travail d'une version plus récente : laissé tel quel
            continue
        try:
            # ``startup`` travaille avec l'interface en anglais (messages pour l'IT) : le travail, lui, écrit dans la base
            # (texte des alertes) et doit le faire dans la langue de l'installation
            with L.activer_interface(None):
                utile = faire()
        except Exception:
            journal.exception("Post-update task \"%s\" failed (%s): it will be done again at the next startup.", code, texte)
            continue
        t.delete()
        faits.append(code)
        if utile is False:  # rien à refaire : pas de message
            continue
        if stdout is not None and verbosity:
            stdout.write(f"After the update: {texte}")
        else:  # démarrage de l'image (migrate silencieux) : dans le journal du serveur
            journal.info("After the update: %s", texte)
    return faits


def apres_migrate(sender, using="default", stdout=None, verbosity=1, **kwargs):
    """Signal ``post_migrate`` (une fois par « migrate », pour l'application collecte)."""
    faire_les_travaux(using, stdout, verbosity)
