# Translation glossary

Words and tone for the interface in six languages: French (fr), Spanish (es), German (de), Italian (it), Dutch (nl) and
Portuguese (pt). English is the base language: translate from `libelles/*.en.json`, and use the French text only to
settle an ambiguity. The general rules of writing (short, one word per concept, verb first on a button, no "we", no
"please") are in the [writing guide](writing_guide.md); the mechanics of the system (zones, keys, parameters) are in
[translation](translation.md). This page gives the words and the tone of each language.

A native reader must check each language before the tool is offered in its country.

## 1. How to translate a language

1. Run `python3 -I qa/translation_check.py extract <zone> --aide fr` to get the English texts of a zone, numbered (nine
   zones: `cadre`, `saisie`, `suivi`, `admin`, `referentiels`, `messages`, `visualisation`, `mcp`, `espaces`).
2. Translate line by line with this glossary. Keep every `{parameter}` and every tag (`<b>`, `<strong>`, `<em>`, `<code>`,
   `<br>`) as in English. Write a plural as `one text ¦¦ other text`. Write a line break as `\n`.
3. Run `python3 -I qa/translation_check.py apply <lang> <zone> batch.txt --travail <folder>` for each batch. The tool
   refuses a line with other parameters or tags. When the zone is complete, it writes `libelles/<zone>.<lang>.json`.
4. Set the language settings (section 3) in `visualisation.<lang>.json` and `cadre.<lang>.json`, then run
   `python3 -I qa/translation_check.py check <lang>`. Fix every error. Read the lists of texts identical to English and of
   texts much longer than English.
5. Run the tests of `parametres` (`parametres/test_controle_libelles.py`). A language appears in the language selector
   only when it is complete: nothing else to switch on. Do not translate demonstration contents or the model library.

Do not translate: the name **Probant**, **KPI**, **N/A**, **SPOC**, **GHG**, **CSV**, **PDF**, **Excel**, **SMTP**, **API**,
codes, file names, formulas, and the unit symbols given by the data.

## 2. Glossary

Use only these words. In the columns, the choice for each language follows the tone rules of section 4.

### 2.1 Core concepts

