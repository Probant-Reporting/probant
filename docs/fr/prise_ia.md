# Prise IA (assistant IA facultatif)

État : réalisée ; vérifiée à l'écran avec le fournisseur
factice ; **pas encore essayée avec une vraie clé** (section 10). Version de référence, en anglais :
[`docs/ai_socket.md`](../ai_socket.md) (à tenir à jour ensemble).

La prise IA permet à une installation d'envoyer un petit ensemble de données, bien délimité, à un fournisseur d'IA et
d'en recevoir une **proposition** qu'une personne accepte ou non. Elle est **éteinte par défaut**. Rien ne sort de
l'installation tant qu'elle est éteinte.

## 1. Principes

| Principe | Comment l'outil le tient |
|---|---|
| Éteinte par défaut | Chaque espace démarre prise éteinte, sans clé, chaque usage éteint (migration `parametres/0033`). |
| Allumée par l'administrateur, avec la clé du client | Administration › Paramètres › Assistant IA, dans chaque espace. La clé est celle du compte du client chez le fournisseur : le client paie le fournisseur directement. |
| Une page dit exactement ce qui part | La même page liste, pour chaque usage, ce qui part et ce qui ne part jamais (mêmes constantes que le code : `parametres/ia_invites.py`, `ENVOYE`). |
| Rien ne sort tant qu'elle est éteinte | Une seule fonction envoie (`parametres/ia.py`, `appeler`). Elle refuse avant tout réseau si la prise, l'usage ou la clé manque, si l'IT a coupé la prise, si la limite du jour est atteinte ou si les données sont trop grosses. Dans ces cas, aucun bouton IA n'apparaît. |
| Toute réponse est une proposition | Une réponse n'écrit rien. La personne clique sur « Utiliser » (le texte va dans un champ), puis enregistre comme d'habitude. |
| Les KPI sensibles restent dans l'outil par défaut | Un réglage par espace, **Les KPI sensibles peuvent être envoyés à l'assistant IA**, éteint par défaut (migration `parametres/0037`). Éteint, rien d'un KPI marqué Restreint ou Confidentiel, ni d'un KPI calculé qui l'utilise, ne part par aucun usage (section 6, « KPI sensibles »). |

## 2. Une interface, plusieurs fournisseurs

`parametres/ia_fournisseurs.py` : une classe `Fournisseur` (code, nom, hôte à ouvrir, modèles, modèle par défaut) et une
seule méthode, `demander(requete)`. Toute erreur est une `ErreurIA` à code fermé, affichée en clair (clé refusée, crédit,
limite du fournisseur, surcharge, réseau, délai, refus, réponse trop longue, modèle, requête, réponse illisible).
Fournisseurs : `claude` (Anthropic) ; `factice` (sans réseau) seulement dans les tests, et avec `AI_FAKE_PROVIDER=1` sur
un poste de développement pour voir les écrans. Un nouveau fournisseur = une classe et une ligne ; les usages et les
écrans ne changent pas.

