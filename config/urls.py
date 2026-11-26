"""URL de l'outil : page contributeur à la racine, back-office sous /admin/."""
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from collecte.vues_langue import changer_langue
from connexion_entreprise import flux as connexion_entreprise
from espaces.vues import Connexion

urlpatterns = [
    path("admin/", admin.site.urls),
    path("connexion/", Connexion.as_view(), name="login"),
    path("deconnexion/", auth_views.LogoutView.as_view(), name="logout"),
    # compte d'entreprise (OpenID Connect) : aller vers le fournisseur, retour du fournisseur (docs/single_sign_on.md)
    path("connexion/entreprise/", connexion_entreprise.debut, name="entreprise_debut"),
    path("connexion/entreprise/retour/", connexion_entreprise.retour, name="entreprise_retour"),
    path("langue/", changer_langue, name="langue"),  # langue de l'interface (barre du haut), aussi sans être connecté
    path("", include("espaces.urls")),
    path("", include("parametres.urls")),
    path("", include("collecte.urls")),
    path("", include("serveur_mcp.urls")),  # /mcp/ (assistants) et Paramètres › Assistants
    path("", include("connexion_entreprise.urls")),  # Paramètres › Connexion d'entreprise (gestionnaires des espaces)
]

handler403 = "collecte.reponses_script.refus"  # motif du refus en JSON pour le script des pages
