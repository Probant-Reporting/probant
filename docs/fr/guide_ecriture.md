# Guide d'écriture

Le système d'écriture unique pour tous les textes de l'outil : interface (menus, boutons, libellés, aides, messages),
e-mails de relance, exports et documentation. Version de référence en anglais :
[`docs/writing_guide.md`](../writing_guide.md) (tenir les deux à jour ensemble).

**L'anglais est la langue de base.** Chaque texte s'écrit d'abord en anglais, selon ce guide. L'interface existe en sept
langues : anglais, français, espagnol, allemand, italien, néerlandais et portugais. Les six autres sont traduites de
l'anglais, puis adaptées avec les règles de la section 8. Les mots de chaque notion sont fixés dans le glossaire de
traduction ([`docs/translation_glossary.md`](../translation_glossary.md), en anglais, une colonne par langue). La
mécanique (zones, clés, paramètres, ajout d'une langue) est dans [`docs/translation.md`](../translation.md).

Un texte nouveau n'est pas terminé tant qu'il n'existe pas dans les sept langues : une langue à laquelle il manque une
clé n'est pas proposée aux personnes (`parametres/controle_libelles.py`), et `qa/translation_check.py check <langue>`
liste ce qui manque.

Sources. Le guide ne garde de chaque source que ce qui convient à un outil web utilisé par des
non-spécialistes, en sept langues :

| Source | Sert pour |
|---|---|
| Apple Style Guide | Textes de l'interface : noms des actions, boutons, messages, typographie |
| Google developer documentation style guide | Documentation : structure des pages, procédures, titres |
| ASD-STE100 (Simplified Technical English) | Langue contrôlée par-dessus les deux : un mot = un sens, phrases courtes, voix active |

Quand les sources ne sont pas d'accord, ce guide tranche (par exemple : pas de contractions en anglais, comme dans
STE100, car elles gênent la traduction).

## 1. Principes

1. **Écrire pour une personne pressée qui n'est pas informaticienne.** Employer les mots du métier, pas ceux du code.
2. **Une notion = un mot, partout.** Suivre le lexique. Ne pas changer de mot pour éviter une répétition.
3. **Dire quoi faire, puis pourquoi (si nécessaire).** L'action vient en premier.
4. **Court.** Si un texte demande plus de deux phrases à l'écran, mettre la suite dans une aide repliable ou dans la
   documentation.
5. **Écrire pour la traduction.** Phrases simples, pas d'expressions imagées, pas de jeux de mots, pas d'humour.

## 2. Ton

| Règle | À faire | À éviter |
|---|---|---|
| S'adresser au lecteur (« vous ») | Vous pouvez rouvrir une valeur validée. | Les utilisateurs peuvent rouvrir… |
| Pas de « nous » | L'outil calcule cette valeur. | Nous calculons cette valeur. |
| Le lecteur est le sujet | Vous pouvez exporter le tableau vers Excel. | Cette page vous permet d'exporter… |
| Voix active | Le validateur valide la valeur. | La valeur est validée par le validateur. |
| Présent | La relance part lundi. | La relance sera envoyée lundi. |
| Pas de « merci de », « veuillez », ni de point d'exclamation | Saisissez un nombre. | Veuillez saisir un nombre ! |
| Calme et neutre, même pour une erreur | Ce fichier dépasse 5 Mo. Choisissez un fichier plus petit. | Erreur ! Fichier invalide. |

## 3. Textes de l'interface

### Majuscules

**Majuscule au premier mot seulement** (et aux noms propres), partout : titres de page, menus, onglets, boutons, en-têtes
de colonnes, libellés, messages, dans les sept langues.

### Longueur

| Élément | Maximum | Forme |
|---|---|---|
| Bouton, lien qui agit | 3 mots | Verbe + objet : « Valider », « Ajouter une organisation » |
| Menu, onglet, titre de page | 3 mots | Nom : « Saisie », « Relances », « Paramètres » |
| Libellé de champ, en-tête de colonne | 4 mots | Groupe nominal |
| Aide sous un champ | 1 phrase, 20 mots | Dit quoi saisir ou ce que le champ change |
| Introduction d'une page | 2 phrases, 25 mots chacune | Dit à quoi sert la page, puis l'action principale |
| Message après une action | 1 ou 2 phrases | Ce qui s'est passé, puis quoi faire (s'il y a lieu) |
| Suite de noms | 3 noms | « Statut de validation du KPI » est la limite |

Les explications plus longues vont dans une aide repliable (« Comment ça marche ? ») ou dans la documentation.

### Boutons et actions

- Un bouton commence par un **verbe à l'infinitif** qui dit exactement ce qui se passe : « Supprimer la campagne », pas
  « OK ».