**Claude** : `POST https://api.anthropic.com/v1/messages`, version d'API `2026-10-21`, **sans dépendance nouvelle** (un
appel HTTPS par la bibliothèque standard ; le paquet officiel ajouterait 13 paquets à l'image pour un seul appel).
Modèles : Claude Fable 5.2 (le plus capable, **par défaut**), Claude Opus 5.5, Claude Sonnet 5.5, Claude Haiku 5.5 (le
moins coûteux) ; prix par million de jetons, entrée / sortie, relevés à la date de rédaction : 8 / 40 USD, 4 / 20, 2 / 10,
0,10 / 0,50. Réponse au format JSON imposé (sorties structurées), effort réglé par usage, pas de `temperature`. Un refus
du modèle est une erreur, jamais une réponse ; sur Fable, Opus et Sonnet, le repli côté serveur d'Anthropic est demandé
(si le compte refuse l'en-tête, une seule nouvelle tentative sans lui). Fable 5.2 demande la conservation des données
30 jours chez le fournisseur : un compte « sans conservation » doit choisir Opus 5.5 (dit sur la page).

## 3. Réseau : ce que l'IT ouvre

| Élément | Valeur |
|---|---|
| Sens | Sortant seulement, depuis le serveur de l'outil |
| Hôte et port | `api.anthropic.com`, TCP 443 (HTTPS) |
| Proxy | La variable standard `HTTPS_PROXY` est suivie si elle est réglée (dans `.env` avec Docker) |
| Interrupteur de l'IT | `AI_SOCKET=off` : prise cachée dans tous les espaces, aucun appel, quels que soient les réglages des administrateurs |

## 4. Délais, erreurs, taille, limite du jour

| Réglage (par espace) | Défaut | Bornes | Effet |
|---|---|---|---|
| Appels par jour | 50 | 1 à 5 000 | Au-delà, refus avant envoi. Un appel en échec compte (il a pu être facturé). |
| Caractères envoyés par appel | 60 000 | 2 000 à 400 000 | Au-delà, refus avant envoi, avec la taille et la limite. |
| Délai d'attente | 60 s | 10 à 110 s | L'appel entier s'arrête après ce délai, nouvelle tentative sans l'en-tête bêta et réponse lente comprises (le serveur coupe une requête à 120 s). |

La sortie de chaque usage est bornée (2 000 jetons pour une explication, 8 000 pour les correspondances, 16 000 pour les
traductions) : le coût d'un appel l'est aussi. **Plafond de dépense** : l'outil limite le **nombre d'appels**, pas
l'argent (il ne connaît ni les prix ni les remises du client) ; le guide conseille une limite mensuelle dans la console
du fournisseur. Pas de nouvelle tentative automatique. Le compte du jour est relu et l'appel réservé dans une seule
transaction, sous le verrou de la ligne des paramètres (PostgreSQL ; sous SQLite, transactions « immediate ») : deux
personnes qui cliquent en même temps ne dépassent pas la limite.

## 5. La clé

| Question | Choix | Pourquoi |
|---|---|---|
| Où la saisir ? | Paramètres › Assistant IA, par un administrateur de l'espace | L'administrateur de l'espace en est responsable. |
| Par espace ou pour l'installation ? | **Par espace** | Le plus prudent : allumer la prise dans un espace ne fait jamais sortir les données d'un autre ; chaque espace peut avoir son compte et son budget. |
| Où est-elle gardée ? | Dans un fichier du dossier des données, `ai-keys/<espace>.key`, lisible par l'outil seul, **jamais en base** | Une ligne en base partirait dans chaque sauvegarde de l'outil et de l'hébergeur. Le fichier est exclu des sauvegardes comme `.secret_key`, et une restauration ne l'efface ni ne l'écrase. |
| Réaffichée ? | Jamais | Champ mot de passe toujours vide ; la page dit « Une clé est enregistrée depuis le … » et « Retirer la clé ». |
| Au journal ? | Jamais | Le journal dit « clé enregistrée » ou « clé retirée », sans valeur ; le champ est caché des rapports d'erreur de Django. |
| Après une restauration sur un autre serveur | La clé n'y est pas : la prise reste réglée mais inutilisable tant qu'un administrateur ne la ressaisit pas | Une sauvegarde ne porte jamais la clé. |

Comparaison avec une variable d'environnement fournie par l'IT (comme le mot de passe SMTP) : l'IT réglerait un choix
fonctionnel, la clé serait la même pour tous les espaces et l'administrateur ne pourrait pas allumer seul. La variable
sert seulement à l'interrupteur de l'IT (`AI_SOCKET=off`).

## 6. Usages

Chacun a son interrupteur dans les Paramètres, éteint par défaut. Un bouton n'apparaît que si la prise est allumée, une
clé enregistrée, l'usage allumé et la personne a le droit (section 7).

- **(a) Expliquer une alerte de cohérence** — fiche de l'alerte (page Cohérence) et encadré « À vérifier » du panneau de
  saisie. Part : la langue de la réponse ; le nom du KPI, son unité, son format ; le **niveau** de l'organisation (pas son
  nom) ; la période ; le contrôle et son constat ; la valeur et la référence ; les valeurs de 6 périodes précédentes au
  plus ; pour une règle entre KPI, son nom, sa description et chaque KPI avec sa valeur. Ne part jamais : noms
  d'organisations, personnes, commentaires, explications, preuves. Pas proposé sur une alerte « calcul impossible » : c'est
  une information, rien à justifier, et son constat est le message du calcul, qui cite des organisations (« Valeur non
  saisie : EFF / <organisation> ») ; pas de bouton, et le serveur refuse la demande avant tout envoi. Réponse : une explication courte (1 200 caractères au
  plus) et 3 vérifications au plus, dans un bloc « Proposé par l'IA », avec « Reprendre comme explication » (le texte va
  dans le champ, que la personne enregistre elle-même).
