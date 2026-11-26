from django.urls import path

from . import vues_reglages

app_name = "connexion_entreprise"
urlpatterns = [
    path("administration/parametres/connexion-entreprise/", vues_reglages.reglages, name="reglages_entreprise"),
]