- La même action a le même verbe partout (section 5).
- Une action qu'on ne peut pas annuler le dit dans sa confirmation, avec la conséquence :
  « Supprimer la campagne ? Ses 1 240 valeurs et leurs preuves sont supprimées. Cette action est définitive. »
  Le bouton de confirmation reprend le verbe (« Supprimer »), l'autre bouton est « Annuler ».

### Messages

| Type | Structure | Exemple |
|---|---|---|
| Réussite | Ce qui s'est passé | « Valeur enregistrée. » |
| Erreur que la personne peut corriger | Ce qui ne va pas + quoi faire | « Ce fichier est un document Word. Choisissez un fichier PDF, JPG ou PNG. » |
| Erreur que la personne ne peut pas corriger | Ce qui s'est passé + qui peut aider | « L'e-mail n'est pas parti. Contactez votre équipe informatique. » |
| Avertissement avant une action | Conséquence + question | voir « Boutons et actions » |
| Page vide | Ce qui manque + comment l'ajouter | « Aucune campagne. Créez une campagne pour commencer la saisie. » |

- Ne jamais mettre la faute sur le lecteur : « Cette valeur n'est pas un nombre », pas « Vous avez saisi une valeur
  invalide ».
- Pas de code ni de terme technique dans un message (« erreur 500 », « exception »).

### Désigner l'interface dans une aide ou la documentation

- Écrire le nom d'un bouton ou d'un menu **exactement comme à l'écran**, en gras dans la documentation : « Cliquez sur
  **Exporter vers Excel**. »
- Chemins avec `›` : **Administration › Paramètres › Langues**.
- Ne pas désigner un élément par sa place ou sa couleur seulement (« le bouton vert à droite ») : donner son nom.

## 4. Phrases (langue contrôlée)

D'après ASD-STE100, pour toute phrase (aides, messages, e-mails, documentation) :

1. **Une consigne par phrase.** Deux actions → deux phrases, ou une liste numérotée.
2. **Consignes : 20 mots au plus. Descriptions : 25 mots au plus.** Nombres, codes, noms de boutons cités et noms
   propres comptent pour un mot.
3. **La condition d'abord, puis une virgule, puis l'action** : « Si la campagne est fermée, demandez à un
   administrateur de la rouvrir. »
4. **Garder les petits mots** : articles, « que » après les verbes (« Vérifiez que le fichier est un PDF »).
5. **Pas de point-virgule en anglais.** En français et en espagnol, préférer deux phrases.
6. **Pas d'abréviations latines** ni de « etc. » : « par exemple », « c'est-à-dire ».
7. **Éviter** « (s) » pour les pluriels, « et/ou », « via ».
8. **Un paragraphe a un seul sujet et 6 phrases au plus** (documentation).

## 5. Mots des actions

Un verbe par action, dans chaque langue. Les verbes allemands, italiens, néerlandais et portugais sont à la section 2.5 du
[glossaire de traduction](../translation_glossary.md).

| Action | Anglais | Français | Espagnol | À éviter (anglais) |
|---|---|---|---|---|
| Ouvrir une session | sign in / sign out | se connecter / se déconnecter | iniciar sesión / cerrar sesión | log in, log on |
| Appuyer sur un élément de l'écran | click | cliquer | hacer clic | click on, press, hit |
| Taper une information | enter | saisir | capturar (une valeur), introducir (un nom, un mot de passe, un e-mail) | input, fill in, type in |
| Cocher une case, choisir une option ou une ligne | select / deselect | cocher / décocher (case), sélectionner (ligne) | marcar / desmarcar (case), seleccionar (ligne) | tick, check, uncheck |
| Choisir dans une liste ou un menu | choose | choisir | elegir | select a command, pick |
| Changer l'état d'un réglage | turn on / turn off | activer / désactiver | activar / desactivar | enable, disable, toggle |
| Garder une modification | save | enregistrer | guardar | store, record |
| Faire disparaître définitivement | delete | supprimer | eliminar | erase, destroy |
| Sortir d'une liste sans détruire | remove | retirer | quitar | delete |
| Faire quelque chose de nouveau | create (un objet), add (à une liste) | créer, ajouter | crear, añadir | make, generate |
| Changer quelque chose | edit (un objet), change (une valeur, un réglage) | modifier | modificar | modify, update |
| Envoyer un fichier à l'outil | import (données), add (preuve) | importer, ajouter | importar, añadir | upload |
| Récupérer un fichier | export (données), download (fichier) | exporter, télécharger | exportar, descargar | extract |
| Confirmer qu'une saisie est complète | validate | valider | validar | approve (sauf ci-dessous), submit |
| Accepter ou refuser une demande de valeur forcée | approve / reject | accepter / refuser | aceptar / rechazar | validate (réservé à la saisie) |
| Annuler une validation | reopen | rouvrir | reabrir | unvalidate, unlock |
| Montrer | show | afficher | mostrar | display, view (verbes) |
| Arrêter une action | cancel | annuler | cancelar | abort, quit |