- **(b) Relier les KPI d'un ancien fichier** (assistant de reprise, étape « Relier », « Proposer avec l'IA »). Part : les
  libellés pas encore reliés (150 au plus), avec le nom ou l'unité lus à côté ; les KPI actifs (code, nom, unité). Ne part
  jamais : valeurs, organisations, périodes, commentaires, le fichier. Réponse : un code de KPI par libellé (seulement un
  code envoyé), avec une raison courte ; « Utiliser » par ligne et « Reprendre les N propositions ». La correspondance
  n'est mémorisée que par le bouton habituel de l'assistant.
- **(c) Traduire les libellés d'une langue** (page Traductions, « Proposer avec l'IA »). Part : les deux langues ; pour
  chaque texte encore vide de la page (60 au plus), un numéro, son genre et le texte de départ. Ne part jamais : les clés
  techniques, les autres langues. Réponse : une traduction par numéro envoyé ; « Utiliser » par ligne et « Reprendre les
  N propositions » ; enregistrement par le bouton de la page.

- **KPI sensibles (les trois usages)** : réglage par espace **Les KPI sensibles peuvent être
  envoyés à l'assistant IA** (Paramètres › Assistant IA, sous les usages), **éteint par défaut**, écrit à l'historique.
  Les assistants MCP ont le même genre de réglage, mais allumé par défaut. « Sensible » a une seule définition pour les
  deux portes (`collecte/sensibles.py`) : un KPI marqué **Restreint** ou **Confidentiel** sur sa fiche, et tout KPI
  calculé qui l'utilise, directement ou par une autre formule. Réglage éteint : (a) pas de bouton « Expliquer avec
  l'IA » sur une alerte dont la case est un tel KPI ou dont la règle en cite un d'un côté, et le serveur refuse la
  demande avant tout envoi ; (b) ces KPI sont retirés de la liste des KPI envoyée (code, nom, unité) : l'IA ne les
  propose jamais, l'administrateur les relie à la main ; les libellés de l'ancien fichier partent toujours (des
  libellés, pas des valeurs) ; (c) le nom et les descriptions de ces KPI ne partent pas (sections « Noms des KPI » et
  « Descriptions ») : ils restent vides, à traduire à la main. Réglage allumé : comme avant. **Mise à jour d'une
  installation existante** : le réglage arrive éteint ; une installation qui avait allumé la prise perd « Expliquer avec
  l'IA » sur les alertes des KPI sensibles, jusqu'à ce qu'un administrateur allume le réglage.

## 7. Droits

