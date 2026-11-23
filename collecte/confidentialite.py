"""Page « Données et confidentialité » : les données personnelles que l'outil garde, pourquoi, combien de temps, qui
les voit, et à qui demander l'accès, la correction ou la suppression.

La page est écrite à partir des réglages réels de l'installation (sauvegardes gardées et leur fréquence, durée des
sessions, délai de la corbeille, blocage de la connexion, résultats gardés du contrôle nocturne, contact de Paramètres › Identité) : elle reste
vraie quand un réglage change. L'administrateur y ajoute le texte de l'entreprise (responsable du traitement, DPO), en
Markdown (``Instance.texte_confidentialite``, Paramètres › Identité), rendu sans danger par ``collecte/markdown.py``.

Lisible par toute personne connectée (lecteur et auditeur compris : la page n'écrit rien) et depuis la page de
connexion, sans compte.
"""
import math

from django.conf import settings
from django.shortcuts import render
from django.views.decorators.http import require_GET

from parametres.libelles import libelle
from parametres.models import Instance

HEURES = {"6h": 6, "12h": 12, "jour": 24, "semaine": 24 * 7}  # intervalle de la sauvegarde automatique


def duree_sauvegardes(instance):
    """Phrase « combien de temps » des sauvegardes : nombre gardé, fréquence et, en sauvegarde automatique, l'ordre de
    grandeur en jours (archives gardées × intervalle)."""
    n = max(instance.sauvegarde_conserver, 1)  # la rotation garde toujours au moins la dernière (parametres/sauvegardes.py)
    if not instance.sauvegarde_auto or instance.sauvegarde_frequence not in HEURES:
        return libelle("cadre.donnees.sauvegardes.duree_manuelle", n=n)
    jours = max(math.ceil(n * HEURES[instance.sauvegarde_frequence] / 24), 1)
    return libelle(f"cadre.donnees.sauvegardes.duree_{instance.sauvegarde_frequence}", n=jours, nombre=n)


def lignes(instance):
    """[(clé de la ligne, titre, contenu, pourquoi, durée, qui)] : une ligne par donnée gardée."""
    from referentiel import connexion as CX

    from .controle_donnees import GARDES

    minutes = CX.DUREE // 60
    heures = max(settings.SESSION_COOKIE_AGE // 3600, 1)
    sortie = []
    # corbeille : délai réglé dans Paramètres › Hébergement (Instance.corbeille_jours) ; sessions terminées effacées
    # chaque nuit (collecte/controle_donnees.py, taches_nocturnes)
    for cle, valeurs_duree in (("compte", {}), ("mot_de_passe", {}), ("valeurs", {}), ("historique", {}),
                               ("preuves", {}), ("corbeille", {"n": instance.corbeille_jours}), ("relances", {}),
                               ("connexion", {"minutes": minutes}), ("historique_connexions", {"n": instance.connexions_jours}),
                               ("sessions", {"heures": heures}), ("sauvegardes", None), ("controle", {"nombre": GARDES})):
        base = f"cadre.donnees.{cle}."
        contenu = libelle(base + "contenu", essais=CX.ESSAIS_MAX, minutes=minutes) if cle == "connexion" else libelle(base + "contenu")
        duree = duree_sauvegardes(instance) if valeurs_duree is None else libelle(base + "duree", **valeurs_duree)
        if cle == "preuves" and instance.preuves_sensibles_mois:  # KPI sensibles : durée réglée (collecte/conservation.py)
            duree += " " + libelle("cadre.donnees.preuves.duree_sensibles", n=instance.preuves_sensibles_mois)
        sortie.append((cle, libelle(base + "titre"), contenu, libelle(base + "pourquoi"), duree, libelle(base + "qui")))
    return sortie


@require_GET
def page(request):
    i = Instance.courante()
    return render(request, "collecte/donnees_confidentialite.html", {
        "lignes": lignes(i), "texte_entreprise": i.texte_confidentialite.strip(), "page": "confidentialite",
    })
