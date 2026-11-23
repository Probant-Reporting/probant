{% comment %}Script des pages, inclus en ligne par templates/base.html. Une seule fonction englobante, découpée en
14 morceaux contigus (dossier _app/), inclus ici dans l’ordre : le premier l’ouvre, le dernier la ferme, et les
variables restent partagées entre les morceaux. Ne pas réordonner ; un morceau qui utilise une balise de la
bibliothèque collecte (icone…) la charge lui-même.{% endcomment %}{% include "collecte/_app/01_socle.js" %}
{% include "collecte/_app/02_panneau.js" %}
{% include "collecte/_app/03_envoi.js" %}
{% include "collecte/_app/04_formulaires_export.js" %}
{% include "collecte/_app/05_filtres.js" %}
{% include "collecte/_app/06_spoc.js" %}
{% include "collecte/_app/07_referentiel.js" %}
{% include "collecte/_app/08_fiches.js" %}
{% include "collecte/_app/09_grilles_formule.js" %}
{% include "collecte/_app/10_fichiers.js" %}
{% include "collecte/_app/11_parametres.js" %}
{% include "collecte/_app/12_communs.js" %}
{% include "collecte/_app/12b_ia.js" %}
{% include "collecte/_app/13_tableaux.js" %}
