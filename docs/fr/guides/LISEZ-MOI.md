# Guides par rôle

Un guide court par rôle, écrit par tâche, dans les sept langues de l'interface. Version anglaise : [`docs/guides/README.md`](../../guides/README.md).

| Rôle | Français | Anglais |
|---|---|---|
| Administrateur | [administrateur.md](administrateur.md) | [administrator.md](../../guides/administrator.md) |
| Validateur | [validateur.md](validateur.md) | [validator.md](../../guides/validator.md) |
| Contributeur | [contributeur.md](contributeur.md) | [contributor.md](../../guides/contributor.md) |
| Lecteur | [lecteur.md](lecteur.md) | [reader.md](../../guides/reader.md) |
| Auditeur | [auditeur.md](auditeur.md) | [auditor.md](../../guides/auditor.md) |

Les guides en espagnol, allemand, italien, néerlandais et portugais sont dans `docs/<langue>/guides/` (`es`, `de`, `it`,
`nl`, `pt`) ; le tableau des noms de fichiers est dans [`docs/guides/README.md`](../../guides/README.md).

## L'aide dans l'outil

L'outil sert lui-même ces fichiers, sans accès à Internet (`collecte/aide.py`) :

- L'icône **Aide** de la barre du haut ouvre le guide de votre rôle, à la section de la page où vous êtes, dans la langue de
  l'interface. Une langue de l'interface qui n'a pas encore de guide reçoit le guide anglais, avec une note.
- L'adresse `/aide/` ouvre votre guide, `/aide/<rôle>/` un autre (`administrator`, `validator`, `contributor`, `reader`,
  `auditor`). Toute personne connectée peut lire tous les guides : ils ne contiennent aucune donnée.
- L'image Docker et le paquet portable contiennent `docs/guides/`, `docs/<langue>/guides/` et `docs/screenshots/`.

## Écrire ou changer un guide

- Suivez `docs/fr/guide_ecriture.md`. Écrivez d'abord le guide anglais, puis le guide français, puis les cinq autres langues, avec les mêmes sections.
- Une section est `## Titre de la tâche {#ancre}`. Les ancres sont les mêmes dans les sept langues : le lien d'aide les
  utilise (`SECTIONS` et `PREFIXES` dans `collecte/aide.py`). Un test les vérifie.
- Un texte en gras est un libellé exact de l'outil (chemin : **Administration › Paramètres**). Un test vérifie chaque
  gras dans `libelles/` de la langue du guide, pour les sept langues. Écrivez le reste en texte simple.
- Une image est une ligne seule : `![Courte description](../../screenshots/fr/nom.png)`.
- Tests : `python3 manage.py test collecte.test_aide_guides`.

## Refaire les captures

Un script fait les captures à partir de la démo fictive Exemplia (2026 ouvert), dans les sept langues (une démo chargée dans chaque langue, pour que les textes de la démo suivent l'interface), à taille fixe (1 280 × 720 px
sur ordinateur, 390 × 844 px sur téléphone, `deviceScaleFactor` 2). Aucune donnée réelle. Les 27 écrans des guides sont faits
pour chaque langue (l'écran `guided-tour` est pris exprès avec la visite guidée allumée, tous les autres avec la visite éteinte) ; les 5 écrans du guide d'installation (`login`, `health`, `setup-*`) seulement en anglais et en français,
car `docs/installation.md` n'existe que dans ces deux langues.

```bash
python3 -m pip install -r requirements-dev.txt          # Pillow compresse les images
node qa/guide_screenshots.js                            # tous les écrans, les sept langues
node qa/guide_screenshots.js --langs fr --only dashboard,reminders --port 8271
```

Le script crée des bases jetables dans un dossier temporaire (jamais `local-data/`), lance deux serveurs sur `--port` et
`--port` + 1 (8261 par défaut), fait les captures, écrit `docs/screenshots/<langue>/<nom>.png` (chacune sous 300 Ko) puis
s'arrête. Il demande Node.js avec Playwright et Chromium (`qa/browser_journeys/README.md`). Options : `--python` (le
Python du projet), `--out`, `--keep`, `--data-dir`. Relancez-le après tout changement d'écran, puis validez les images.
Le guide d'installation (`docs/fr/installation.md`) cite les mêmes images.