| English | French | Spanish | German | Italian | Dutch | Portuguese |
|---|---|---|---|---|---|---|
| KPI | KPI (indicateur) | KPI (indicador) | KPI (Kennzahl) | KPI (indicatore) | KPI (indicator) | KPI (indicador) |
| framework | référentiel | marco de referencia | Berichtsrahmen | quadro di riferimento | kader | referencial |
| KPI framework | référentiel KPI | marco de KPI | KPI-Berichtsrahmen | quadro KPI | KPI-kader | referencial de KPI |
| library | bibliothèque | biblioteca | Bibliothek | biblioteca | bibliotheek | biblioteca |
| campaign | campagne | campaña | Kampagne | campagna | campagne | campanha |
| reporting year | exercice | ejercicio | Berichtsjahr | esercizio | verslagjaar | exercício |
| period | période | periodo | Periode | periodo | periode | período |
| data entry (menu, action) | saisie | captura | Datenerfassung | inserimento dati | gegevensinvoer | introdução de dados |
| enter (a value) | saisir | capturar | erfassen | inserire | invoeren | introduzir |
| value | valeur | valor | Wert | valore | waarde | valor |
| organisation | organisation | organización | Organisation | organizzazione | organisatie | organização |
| organisation tree | arbre des organisations | árbol de organizaciones | Organisationsstruktur | albero delle organizzazioni | organisatiestructuur | árvore de organizações |
| level (of the tree) | niveau | nivel | Ebene | livello | niveau | nível |
| theme | thème | tema | Thema | tema | thema | tema |
| unit | unité | unidad | Einheit | unità | eenheid | unidade |
| formula | formule | fórmula | Formel | formula | formule | fórmula |
| aggregation, aggregated | agrégation, agrégé | agregación, agregado | Aggregation, aggregiert | aggregazione, aggregato | aggregatie, geaggregeerd | agregação, agregado |
| assignment | attribution | asignación | Zuweisung | assegnazione | toewijzing | atribuição |
| evidence | preuve | justificante | Nachweis | giustificativo | bewijsstuk | comprovativo |
| comment | commentaire | comentario | Kommentar | commento | opmerking | comentário |
| justification | justification | justificación | Begründung | giustificazione | motivering | justificação |
| reminder | relance | recordatorio | Erinnerung | promemoria | herinnering | lembrete |
| send a reminder | relancer | enviar un recordatorio | Erinnerung senden | inviare un promemoria | herinnering sturen | enviar um lembrete |
| consistency (checks) | cohérence | coherencia | Konsistenz | coerenza | consistentie | coerência |
| alert | alerte | alerta | Hinweis | avviso | melding | alerta |
| to be handled | à traiter | por tratar | zu bearbeiten | da gestire | te behandelen | por tratar |
| variance (vs N-1) | écart (N-1) | desviación (respecto a N-1) | Abweichung (ggü. N-1) | scostamento (rispetto a N-1) | afwijking (t.o.v. N-1) | desvio (face a N-1) |
| completion rate | taux de remplissage | tasa de cumplimentación | Ausfüllgrad | tasso di compilazione | invulgraad | taxa de preenchimento |
| deadline (end of data entry) | date de fin de saisie | fecha de fin de captura | Erfassungsfrist | scadenza di inserimento | invoerdeadline | prazo de introdução |
| threshold | seuil | umbral | Schwellenwert | soglia | drempel | limiar |
| emission factor | facteur d'émission | factor de emisión | Emissionsfaktor | fattore di emissione | emissiefactor | fator de emissão |
| inherited parameter | paramètre hérité | parámetro heredado | vererbter Parameter | parametro ereditato | overgeërfde parameter | parâmetro herdado |
| entry type, answer type | type de saisie, type de réponse | tipo de captura, tipo de respuesta | Eingabetyp, Antworttyp | tipo di inserimento, tipo di risposta | invoertype, antwoordtype | tipo de introdução, tipo de resposta |
| choice list | liste de choix | lista de opciones | Auswahlliste | elenco di scelte | keuzelijst | lista de opções |
| template (file) | modèle | plantilla | Vorlage | modello | sjabloon | modelo |
| requested since (a KPI in a framework) | demandé depuis | solicitado desde | angefordert seit | richiesto dal | gevraagd sinds | pedido desde |
| file | fichier | archivo | Datei | file | bestand | ficheiro |
| row, column | ligne, colonne | fila, columna | Zeile, Spalte | riga, colonna | rij, kolom | linha, coluna |

### 2.2 Statuses and states

| English | French | Spanish | German | Italian | Dutch | Portuguese |
|---|---|---|---|---|---|---|
| to fill in | à saisir | por capturar | zu erfassen | da inserire | in te voeren | por introduzir |
| draft | brouillon | borrador | Entwurf | bozza | concept | rascunho |
| validated | validé | validado | validiert | convalidato | gevalideerd | validado |
| incomplete | incomplet | incompleto | unvollständig | incompleto | onvolledig | incompleto |
| calculated | calculé | calculado | berechnet | calcolato | berekend | calculado |
| calculation error | erreur de calcul | error de cálculo | Berechnungsfehler | errore di calcolo | rekenfout | erro de cálculo |
| overridden value | valeur forcée | valor forzado | überschriebener Wert | valore forzato | overschreven waarde | valor forçado |
| override request | demande de forçage | solicitud de valor forzado | Überschreibungsantrag | richiesta di forzatura | verzoek tot overschrijving | pedido de valor forçado |
| N/A | N/A | N/A | N/A | N/A | N/A | N/A |
| not applicable (full words) | non applicable | no aplica | nicht zutreffend | non applicabile | niet van toepassing | não aplicável |
| open for data entry | saisie ouverte | captura abierta | Erfassung offen | inserimento aperto | invoer open | introdução aberta |
| closed | clôturée | cerrada | abgeschlossen | chiusa | afgesloten | encerrada |
| in preparation | en préparation | en preparación | in Vorbereitung | in preparazione | in voorbereiding | em preparação |
| review (campaign status) | revue | revisión | Prüfung | revisione | review | revisão |
| confidential, restricted, not sensitive | confidentiel, restreint, non sensible | confidencial, restringido, no sensible | vertraulich, eingeschränkt, nicht sensibel | riservato, limitato, non sensibile | vertrouwelijk, beperkt, niet gevoelig | confidencial, restrito, não sensível |
| yes, no | oui, non | sí, no | Ja, Nein | sì, no | ja, nee | sim, não |
| none, all | aucun, tous | ninguno, todos | keine, alle | nessuno, tutti | geen, alle | nenhum, todos |
| Sum, Count, Average, Latest value | Somme, Décompte, Moyenne, Dernière valeur | Suma, Recuento, Media, Último valor | Summe, Anzahl, Durchschnitt, Letzter Wert | Somma, Conteggio, Media, Ultimo valore | Som, Aantal, Gemiddelde, Laatste waarde | Soma, Contagem, Média, Último valor |
| year, half-year, quarter, month | année, semestre, trimestre, mois | año, semestre, trimestre, mes | Jahr, Halbjahr, Quartal, Monat | anno, semestre, trimestre, mese | jaar, halfjaar, kwartaal, maand | ano, semestre, trimestre, mês |

