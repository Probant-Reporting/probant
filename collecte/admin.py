"""Mode expert : réponses, preuves, campagnes, périodes et journal consultables seulement (voir referentiel/admin.py)."""
from django.contrib import admin

from referentiel.admin import LectureSeule

from .models import Campagne, Journal, Periode, Preuve, Reponse


@admin.register(Periode)
class PeriodeAdmin(LectureSeule, admin.ModelAdmin):
    list_display = ("libelle", "type", "debut", "fin")
    list_filter = ("type",)


@admin.register(Campagne)
class CampagneAdmin(LectureSeule, admin.ModelAdmin):
    list_display = ("__str__", "referentiel", "periode", "exercice", "statut", "date_ouverture", "date_fin_saisie", "seuil_ecart")
    list_filter = ("referentiel", "statut", "periode__type")


class PreuveInline(LectureSeule, admin.TabularInline):
    model = Preuve
    extra = 0
    readonly_fields = ("nom_fichier", "taille", "depose_par", "date_depot")


@admin.register(Reponse)
class ReponseAdmin(LectureSeule, admin.ModelAdmin):
    list_display = ("kpi", "organisation", "periode", "valeur", "non_applicable", "statut", "origine", "date_maj")
    list_filter = ("periode__type", "statut", "origine", "organisation__niveau", "organisation", "kpi__elements__referentiel")
    search_fields = ("kpi__code", "kpi__libelle", "organisation__nom")
    raw_id_fields = ("kpi",)
    readonly_fields = ("message_calcul", "date_maj")
    inlines = [PreuveInline]
    list_select_related = ("kpi", "organisation", "periode")


@admin.register(Journal)
class JournalAdmin(LectureSeule, admin.ModelAdmin):
    list_display = ("date", "utilisateur", "action", "objet", "objet_id", "champ", "avant", "apres")
    list_filter = ("action", "objet")