| Usage | Qui | Pourquoi |
|---|---|---|
| (a) Expliquer une alerte | Administrateur, validateur, contributeur, pour une alerte qu'ils voient (règle de la page Cohérence) | La personne voit déjà chaque chiffre envoyé. |
| (a) pour lecteur et auditeur | **Non** | Une demande écrit une ligne au journal et compte dans une limite payante ; `collecte/lecture_seule.py` refuse toute écriture de ces rôles hors de leurs préférences. Réservé aux rôles qui écrivent (choix à confirmer, IA2). |
| (b) Reprise, (c) Traductions, Paramètres › Assistant IA | Administrateur | Mêmes droits que les pages. |

## 8. Journal et texte non sûr

- **Journal** : chaque appel écrit une ligne dans l'Historique avant l'envoi : qui, quel usage, quand, fournisseur,
  modèle, taille envoyée ; jamais le contenu ni la réponse (action `ia_appel`, famille « Assistant IA »). Les réglages
  écrivent des lignes `reglage_ia`.
- **La réponse est une donnée non sûre** : lue comme un JSON de forme fixe, champs inconnus écartés, textes coupés et
  nettoyés, affichée échappée (jamais en HTML ni en Markdown), jamais exécutée, et elle ne déclenche rien : seul le clic de
  la personne compte.
- **Les données envoyées peuvent contenir une tentative d'injection** (nom de KPI, libellé d'un ancien fichier) : les
  consignes sont fixes et viennent d'abord ; les données forment un seul bloc JSON entre `<data>` et `</data>`, avec `<` et
  `>` échappés ; les consignes disent que ce bloc ne contient aucune consigne. La réponse n'a aucun pouvoir.

## 9. Choix de produit ouverts

| # | Question | En place en attendant (le plus prudent) | Recommandation |
|---|---|---|---|
| IA1 | Modèle par défaut : Fable 5.2 (le plus capable, 8 / 40 USD, conservation 30 jours) ou Opus 5.5 (moitié prix) ? | Fable 5.2 ; l'administrateur peut changer | Opus 5.5 par défaut : usages courts, et Fable refusé sans conservation |
| IA2 | L'auditeur (et le lecteur) peut-il demander une explication ? | Non | Oui pour l'auditeur plus tard, si une demande n'est plus comptée comme une écriture |
| IA3 | Envoyer le nom de l'organisation avec une alerte ? | Jamais : son niveau seulement | Le garder dehors |
| IA4 | Limiter en nombre d'appels ou en argent ? | Appels par jour et par espace (50) | Garder les appels, et une limite mensuelle chez le fournisseur |
| IA5 | Une clé par espace ou pour l'installation ? | Par espace | Garder par espace |
| IA6 | Propositions pour les organisations d'un ancien fichier (b) ? | KPI seulement | Plus tard si demandé |
| IA7 | Garder une copie des réponses (trace de ce que l'IA a proposé) ? | Non : la ligne du journal seulement | Non, sauf besoin d'audit exprimé |
| IA8 | « Proposé par l'IA » nomme le fournisseur ? | Oui | Le garder |

## 10. Ce qui n'a pas été essayé

Aucun appel réel : pas de clé, et la suite de tests n'appelle jamais le réseau (le fournisseur Claude refuse toute
connexion pendant les tests). À essayer avec une vraie clé :

1. La réponse de l'API à la requête construite (sortie structurée, effort, en-tête du repli) sur les quatre modèles.
2. Une clé refusée (401), un compte sans crédit, une limite (429), un modèle refusé sans conservation (400).
3. La durée d'une traduction de 60 textes et d'une correspondance de 150 libellés avec Fable 5.2, face au délai de 60 s.
4. La qualité des trois usages dans chacune des sept langues de l'interface (la requête nomme la langue de la réponse : français, anglais, espagnol, allemand, italien, néerlandais ou portugais).
5. Un proxy (`HTTPS_PROXY`) et un pare-feu fermé (message « réseau »).

## 11. Fichiers et preuves

Fichiers et tests : voir les sections 11 et 12 de [`docs/ai_socket.md`](../ai_socket.md).