### 2.3 People and roles

| English | French | Spanish | German | Italian | Dutch | Portuguese |
|---|---|---|---|---|---|---|
| administrator | administrateur | administrador | Administrator | amministratore | beheerder | administrador |
| validator | validateur | validador | Validator | validatore | validator | validador |
| contributor | contributeur | colaborador | Mitwirkender | collaboratore | bijdrager | colaborador |
| reader | lecteur | lector | Leser | lettore | lezer | leitor |
| auditor | auditeur | auditor | Auditor | auditor | auditor | auditor |
| SPOC (point of contact) | SPOC (personne référente) | SPOC (persona de referencia) | SPOC (Ansprechperson) | SPOC (referente) | SPOC (aanspreekpunt) | SPOC (ponto de contacto) |
| account | compte | cuenta | Konto | account | account | conta |
| (temporary) password | mot de passe (provisoire) | contraseña (provisional) | (vorläufiges) Passwort | password (provvisoria) | (tijdelijk) wachtwoord | palavra-passe (provisória) |
| email | e-mail | correo electrónico | E-Mail | e-mail | e-mail | email |
| space (a department) | espace | espacio | Bereich | spazio | ruimte | espaço |

### 2.4 Menus, pages and places

| English | French | Spanish | German | Italian | Dutch | Portuguese |
|---|---|---|---|---|---|---|
| Data entry (menu) | Saisie | Captura | Datenerfassung | Inserimento dati | Gegevensinvoer | Introdução de dados |
| Dashboard | Tableau de bord | Cuadro de mando | Dashboard | Cruscotto | Dashboard | Painel de controlo |
| Visualisation (module) | Visualisation | Visualización | Visualisierung | Visualizzazione | Visualisatie | Visualização |
| view (of the Visualisation) | vue | vista | Ansicht | vista | weergave | vista |
| visual (chart, table on a view) | visuel | visual | Visual | visual | visual | visual |
| Consistency (menu) | Cohérence | Coherencia | Konsistenz | Coerenza | Consistentie | Coerência |
| Reminders (page) | Relances | Recordatorios | Erinnerungen | Promemoria | Herinneringen | Lembretes |
| Import / Export | Import / Export | Importar / Exportar | Import / Export | Importazione / Esportazione | Importeren / Exporteren | Importar / Exportar |
| History (log) | Historique | Historial | Verlauf | Cronologia | Geschiedenis | Histórico |
| Administration | Administration | Administración | Administration | Amministrazione | Beheer | Administração |
| Settings | Paramètres | Configuración | Einstellungen | Impostazioni | Instellingen | Definições |
| My account | Mon compte | Mi cuenta | Mein Konto | Il mio account | Mijn account | A minha conta |
| Frameworks | Référentiels | Marcos de referencia | Berichtsrahmen | Quadri di riferimento | Kaders | Referenciais |
| Languages | Langues | Idiomas | Sprachen | Lingue | Talen | Línguas |
| identity (of the installation) | identité | identidad | Identität | identità | identiteit | identidade |
| reference language, default language | langue de référence, par défaut | idioma de referencia, predeterminado | Referenzsprache, Standardsprache | lingua di riferimento, predefinita | referentietaal, standaardtaal | língua de referência, predefinida |
| translation | traduction | traducción | Übersetzung | traduzione | vertaling | tradução |
| setup (wizard) | mise en place (assistant) | puesta en marcha (asistente) | Einrichtung (Assistent) | configurazione iniziale (procedura guidata) | installatie-assistent | configuração inicial (assistente) |
| appearance (light, dark, automatic) | – | – | – | – | uiterlijk (licht, donker, automatisch) | aspeto (claro, escuro, automático) |
| late (behind the expected pace) | – | – | – | – | achter, achterstand | em atraso |
| match, link (labels of a former system) | – | – | – | – | koppelen, overeenkomst | ligar, correspondência |
| assistant token | – | – | – | – | token | token |
| role (of a person) | – | – | – | – | – | função |
| tab, sheet (of a workbook) | – | – | – | – | – | separador, folha |
| workbook (Excel) | – | – | – | – | – | livro |
| trash (deleted items) | – | – | – | – | – | reciclagem |
| installation (of the tool) | installation | instalación | Installation | installazione | installatie | instalação |
| backup, restore | sauvegarde, restauration | copia de seguridad, restauración | Sicherung, Wiederherstellung | backup, ripristino | back-up, herstel | cópia de segurança, restauro |
| hosting | hébergement | alojamiento | Hosting | hosting | hosting | alojamento |
| Data and privacy | Données et confidentialité | Datos y privacidad | Daten und Datenschutz | Dati e privacy | Gegevens en privacy | Dados e privacidade |
| assistants (MCP server) | assistants | asistentes | Assistenten | assistenti | assistenten | assistentes |

