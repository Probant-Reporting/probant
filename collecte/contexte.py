"""« Je réponds à » : référentiel et période choisis, affichés dans la barre du haut de toutes les pages."""
from .models import Campagne


def choix_reponse(request):
    user = getattr(request, "user", None)
    session = getattr(request, "session", None)
    if user is None or not user.is_authenticated or session is None:
        return {}
    from . import saisie as S

    cle = session.get("campagne")
    c = Campagne.objects.select_related("referentiel", "periode").filter(pk=cle).first() if str(cle).isascii() and str(cle).isdigit() and len(str(cle)) < 19 else None
    if c is None:
        c = S.campagne_par_defaut(user)
        if c is not None:
            session["campagne"] = c.pk
    from .views import VUE_FLUX, vue_saisie

    # onglet Saisie : il rouvre la dernière vue choisie (une organisation à la fois, ou tout ce qui m'est attribué)
    return {"campagne_choisie": c, "saisie_flux": vue_saisie(user, session) == VUE_FLUX}