Les mots des choses (KPI, référentiel, campagne, organisation, preuve, relance…) sont dans le
[glossaire de traduction](../translation_glossary.md), qui a une colonne par langue. Y ajouter un mot, dans toutes les
colonnes, avant de l'employer dans un nouveau texte.

## 6. Mots à éviter (anglais)

e-mail → email ; okay → OK ; drop-down → list ; tooltip → help ; user (en s'adressant au lecteur) → you ;
utilise → use ; commence → start ; additional → more ; prior to → before ; due to → because of ; whether → if ;
in order to → to ; corrupted → damaged ; whitelist / blacklist → allow list / deny list ; bug, crash → problem, stops.

## 7. Typographie (anglais)

Anglais britannique (organisation, colour), chiffres pour tous les nombres, `12.5%`, espace entre nombre et unité
(`5 MB`), dates `4 November 2026`, deux-points avant une liste, virgule avant le dernier élément d'une énumération,
guillemets “…” pour un message cité. Détail dans la version anglaise.

## 8. Français, espagnol et autres langues

Les textes français et espagnols suivent les mêmes règles (sections 1 à 5) : même sens, même structure, même longueur
autant que la langue le permet. Ils n'ajoutent ni ne retirent d'information. Ensuite :

| | Français | Espagnol |
|---|---|---|
| S'adresser au lecteur | vous | usted (« Haga clic », « Compruebe ») |
| Consignes | impératif (« Saisissez un nombre. ») | impératif avec usted (« Capture un valor. », « Introduzca su contraseña. ») |
| Boutons | infinitif (« Exporter vers Excel ») | infinitif (« Exportar a Excel ») |
| Deux-points, point-virgule, ? ! | espace insécable avant (« Total : 3 ») | pas d'espace avant ; ¿ ¡ au début |
| Guillemets | « … » avec espaces insécables | «…» sans espace |
| Nombres | `1 240,5` (espace fine insécable, virgule) | `1.240,5` |
| Pourcentages | `12,5 %` (espace insécable) | `12,5 %` |
| Dates | `4 novembre 2026`, `04/11/2026` dans les tableaux | `4 de noviembre de 2026`, `04/11/2026` dans les tableaux |
| Majuscules | au premier mot seulement | au premier mot seulement |
| Variante | français de France | espagnol d'Espagne |

L'allemand, l'italien, le néerlandais et le portugais suivent les mêmes règles. Leur façon de s'adresser au lecteur, les
consignes, les boutons, les guillemets, les formats des nombres et des dates et l'orthographe sont à la section 4 du
[glossaire de traduction](../translation_glossary.md) : allemand avec « Sie », italien impersonnel, néerlandais avec
« u », portugais d'Europe. Un lecteur dont c'est la langue doit vérifier chacune de ces quatre langues avant que l'outil soit proposé
dans son pays.

## 9. Documentation

D'après le Google developer documentation style guide :

- **Commencer par le but** : la première phrase d'une page dit ce que le lecteur peut en faire.
- **Titres** en forme de tâche quand c'est possible : « Restaurer une sauvegarde », pas « Restauration ».
- **Procédures** : une introduction qui finit par deux-points, puis des étapes numérotées, une action par étape, le
  résultat après l'action (« Cliquez sur **Enregistrer**. L'outil affiche la nouvelle valeur. »).
- **Prérequis avant les étapes**, pas au milieu.
- **Les notes informent seulement**, sans consigne. Un risque de perte de données est un **Avertissement**, placé avant
  l'étape.
- **Tableaux** pour comparer et pour les réglages ; une phrase avant chaque tableau dit ce qu'il montre.
- **Commandes, noms de fichiers et chemins** en police de code : `./update.sh`.
- **Liens** : le texte du lien dit où il mène, jamais « cliquez ici ».

## 10. À vérifier avant de committer un texte

- [ ] L'anglais est écrit d'abord ; les six autres langues le suivent.
- [ ] Chaque mot de notion ou d'action est celui du lexique.
- [ ] Majuscule au premier mot seulement. Pas de « veuillez », de « ! », de « nous ».
- [ ] Boutons : verbe d'abord, 3 mots au plus. Aides : 20 mots au plus par phrase.
- [ ] Messages : ce qui s'est passé, puis quoi faire.
- [ ] Le texte dit la même chose dans les sept langues, avec les mêmes paramètres (`{n}`, `{nom}`). `python3 -I qa/translation_check.py check <langue>` ne signale aucune erreur.
