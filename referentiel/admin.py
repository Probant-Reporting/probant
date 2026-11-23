"""Mode expert (/admin/) : consultation des tables brutes, en lecture seule. Tout se modifie
dans l'outil, avec ses contrôles (droits, campagnes clôturées figées, formules) et son journal."""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import Group
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe

from .models import KPI, Attribution, Description, ElementReferentiel, KPIFormule, Organisation, OrgAlias, Referentiel, Theme, Utilisateur

admin.site.site_header = "Probant – mode expert (lecture seule)"
admin.site.site_title = "Probant"
admin.site.index_title = "Tables (consultation seulement)"

if admin.site.is_registered(Group):  # les groupes de Django ne servent pas : les rôles sont portés par les comptes
    admin.site.unregister(Group)


class LectureSeule:
    """Consultable seulement : ni ajout, ni modification, ni suppression, ni action en masse."""

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_actions(self, request):
        return {}


# ---------------------------------------------------------------- KPI
class DescriptionInline(LectureSeule, admin.StackedInline):
    model = Description
    extra = 0


@admin.register(KPI)
class KPIAdmin(LectureSeule, admin.ModelAdmin):
    list_display = ("code", "nom_court", "type_saisie", "granularite", "methode_agregation", "unite",
                    "preuve_obligatoire", "confidentialite", "ordre", "actif")
    list_filter = ("actif", "type_saisie", "type_reponse", "granularite", "methode_agregation", "elements__referentiel", "equipe_responsable",
                   "preuve_obligatoire", "confidentialite")
    search_fields = ("code", "libelle", "formule")
    inlines = [DescriptionInline]
    list_per_page = 100
    readonly_fields = ("sources_lisibles", "utilise_par_lisible", "date_maj")
    fieldsets = (
        ("Identification", {"fields": ("code", "libelle", "traductions", "ordre", "actif", "equipe_responsable")}),
        ("Saisie et calcul", {"fields": ("type_saisie", "type_reponse", "unite", "decimales", "granularite", "methode_agregation",
                                         "formule", "sources_lisibles", "utilise_par_lisible")}),
        ("Contrôles", {"fields": ("preuve_obligatoire", "confidentialite")}),
        ("Champs personnalisés", {"fields": ("champs", "date_maj")}),
    )
    @admin.display(description="Nom", ordering="libelle")
    def nom_court(self, obj):
        n = obj.nom
        return n if len(n) < 70 else n[:67] + "…"

    @admin.display(description="KPI sources")
    def sources_lisibles(self, obj):
        liens = obj.sources.select_related("kpi_source")
        return format_html_join(mark_safe("<br>"), "[{}{}] {}", (
            (l.kpi_source_id, "" if l.decalage == "N" else "@" + l.decalage, l.kpi_source.nom) for l in liens)) or "—"

    @admin.display(description="Utilisé par")
    def utilise_par_lisible(self, obj):
        liens = KPIFormule.objects.filter(kpi_source=obj).select_related("kpi_calcule")
        return format_html_join(mark_safe("<br>"), "[{}] {}", ((l.kpi_calcule_id, l.kpi_calcule.nom) for l in liens)) or "—"


# ---------------------------------------------------------------- organisations
class OrgAliasInline(LectureSeule, admin.TabularInline):
    model = OrgAlias
    extra = 0


@admin.register(Organisation)
class OrganisationAdmin(LectureSeule, admin.ModelAdmin):
    list_display = ("arbre", "niveau", "type_site", "rang", "actif")
    list_filter = ("niveau", "actif", "type_site")
    search_fields = ("nom", "alias__libelle")
    inlines = [OrgAliasInline]

    @admin.display(description="Organisation")
    def arbre(self, obj):
        prof = obj.niveau.rang - 1
        return format_html("{}{}", " " * prof, obj.nom)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("parent", "niveau")


# ---------------------------------------------------------------- comptes et attributions
@admin.register(Utilisateur)
class UtilisateurAdmin(LectureSeule, UserAdmin):
    list_display = ("email", "first_name", "last_name", "role", "equipe", "is_active")
    list_filter = ("role", "equipe", "is_active")
    search_fields = ("email", "first_name", "last_name")
    fieldsets = UserAdmin.fieldsets + (("Probant", {"fields": ("role", "equipe", "langue")}),)


@admin.register(Attribution)
class AttributionAdmin(LectureSeule, admin.ModelAdmin):
    list_display = ("kpi", "organisation", "utilisateur", "role")
    list_filter = ("role", "organisation__niveau", "organisation", "kpi__elements__referentiel")
    search_fields = ("kpi__code", "kpi__libelle", "utilisateur__email", "organisation__nom")
    autocomplete_fields = ("kpi", "utilisateur")


@admin.register(Referentiel)
class ReferentielAdmin(LectureSeule, admin.ModelAdmin):
    list_display = ("code", "nom", "ordre", "actif")


@admin.register(Theme)
class ThemeAdmin(LectureSeule, admin.ModelAdmin):
    list_display = ("code", "nom", "referentiel", "parent", "ordre")
    list_filter = ("referentiel",)
    search_fields = ("code", "nom")


@admin.register(ElementReferentiel)
class ElementReferentielAdmin(LectureSeule, admin.ModelAdmin):
    list_display = ("kpi", "referentiel", "theme", "ordre", "obligatoire")
    list_filter = ("referentiel", "obligatoire")
    search_fields = ("kpi__code", "kpi__libelle")
    raw_id_fields = ("kpi",)
