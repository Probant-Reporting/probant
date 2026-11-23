"""URL de l'outil : page contributeur à la racine, back-office sous /admin/."""
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from collecte.vues_langue import changer_langue
from espaces.vues import Connexion

urlpatterns = [
    path("admin/", admin.site.urls),
    path("connexion/", Connexion.as_view(), name="login"),
    path("deconnexion/", auth_views.LogoutView.as_view(), name="logout"),
    path("langue/", changer_langue, name="langue"),  # langue de l'interface (barre du haut), aussi sans être connecté
    path("", include("espaces.urls")),
    path("", include("parametres.urls")),
    path("", include("collecte.urls")),
    path("", include("serveur_mcp.urls")),  # /mcp/ (assistants) et Paramètres › Assistants
]

handler403 = "collecte.reponses_script.refus"  # motif du refus en JSON pour le script des pages