### 2.5 Actions

One verb per action, in every language. A button uses the form given in section 4.

| English | French | Spanish | German | Italian | Dutch | Portuguese |
|---|---|---|---|---|---|---|
| sign in, sign out | se connecter, se déconnecter | iniciar sesión, cerrar sesión | anmelden, abmelden | accedere, uscire | inloggen, uitloggen | iniciar sessão, terminar sessão |
| click | cliquer | hacer clic | klicken | fare clic | klikken | clicar |
| select, deselect (a box) | cocher, décocher | marcar, desmarcar | auswählen, abwählen | selezionare, deselezionare | aanvinken, uitvinken | assinalar, desassinalar |
| choose (in a list) | choisir | elegir | wählen | scegliere | kiezen | escolher |
| turn on, turn off | activer, désactiver | activar, desactivar | aktivieren, deaktivieren | attivare, disattivare | inschakelen, uitschakelen | ativar, desativar |
| save | enregistrer | guardar | speichern | salvare | opslaan | guardar |
| Save changes (button of a form that edits something existing: the same label on every page) | Enregistrer les modifications | Guardar los cambios | Änderungen speichern | Salva le modifiche | Wijzigingen opslaan | Guardar as alterações |
| cancel | annuler | cancelar | abbrechen | annullare | annuleren | cancelar |
| undo | annuler (la dernière action) | deshacer | rückgängig machen | annullare l'ultima azione | ongedaan maken | anular |
| delete (for good) | supprimer | eliminar | löschen | eliminare | verwijderen | eliminar |
| remove (from a list) | retirer | quitar | entfernen | rimuovere | weghalen | remover |
| create, add | créer, ajouter | crear, añadir | anlegen, hinzufügen | creare, aggiungere | aanmaken, toevoegen | criar, adicionar |
| edit, change | modifier | modificar | bearbeiten, ändern | modificare | bewerken, wijzigen | editar, alterar |
| import (data), add (evidence) | importer, ajouter | importar, añadir | importieren, hinzufügen | importare, aggiungere | importeren, toevoegen | importar, adicionar |
| export, download | exporter, télécharger | exportar, descargar | exportieren, herunterladen | esportare, scaricare | exporteren, downloaden | exportar, transferir |
| validate | valider | validar | validieren | convalidare | valideren | validar |
| approve, reject | accepter, refuser | aceptar, rechazar | genehmigen, ablehnen | approvare, rifiutare | goedkeuren, afwijzen | aprovar, rejeitar |
| reopen | rouvrir | reabrir | erneut öffnen | riaprire | heropenen | reabrir |
| show | afficher | mostrar | anzeigen | mostrare | tonen | mostrar |
| display (the Display menu of filters) | affichage | visualización | Anzeige | visualizzazione | weergave-opties | apresentação |
| search, filter | rechercher, filtrer | buscar, filtrar | suchen, filtern | cercare, filtrare | zoeken, filteren | pesquisar, filtrar |
| apply, clear (filters) | appliquer, effacer | aplicar, borrar | anwenden, zurücksetzen | applicare, cancellare | toepassen, wissen | aplicar, limpar |
| close, back, previous, next | fermer, retour, précédent, suivant | cerrar, volver, anterior, siguiente | schließen, zurück, zurück, weiter | chiudere, indietro, precedente, avanti | sluiten, terug, vorige, volgende | fechar, voltar, anterior, seguinte |
| confirm | confirmer | confirmar | bestätigen | confermare | bevestigen | confirmar |

