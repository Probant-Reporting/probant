"""Paramètres de l'installation disponibles dans toutes les pages (nom, logo, couleurs, niveaux, types de saisie)."""
from . import couleurs as CO
from . import niveaux as N
from . import referentiel as PR
from .models import Instance

_EMPREINTE = {}  # chemin → (date de modification, empreinte)


def version_css(fichier="css/outil.css"):
    """Version de la feuille de style dans son adresse (?v=) : la version de l'outil et une empreinte du fichier, pour que
    le navigateur recharge la feuille dès qu'elle change (après un git pull ou une mise à jour), sans vider son cache."""
    import hashlib
    import os

    from django.conf import settings
    from django.contrib.staticfiles import finders

    chemin = finders.find(fichier)
    if not chemin:
        return settings.VERSION
    date = os.path.getmtime(chemin)
    if _EMPREINTE.get(chemin, (None,))[0] != date:
        with open(chemin, "rb") as f:
            _EMPREINTE[chemin] = (date, hashlib.sha256(f.read()).hexdigest()[:10])
    return f"{settings.VERSION}-{_EMPREINTE[chemin][1]}"


def langues_interface():
    """[(code, nom de la langue dans cette langue)] du sélecteur de la barre du haut : FR / EN / ES."""
    from . import langues as L
    from . import libelles as LB

    return [(c, LB.libelle("cadre.langue.nom", c)) for c in L.langues_interface()]


def apparence(request):
    """Apparence choisie sur cet appareil (Mon compte) : « systeme » (par défaut), « clair » ou « sombre »."""
    valeur = getattr(request, "COOKIES", {}).get(CO.COOKIE_APPARENCE, "")
    return valeur if valeur in CO.APPARENCES else "systeme"


def instance(request):
    from . import langues as L

    i = Instance.courante()
    g = i.gamme()
    niveaux = N.tous()
    from referentiel import plans

    refs = list(plans.Referentiel.objects.all())
    session = getattr(request, "session", None)
    from django.conf import settings

    from collecte.fichiers import mo

    gs = CO.gamme_sombre(g)
    sombre = CO.bloc_sombre(CO.css(gs) + CO.css_graphiques_sombre(i.couleurs_graphiques, gs["surface"]),
                            N.regles_sombres(gs["surface"], niveaux) + PR.regles_sombres(gs["surface"])
                            + plans.regles_sombres(gs["surface"], refs))
    return {"instance": i, "version_outil": settings.VERSION, "version_css": version_css(), "taille_max_preuve": mo(settings.PREUVE_TAILLE_MAX),
            "taille_max_import": mo(settings.IMPORT_TAILLE_MAX), "couleur_icone": g["principale-vive"].lstrip("#"),
            # couleurs de la marque, puis celles des graphiques si l'admin les a réglées (sinon celles d'outil.css)
            "couleurs_css": CO.css(g) + CO.css_graphiques(i.couleurs_graphiques),
            # apparence sombre (système en sombre, ou choix « Sombre » de Mon compte) et choix de l'appareil
            "sombre_css": sombre, "apparence": apparence(request),
            "niveaux_arbre": niveaux, "niveaux_par_code": {n.code: n for n in niveaux}, "niveaux_css": N.css(niveaux),
            "types_css": PR.css(), "referentiels_css": plans.css(refs), "referentiels_filtre": [r for r in refs if r.actif],
            "referentiel_code": session.get("referentiel", "") if session is not None else "",
            "langue_interface": L.interface(), "langues_interface": langues_interface(),
            "ia_permise": settings.IA_PRISE_PERMISE}  # onglet Paramètres › Assistant IA (coupé par l'IT : caché)
