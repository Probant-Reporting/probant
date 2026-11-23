from django.urls import path

from . import vues

app_name = "espaces"
urlpatterns = [
    path("administration/espaces/", vues.liste, name="liste"),
    path("administration/espaces/nouveau/", vues.nouveau, name="nouveau"),
]