### 2.6 Terms added while translating

Added during the Italian translation. Only the Italian column is settled; "–" is to complete by the person who
translates the other languages.

| English | French | Spanish | German | Italian | Dutch | Portuguese |
|---|---|---|---|---|---|---|
| token (assistant access key) | jeton | – | – | token | – | – |
| space manager | gestionnaire des espaces | – | – | gestore degli spazi | – | – |
| workbook (Excel) | classeur | – | – | cartella di lavoro | – | – |
| trash, recently deleted | corbeille, supprimés récemment | – | – | cestino, eliminati di recente | – | – |
| fallback (text shown when a translation is missing) | repli | – | – | ripiego | – | – |
| dismiss (an alert) | ignorer | – | – | ignorare | – | – |
| finding (result of a consistency check) | constat | – | – | rilievo | – | – |
| AI (assistant) | IA | – | – | IA | – | – |
| tab (of a page or a menu) | onglet | – | – | scheda | – | – |
| preview | aperçu | – | – | anteprima | – | – |
| evidence (short column heading) | preuve | Justif. (heading only) | – | Giustif. (heading only, the full word does not fit) | – | – |
| subsidiary (level name in the demo) | filiale | filial | Tochtergesellschaft | filiale | dochteronderneming | filial |
| variance vs N-1 (short column heading) | Écart N-1 | Desv. N-1 (heading only; the full "Desviación respecto a N-1" stays in the text and the panel) | Abw. zu N-1 | Scostamento N-1 | Afw. t.o.v. N-1 | Desvio N-1 |

## 3. Language settings (in the label files, not in the code)

A new language sets its own number and date formats in its label files. Set these keys with the values below.

| Key | File | fr | es | de | it | nl | pt |
|---|---|---|---|---|---|---|---|
| `format.milliers` (thousands) | `visualisation.<lang>.json` | narrow no-break space | `.` | `.` | `.` | `.` | no-break space |
| `format.decimal` | same | `,` | `,` | `,` | `,` | `,` | `,` |
| `format.pourcent` | same | `{valeur} %` (narrow no-break space) | same as fr | same as fr | `{valeur}%` | `{valeur}%` | `{valeur}%` |
| `format.zero_singulier` | same | `1` | `0` | `0` | `0` | `0` | `0` |
| `cadre.langue.nom` (own name) | `cadre.<lang>.json` | Français | Español | Deutsch | Italiano | Nederlands | Português |
| `saisie.date_longue` | `saisie.<lang>.json` | `{jour} {mois} {annee}` | `{jour} de {mois} de {annee}` | `{jour}. {mois} {annee}` | `{jour} {mois} {annee}` | `{jour} {mois} {annee}` | `{jour} de {mois} de {annee}` |

`format.zero_singulier` is `1` when 0 takes the singular form as 1 does (French). Then a plural `one` is used for 0 and 1.
Month names, quarter and half-year prefixes (German `Q1`, `H1`; Italian `T1`; Dutch `K1`) are already in
`collecte/periodes.py` for the six languages. The names of the languages in each language are `commun.langue_nom.<code>` (already
present in `cadre.en.json`, `cadre.fr.json` and `cadre.es.json` for all six).

## 4. Tone and mechanics by language

