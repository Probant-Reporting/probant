from django.urls import path

from . import vues

app_name = "serveur_mcp"

urlpatterns = [
    path("mcp/", vues.point, name="point"),  # assistants (MCP) : un jeton, jamais de session
    path("administration/parametres/assistants/", vues.reglages, name="reglages"),
]
