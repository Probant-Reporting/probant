from django.urls import path
from django.views.generic import RedirectView

from . import administration as A
from . import attributions_lecture_seule as ALS
from . import compte
from . import vues_certificat, vues_connexions
from . import aide as AI
from . import confidentialite as CF
from . import vues_coherence as CO
from . import vues_consolidation as VC
from . import conservation as CV
from . import corbeille as CB
from . import vues_echanges as EC
from . import vues_export_officiel as EO
from . import vues_forcage as VF
from . import vues_visualisation as VI
from . import vues_visu as VV
from . import vues_reprise as RE
from . import vues_ia as IA
from . import views
from . import vues_cellule
from . import vues_referentiel_kpi
from . import vues_relances

app_name = "collecte"

urlpatterns = [
    path("", views.accueil, name="accueil"),
    path("saisie/", views.saisie, name="saisie"),
    path("je-reponds-a/", views.choix_reponse, name="choix_reponse"),
    path("je-reponds-a/<int:pk>/", views.choisir_campagne, name="choisir_campagne"),
    path("pour-moi/", views.pour_moi, name="pour_moi"),
    path("valeurs-forcees/", VF.forcages, name="forcages"),
    path("valeurs-forcees/importee/", VF.importee, name="forcage_importee"),
    path("tableau-de-bord/", views.tableau_de_bord, name="tableau_de_bord"),
    path("visualisation/", VI.accueil, name="visu"),
    path("visualisation/theme/<int:pk>/", VI.theme, name="visu_theme"),
    path("visualisation/kpi/<str:code>/", VI.kpi, name="visu_kpi"),
    # anciennes adresses des tableaux, devenus des vues (migration 0023) : redirigées
    path("visualisation/tableaux/nouveau/", VI.tableau_nouveau, name="visu_tableau_nouveau"),
    path("visualisation/tableaux/<int:pk>/", VI.tableau, name="visu_tableau"),
    path("visualisation/tableaux/<int:pk>/modifier/", VI.tableau_modifier, name="visu_tableau_modifier"),
    # Visualisation v2 : vues (page et points d'accès JSON internes à la page)
    path("visualisation/vues/<int:pk>/", VV.page_vue, name="visu_vue"),
    path("visualisation/vues/nouvelle/", VV.page_nouvelle, name="visu_vue_nouvelle"),
    path("visualisation/donnees/catalogue/", VV.catalogue, name="visu_catalogue"),
    path("visualisation/vues/<int:pk>/donnees/", VV.vue_donnees, name="visu_vue_donnees"),
    path("visualisation/donnees/", VV.donnees, name="visu_donnees"),
    path("visualisation/vues/", VV.vue_creer, name="visu_vue_creer"),
    path("visualisation/vues/<int:pk>/enregistrer/", VV.vue_enregistrer, name="visu_vue_enregistrer"),
    path("visualisation/vues/<int:pk>/dupliquer/", VV.vue_dupliquer, name="visu_vue_dupliquer"),
    path("visualisation/vues/<int:pk>/supprimer/", VV.vue_supprimer, name="visu_vue_supprimer"),
    path("visualisation/vues/<int:pk>/partage/", VV.vue_partage, name="visu_vue_partage"),
    path("visualisation/vues/ordre/", VV.vues_ordre, name="visu_vues_ordre"),
    path("visualisation/vues/<int:pk>/preferee/", VV.vue_preferee, name="visu_vue_preferee"),
    path("visualisation/vues/<int:pk>/excel/", VV.vue_excel, name="visu_vue_excel"),
    path("visualisation/excel/", VV.excel, name="visu_excel"),
    path("tableau-de-bord/consolidation/", VC.consolidation, name="consolidation"),
    path("tableau-de-bord/consolidation/excel/", VC.consolidation_excel, name="consolidation_excel"),
    path("tableau-de-bord/relances/", vues_relances.relances, name="relances"),
    path("historique/", A.journal, name="historique"),  # le journal, pour l'auditeur
    path("historique/connexions/", vues_connexions.historique, name="historique_connexions"),  # pour l'auditeur
    path("saisie/<int:campagne_id>/<str:kpi_id>/<int:org_id>/", vues_cellule.cellule, name="cellule"),
    path("saisie/apercu-texte/", vues_cellule.apercu_texte, name="apercu_texte"),
    path("preuve/<int:pk>/", vues_cellule.preuve, name="preuve"),
    path("attributions/", views.attribuer, name="attribuer"),
    path("referentiel/", vues_referentiel_kpi.referentiel, name="referentiel"),
    path("referentiel/kpis.json", vues_referentiel_kpi.referentiel_kpis_json, name="referentiel_kpis_json"),
    path("referentiel/kpi/nouveau/", vues_referentiel_kpi.referentiel_kpi, name="referentiel_kpi_nouveau"),
    path("referentiel/kpi/<str:kpi_id>/", vues_referentiel_kpi.referentiel_kpi, name="referentiel_kpi"),
    path("corbeille/<str:type_>/<int:pk>/restaurer/", CB.restaurer, name="corbeille_restaurer"),
    path("import-export/", EC.accueil, name="echanges"),
    path("import-export/exporter/", EC.exporter, name="echanges_exporter"),
    path("import-export/exporter/resume/", EC.resume_export, name="echanges_resume"),
    path("import-export/selections/", RedirectView.as_view(pattern_name="collecte:echanges_listes_page")),  # ancien onglet
    path("import-export/listes-kpi/", EC.page_listes, name="echanges_listes_page"),
    path("import-export/formats-officiels/", EO.export_officiel, name="export_officiel"),
    path("import-export/listes/", EC.listes_kpi, name="echanges_listes"),
    # anciennes adresses de la configuration et de la reprise (réglages de l'admin, désormais dans Administration)
    path("import-export/reprise/", RedirectView.as_view(pattern_name="collecte:admin_reprise", query_string=True)),
    path("import-export/reglages/<int:pk>/supprimer/", EC.supprimer_reglage, name="echanges_supprimer_reglage"),
    path("import-export/modeles/ordre/", EC.ordre_modeles, name="echanges_ordre_modeles"),
    path("import-export/modeles/restaurer/", EC.restaurer_modeles, name="echanges_restaurer_modeles"),
    path("import-export/importer/", EC.importer, name="echanges_importer"),
    path("import-export/importer/rejets/", EC.rejets, name="echanges_rejets"),
    path("import-export/importer/tache/<int:pk>/", EC.tache_etat, name="echanges_tache_etat"),
    path("import-export/importer/tache/<int:pk>/arreter/", EC.tache_arreter, name="echanges_tache_arreter"),
    path("import-export/modele/", EC.modele, name="echanges_modele"),
    path("import-export/exports/<int:pk>/etat/", EC.export_etat, name="echanges_export_etat"),
    path("import-export/exports/<int:pk>/fichier/", EC.export_fichier, name="echanges_export_fichier"),
    path("import-export/configuration/", RedirectView.as_view(pattern_name="collecte:admin_fichiers", query_string=True)),
    path("coherence/", CO.coherence, name="coherence"),
    path("coherence/alerte/<int:pk>/", CO.alerte, name="alerte"),
    path("coherence/alerte/<int:pk>/ia/", IA.alerte_ia, name="alerte_ia"),
    path("coherence/regles/", CO.regles, name="regles"),
    path("coherence/regles/nouvelle/", CO.regle, name="regle_nouvelle"),
    path("coherence/regles/<int:pk>/", CO.regle, name="regle"),
    path("coherence/regles/<int:pk>/statut/", CO.regle_basculer, name="regle_basculer"),
    path("mon-compte/", compte.mon_compte, name="mon_compte"),
    path("aide/", AI.page, name="aide"),  # guide du rôle de la personne (lien « Aide » de la barre du haut)
    path("aide/images/<str:langue>/<str:nom>", AI.image, name="aide_image"),
    path("aide/<str:guide>/", AI.page, name="aide_guide"),
    path("confidentialite/", CF.page, name="confidentialite"),  # Données et confidentialité, aussi sans être connecté
    path("administration/", A.accueil, name="admin_accueil"),
    path("administration/fichiers/", EC.configuration, name="admin_fichiers"),
    path("administration/fichiers/reprise/", RE.reprise, name="admin_reprise"),
    path("administration/fichiers/reprise/ia/", IA.reprise_ia, name="admin_reprise_ia"),
    path("administration/campagnes/", A.campagnes, name="admin_campagnes"),
    path("administration/campagnes/nouvelle/", A.campagne, name="admin_campagne_nouvelle"),
    path("administration/campagnes/<int:pk>/", A.campagne, name="admin_campagne"),
    path("certificat-de-cloture/<int:pk>/", vues_certificat.certificat, name="certificat_cloture"),  # administrateur et auditeur
    path("administration/organisations/", A.organisations, name="admin_organisations"),
    path("administration/organisations/plusieurs/", A.organisations_plusieurs, name="admin_organisations_plusieurs"),
    path("administration/organisations/nouvelle/", A.organisation, name="admin_organisation_nouvelle"),
    path("administration/organisations/<int:org_id>/", A.organisation, name="admin_organisation"),
    path("administration/comptes/", A.comptes, name="admin_comptes"),
    path("administration/comptes/plusieurs/", A.comptes_plusieurs, name="admin_comptes_plusieurs"),
    path("administration/comptes/nouveau/", A.compte, name="admin_compte_nouveau"),
    path("administration/comptes/connexions/", vues_connexions.historique, name="admin_connexions"),
    path("administration/comptes/<int:user_id>/", A.compte, name="admin_compte"),
    path("administration/journal/", A.journal, name="admin_journal"),
    path("administration/journal/supprimes/", CB.tous_supprimes, name="admin_supprimes"),  # Récemment supprimés (tous)
    path("administration/preuves/", CV.page, name="admin_preuves"),  # Preuves à supprimer (KPI sensibles)
    path("administration/formules/", A.formules, name="admin_formules"),
    path("administration/attributions/", A.attributions, name="admin_attributions"),
    path("administration/attributions/remplacer/", A.remplacer_personne, name="admin_remplacer"),
    # comptes en lecture seule qui ont encore des attributions : les retirer
    path("administration/attributions/lecture-seule/", ALS.page, name="admin_attributions_lecture_seule"),
]