The reader is a busy person who is not an IT specialist, in a large group. Be formal, calm and short. The same meaning
and the same parameters as in English: do not add or remove information.

| | German (de) | Italian (it) | Dutch (nl) | Portuguese (pt) |
|---|---|---|---|---|
| Form of address | **Sie**, always capitalised. Write "Sie" only when needed: "Geben Sie eine Zahl ein." | Impersonal and infinitive. No "tu", no "Lei" where the sentence can avoid it: "Selezionare un file.", "È possibile riaprire il valore." | **u** (formal). Prefer the infinitive or the imperative without pronoun: "Voer een getal in." Use "u" only when needed ("U kunt de waarde heropenen.") | **European Portuguese**, no "você": impersonal or the 3rd-person imperative: "Introduza um número.", "Pode reabrir o valor." |
| Instructions | Imperative with Sie: "Wählen Sie eine Datei." | Infinitive or impersonal: "Scegliere un file." | Imperative: "Kies een bestand." | 3rd-person imperative: "Escolha um ficheiro." |
| Buttons | Infinitive: "Speichern", "Exportieren" (noun only when the verb is unclear) | Short imperative form that is also the usual button form: "Salva", "Esporta", "Annulla" | Infinitive: "Opslaan", "Exporteren" | Infinitive: "Guardar", "Exportar" |
| Menus, tabs, titles | Noun | Noun | Noun | Noun |
| Capitals | German capitalises every noun. Everything else as a sentence ("Neue Kampagne anlegen"). | Sentence case | Sentence case | Sentence case |
| Quotation marks | „…“ | «…» | “…” | «…» |
| Space before `: ; ? !` | none | none | none | none |
| Numbers | `1.240,5` | `1.240,5` | `1.240,5` | `1 240,5` (no-break space) |
| Percentages | `12,5 %` (no-break space) | `12,5%` | `12,5%` | `12,5%` |
| Dates (sentences) | `4. November 2026` | `4 novembre 2026` | `4 november 2026` | `4 de novembro de 2026` |
| Variant and spelling | Germany; current spelling (ß after a long vowel, "ss" after a short one) | Italy | Netherlands; current spelling ("e-mail", "back-up") | Portugal; Acordo Ortográfico 1990 ("fator", "ativar", "ficheiro", "ecrã", "palavra-passe", "utilizador") |
| Gender | Avoid pronouns for people. Use "Person", "Konto" or the role noun as in the glossary. | Role nouns as in the glossary | Role nouns as in the glossary | Role nouns as in the glossary |
| Compound words | Join the noun cluster with hyphens when long ("KPI-Berichtsrahmen"). Keep a button under 20 characters. | n/a | One word as Dutch does ("organisatiestructuur") | n/a |
| Separate "you" words | "Ihr", "Ihre" when needed | "il vostro" avoided | "uw" | "o seu" |

Rules for every language:

- A button is 1 to 3 words, a tab and a column heading 1 to 3 words. If the language is longer than English by more
  than 60%, find a shorter synonym from this glossary or a shorter form (German: "Zuweisen" for "Assign", not
  "Zuweisung vornehmen").
- Never leave an English word that has a glossary word. Keep English only for the "do not translate" list.
- `email` in English; "E-Mail" (de), "e-mail" (it, nl), "email" (pt).
- Text with `{n}` and a plural: write both forms. Dutch, German, Italian and Portuguese use the English split: 1 is `one`,
  every other number, 0 included, is `other`.
- Keep the same tags as in English. Do not add a tag, a link or an emoji.
- Where the English asks a question to confirm an action, the confirm button repeats the verb of the action.

## 5. Choices to confirm

| Choice | Why | Confirm with |
|---|---|---|
| Portuguese: **European**, not Brazilian | Chosen for the first translation | The maintainer, then a native reader |
| Dutch: formal **u** | Large groups, professional tool. Many modern tools use "je". | The maintainer, then a native reader |
| Italian: impersonal and infinitive, button imperative | Usual form of business software, avoids "Lei" and "tu" | A native reader |
| German roles: "Mitwirkender", "Leser" (generic masculine in the role names only) | Business software convention; the rest of the text avoids gender | A native reader |
| German "Berichtsrahmen" for framework, "Bereich" for space | No single usual word; check on screen | A native reader |
| Dashboard: "Dashboard" (de, nl), "Cruscotto" (it), "Painel de controlo" (pt) | Usual word in each language | A native reader |
| Portuguese: "Provas" as the short column heading for "comprovativo" (evidence) | "Comprovativos" and "Comprov." did not fit the column of Data entry | A native reader |
| Portuguese: "reciclagem" for the trash of deleted items, "livro" for an Excel workbook | Usual words of Portuguese (Portugal) software | A native reader |

