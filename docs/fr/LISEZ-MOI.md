# Probant (lisez-moi en français)

> Lisez-moi en français. Le [README.md](../../README.md) anglais présente l'outil. Ce lisez-moi donne en plus les
> commandes principales et les repères pour l'IT.

Cette page vous indique comment essayer, lancer et installer Probant.

Probant est un outil configurable de collecte et de suivi d'indicateurs (KPI), pour tout reporting et pour
l'accompagnement des audits. Il couvre les référentiels, les organisations, les campagnes par période, la saisie avec
preuves et validation, la cohérence, le taux de remplissage, les relances par e-mail, les imports et les exports.
Avec l'assistant
**Mise en place**, vous pouvez l'installer pour toute structure. Plusieurs départements (espaces) peuvent partager une
même installation. L'interface existe en français, anglais, espagnol, allemand, italien, néerlandais et portugais.

Le tableau ci-dessous indique quoi lire pour chaque tâche :

| Pour… | Lire |
|---|---|
| Installer l'outil sur un serveur avec Docker (IT) | [installation.md](installation.md) (pas à pas, illustré) |
| Installer l'outil sans serveur, chez Clever Cloud (IT) | [hebergement_cle_en_main.md](hebergement_cle_en_main.md) (application Python avec PostgreSQL et FS Bucket) |
| Savoir quel fichier va où | [rangement_des_fichiers.md](rangement_des_fichiers.md) (preuves, logo, imports, sauvegardes) |
| Comprendre l'assistant IA facultatif (éteint par défaut) : ce qui part, la clé, le réseau | [prise_ia.md](prise_ia.md) |
| Apprendre à se servir de l'outil, par rôle (aussi dans l'outil, par l'icône Aide) | [guides/LISEZ-MOI.md](guides/LISEZ-MOI.md) |
| Écrire un texte de l'outil ou de la documentation | [guide_ecriture.md](guide_ecriture.md) |
| Connecter un assistant IA (Claude…) avec ses droits, ou le permettre (administrateur) | [assistants_mcp.md](assistants_mcp.md) |

Ces guides sont la traduction française des guides anglais. **Le reste de la documentation est en anglais**, dans
[docs/](..) :

- espaces : [spaces.md](../spaces.md)
- bibliothèque de référentiels : [library.md](../library.md)
- traductions : [translation.md](../translation.md)

Les administrateurs créent et gèrent les comptes dans l'outil. Chacun peut aussi se connecter avec son compte d'entreprise (OpenID Connect, éteint par défaut,
[connexion_entreprise.md](connexion_entreprise.md)) : le fournisseur prouve seulement l'identité, l'outil ne crée aucun
compte. L'IT fournit l'hébergement, le nom de domaine avec HTTPS, le compte SMTP
pour les e-mails et la destination de la copie externe des sauvegardes.

## Essayer l'outil sur un ordinateur

Vous pouvez essayer l'outil sur un ordinateur Windows ou Mac, sans droits administrateur. La version tout-en-un
contient un Python portable : vous n'installez rien. C'est un essai pour une personne sur un ordinateur, pas pour une
équipe : pour travailler à plusieurs, installez l'outil sur un serveur.

Pour lancer la version tout-en-un :

1. Sur la page du dépôt, ouvrez **Releases**, puis la dernière version.
2. Téléchargez `probant-windows.zip`. Sur un Mac, téléchargez `probant-mac.zip` (processeurs Apple et Intel).
3. Extrayez le fichier.
4. Double-cliquez sur `Start.bat`. Sur un Mac, double-cliquez sur `Start.command`. Le premier démarrage demande ce
   que vous voulez essayer : la démo (Exemplia, une société fictive avec ses données) ou un outil vide (vous mettez en
   place votre propre structure).
   La fenêtre montre chaque étape du démarrage avec une ligne qui avance (barre, part faite, temps écoulé) : le premier
   démarrage prend quelques minutes, les suivants moins. Le navigateur s'ouvre quand l'outil est prêt.