## 6. ESRS terms (library templates)

Used in the texts of the eleven ESRS templates (`referentiel/bibliotheque/traductions/esrs.<language>.json`), the same word in every template. Same tone rules as section 4. To be reviewed by native speakers.

| English | Spanish | German | Italian | Dutch | Portuguese |
|---|---|---|---|---|---|
| sustainability statement | declaración de sostenibilidad | Nachhaltigkeitserklärung | rendicontazione di sostenibilità | duurzaamheidsverklaring | declaração de sustentabilidade |
| impacts, risks and opportunities | impactos, riesgos y oportunidades | Auswirkungen, Risiken und Chancen | impatti, rischi e opportunità | effecten, risico's en kansen | impactos, riscos e oportunidades |
| material (topic) | material | wesentlich | rilevante | materieel | material |
| value chain (upstream, downstream) | cadena de valor (ascendente, descendente) | Wertschöpfungskette (vor-, nachgelagert) | catena del valore (a monte, a valle) | waardeketen (upstream, downstream) | cadeia de valor (a montante, a jusante) |
| stakeholders | partes interesadas | Interessenträger | portatori di interessi | belanghebbenden | partes interessadas |
| policies, actions, targets, metrics | políticas, acciones, metas, parámetros | Konzepte, Maßnahmen, Ziele, Kennzahlen | politiche, azioni, obiettivi, metriche | beleid, acties, streefdoelen, metrieken | políticas, ações, metas, métricas |
| own workforce | personal propio | eigene Belegschaft | forza lavoro propria | eigen personeel | trabalhadores próprios |
| affected communities | colectivos afectados | betroffene Gemeinschaften | comunità interessate | getroffen gemeenschappen | comunidades afetadas |
| business conduct | conducta empresarial | Unternehmensführung | condotta delle imprese | zakelijk gedrag | conduta empresarial |
| GHG, scope 1, 2, 3 | GEI, alcance 1, 2, 3 | THG, Scope 1, 2, 3 | GHG, ambito 1, 2, 3 | broeikasgas, scope 1, 2, 3 | GEE, âmbito 1, 2, 3 |
| removals, carbon credits | absorciones, créditos de carbono | Entnahmen, CO2-Gutschriften | assorbimenti, crediti di carbonio | verwijderingen, koolstofkredieten | remoções, créditos de carbono |
| transition plan | plan de transición | Übergangsplan | piano di transizione | transitieplan | plano de transição |
| due diligence | diligencia debida | Sorgfaltspflicht | dovuta diligenza | due diligence | dever de diligência |
| grievance mechanism, remediation | mecanismo de reclamación, reparación | Beschwerdemechanismus, Abhilfe | meccanismo di reclamo, rimedio | klachtenmechanisme, herstel | mecanismo de reclamação, reparação |
| administrative, management and supervisory bodies | órganos de administración, de dirección y de supervisión | Verwaltungs-, Leitungs- und Aufsichtsorgane | organi di amministrazione, direzione e controllo | bestuurs-, leidinggevende en toezichthoudende organen | órgãos de administração, de direção e de fiscalização |
| waste diverted from disposal | residuos desviados de la eliminación | von der Beseitigung ausgenommene Abfälle | rifiuti deviati dallo smaltimento | van verwijdering afgeleid afval | resíduos desviados da eliminação |
| EU ETS | RCDE UE | EU-EHS | ETS UE | EU-ETS | CELE-UE |

Open points for the native reviewers: Spanish "parámetros" for metrics (official wording) against "indicadores" for KPIs; German "Konzepte" for policies (as in the framework names); Portuguese "trabalhadores próprios" and "CELE-UE"; Dutch "metrieken"; Italian "corruzione" for corruption or bribery.