5. Démo : la fenêtre liste un compte par rôle (`admin`, `validateur`, `contributeur`, `lecteur`, `auditeur`), tous
   avec le mot de passe `demo-probant-2026`. Déconnectez-vous pour essayer un autre compte. Outil vide : l'assistant de
   mise en place s'ouvre, et sa première étape crée votre compte administrateur.

L'outil garde vos essais dans le dossier `data`.

## Essayer l'outil dans GitHub Codespaces

Codespaces ouvre une copie de l'outil dans votre navigateur, sur un ordinateur de GitHub. Tout s'installe et démarre
seul, avec des **données fictives**. Vous pouvez saisir des valeurs, les valider et ajouter des preuves sans aucun
risque.

### Ouvrir le Codespace

Avant de commencer, connectez-vous à votre compte GitHub.

Pour ouvrir le Codespace la première fois :

1. Allez sur la page du dépôt sur GitHub.
2. Cliquez sur le bouton vert **Code**.
3. Cliquez sur l'onglet **Codespaces**.
4. Cliquez sur **Create codespace on main**.
5. Attendez 2 à 4 minutes. Un éditeur (VS Code) s'ouvre dans le navigateur. Le site démarre seul.

Les fois suivantes, cliquez sur le nom du Codespace existant (n'en créez pas un nouveau). Si l'onglet du site ne
s'ouvre pas, cliquez sur l'onglet **Ports** de l'éditeur, puis sur l'icône globe de la ligne **8000 (Probant)**.

### Se connecter avec un compte de démo

Les comptes de démo sont `admin`, `validateur`, `contributeur`, `lecteur` et `auditeur`. Ils ont le même mot de passe,
`demo-probant-2026`. Ce sont des comptes fictifs : utilisez-les seulement dans la démo. Cela vaut aussi pour la version
tout-en-un.

La démo est **Exemplia**, un fabricant fictif d'emballages en carton, sans lien avec
une vraie entreprise : 4 niveaux (Groupe › Pays › Filiale › Site), 11 sites en France, en Espagne et en Allemagne, la norme
volontaire VS (modules de base et complet) et les onze modèles ESRS installés sans aucune valeur ni campagne (ils paraissent
dans la bibliothèque et dans les Paramètres, prêts à entrer dans une campagne), exercices 2024 et 2025 remplis, validés et clôturés, et exercice 2026
ouvert pour essayer la saisie, les validations et les relances : date limite dans 10 jours,
collecte en cours (valeurs validées, brouillons, cases à saisir ; 2 alertes de cohérence à traiter et 1 justifiée, en
attente du validateur). Le classeur officiel
de l'EFRAG s'exporte pour 2024 et 2025. Pour recharger la démo depuis le début, saisissez
`python3 manage.py load_demo --reset`.

### Essayer une installation vide

Le Codespace permet aussi de partir d'une installation vide, sur son propre port :

- **Installation vide** : `bash .devcontainer/start_empty.sh`, port 8002. L'assistant **Mise en place** s'ouvre à la
  place de la page de connexion.

### Récupérer les dernières modifications

Pour récupérer les dernières modifications dans le Codespace :

1. Dans le terminal du Codespace, appuyez sur **Ctrl+C**. Le site s'arrête.
2. Saisissez `git pull`, puis appuyez sur Entrée.
3. Saisissez `bash .devcontainer/start.sh`. La commande installe ce qui manque, applique les migrations et démarre le
   site.
4. Rechargez la page.

## Lancer l'outil sur un poste de travail

Avec Docker (recommandé), saisissez `./install.sh`, puis ouvrez l'adresse affichée. Sur un serveur, installez plutôt
l'outil en une commande, avec l'image publiée (voir « Commandes principales »). Le guide complet pour l'IT est
[installation.md](installation.md).

La base est vide. À la première ouverture, l'assistant **Mise en place** s'ouvre à la place de la page de connexion.
Son étape 1 crée le compte administrateur. **Faites l'étape 1 tout de suite, avant de communiquer l'adresse à
d'autres personnes.**

Pour mettre à jour l'outil, saisissez `./update.sh`. La commande fait d'abord une sauvegarde, puis applique les
migrations automatiquement.

Sans Docker, pour le développement (Python 3.12 ou plus récent), saisissez ces commandes :

```bash
python3 -m pip install -r requirements.txt
export DJANGO_DEBUG=1           # mode développement (sinon : réglages de production, voir .env.example)
python3 manage.py migrate
python3 manage.py load_demo     # données de démo fictives (facultatif : sans elles, l'assistant s'ouvre)
python3 manage.py runserver
```

## Trouver les données d'une installation

Toutes les données d'une installation (bases, preuves, logo, sauvegardes, clé secrète) sont dans **un seul dossier**.
Ce dossier n'est jamais mélangé au code. Le tableau ci-dessous indique où il se trouve :

| Où | Dossier des données |
|---|---|
| Docker | `/data` (le volume `donnees`) |
| Poste de développement, Codespace | `local-data/` |
| Version tout-en-un (Windows, Mac) | `data/` à côté de `Start.bat` / `Start.command` |
| Clever Cloud | Le dossier réglé par `DATA_DIR` (le FS Bucket) |

## Commandes principales

Avec Docker, ajoutez `docker compose exec web` devant chaque commande. Dans un Codespace, écrivez `python3` au lieu de
`python`. Le tableau ci-dessous donne les commandes principales :

| Pour… | Commande |
|---|---|
| Installer en une commande (serveur) | `curl -fsSL https://github.com/Probant-Reporting/probant/raw/main/get.sh \| sudo sh` (`--check` : vérifier le serveur seulement) |
| Vérifier un serveur avant l'installation | `./install.sh --check` ou `sh check.sh` (ne change rien) |
| Installer ou mettre à jour sans accès à Internet | `./install.sh --offline probant-image-X.Y.Z.tar.gz`, `./update.sh --offline <archive>` |
| Mettre à jour (Docker) | `./update.sh` (sauvegarde d'abord, migrations au démarrage) |
| Mises à jour automatiques (serveur) | `sudo ./install.sh --auto-update on` ou `off` ; `./auto-update.sh --status` |
| Copier tout de suite les sauvegardes vers la destination externe | `python manage.py backup --copy` |
| Envoyer les alertes par e-mail (sans les tâches de fond) | `python manage.py check_data --alerts`, toutes les 15 minutes |
| Faire une sauvegarde maintenant | `python manage.py backup` (liste : `backup --list`) |
| Restaurer une archive | `python manage.py restore backup-20261026-023000-auto.zip` |
| Charger la démo | `python manage.py load_demo` (repartir de zéro : `--reset`, deux espaces : `--spaces` ; seulement sur une base vide ou déjà faite par la commande, sinon refus, sauf `--force-on-existing-data`) |
| Envoyer les relances du jour | `python manage.py send_reminders --auto` |
| Recalculer un exercice | `python manage.py recalculate 2025` |
| Contrôler la cohérence des données (sans rien modifier) | `python manage.py check_data` (`--json`, fait aussi chaque nuit à 03:30) |
| Effacer la corbeille (éléments supprimés depuis plus de 30 jours) | `python manage.py purge_deleted` (fait aussi à chaque démarrage) |
| Exporter ou importer un référentiel | `python manage.py package export <code>` / `package import <fichier>` |
| Lancer les tests | `python3 manage.py test` |
| Contrôler le code (import inutile, variable jamais lue, nom non défini… ; aucune règle de style, rien n'est reformaté) | `python3 -m ruff check .` |
| Lancer les tests en parallèle (outils : `python3 -m pip install -r requirements-dev.txt`) | `python3 manage.py test --parallel 4 --noinput` |
| Faire échouer les tests du navigateur quand Playwright ou Chromium manque (au lieu de les sauter) | `REQUIRE_BROWSER_TESTS=1 python3 manage.py test` |
| Tests automatiques sur GitHub (à chaque envoi dans `main`, à chaque demande de fusion, ou à la demande : SQLite, PostgreSQL, tous les tests du navigateur, installation Docker, `pip-audit`) | `.github/workflows/tests.yml` |
| Tester une installation Docker vierge | `bash docker/test_installation.sh` |

Les anciens noms français des commandes (`sauvegarde`, `restauration`, `charger_demo`, `relances`, `recalculer`,
`paquet`, `espaces`, `controler_donnees`), de leurs options et des réglages du fichier `.env` (`DOMAINE`,
`SMTP_HOTE`…) fonctionnent encore. Utilisez les noms anglais ci-dessus.

## Pour l'IT

Avant l'installation, donnez à l'IT [demande_it.md](demande_it.md) (ce qu'il faut préparer) et à l'équipe sécurité
[dossier_securite.md](dossier_securite.md) (architecture, données, flux réseau, questionnaire de sécurité).

Pour surveiller l'outil, utilisez ces repères :

- L'outil envoie lui-même des alertes par e-mail sur sa santé (**Administration › Paramètres › Santé**), allumées dès le
  départ sur une installation neuve. Le serveur d'e-mails se règle dans **Administration › Paramètres › Hébergement**,
  ou dans `.env` (`SMTP_HOST` passe alors en premier).
- `GET /sante/` répond `200` quand tout va bien, et `503` sinon (base ou stockage indisponible). Cette adresse ne
  demande pas de connexion et ne montre aucune donnée sensible.
- Pour lire le journal, saisissez `docker compose logs -f web`.
- Le numéro de version est affiché en bas de chaque page et dans **Administration › Paramètres › Hébergement**.
- Chaque nuit, le contrôle des données examine la base sans rien modifier : calculs refaits et comparés, valeurs sans
  KPI ou en double, statuts, pourcentages, attributions, preuves, formules, arbre et dernière sauvegarde. Le résultat
  est dans **Administration › Paramètres › Hébergement**, dans **À traiter** et dans le détail de `/sante/` (clé
  `controle_donnees`, jamais en `503`).
- Les gros imports de valeurs (au-delà de `BACKGROUND_IMPORT_ROWS` lignes, 5 000 par défaut) et les gros exports (seuil
  dans **Administration › Paramètres › Hébergement**) se font en arrière-plan, dans le processus `run_imports
  --schedule`, que l'image Docker lance. L'outil affiche une barre d'avancement. Les fichiers des gros exports sont dans
  `files/exports/`, effacés après 7 jours et jamais dans les sauvegardes. Le détail de `/sante/` signale un import
  ou un export bloqué (`background_imports`, `background_exports`).
- Les assistants IA (MCP) n'ont rien à installer : l'adresse `/mcp/` de chaque espace, même domaine et même HTTPS. Le
  proxy transmet l'en-tête `Authorization` (Caddy et Clever Cloud le font). Éteint tant qu'un administrateur ne l'a pas
  permis dans l'outil ([assistants_mcp.md](assistants_mcp.md)). L'assistant IA facultatif (clé d'un fournisseur,
  éteint par défaut) est décrit dans [prise_ia.md](prise_ia.md).
- Les preuves des KPI sensibles : **Administration › Paramètres › Hébergement** règle une durée de conservation en mois.
  L'outil ne supprime rien tout seul : un administrateur supprime les preuves proposées, après confirmation.
- L'icône **Aide** de la barre du haut ouvre le guide du rôle de la personne ([guides/LISEZ-MOI.md](guides/LISEZ-MOI.md)).
  L'outil lit les guides dans `docs/guides/` et `docs/fr/guides/`, sans accès à Internet.
