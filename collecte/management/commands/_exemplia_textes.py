"""Démo Exemplia : tous les textes que la démo écrit elle-même, dans les sept langues de l'interface.

Un jeu de textes par langue : la commande ``load_demo`` charge la démo dans une langue (celle de l'installation, ou
``--language``) et écrit les textes de cette langue (commentaires, justifications, textes rédigés, noms de vues, noms
des organisations qui se traduisent, titres des justificatifs). Les valeurs chiffrées et les clés des réponses à liste
ne dépendent jamais de la langue. Les noms propres fictifs (Exemplia, noms de filiales, de villes, de personnes) ne se
traduisent pas.

L'anglais est la langue de base ; le français est la langue de référence de l'installation (les clés des listes de choix
sont en français). ``texte(cle)`` renvoie le texte de la langue réglée par ``regler`` (français par défaut).
"""
from contextlib import contextmanager
from contextvars import ContextVar

LANGUES = ("en", "fr", "es", "de", "it", "nl", "pt")

_langue = ContextVar("exemplia_langue", default="fr")
T = {}


def langue():
    return _langue.get()


@contextmanager
def regler(code):
    jeton = _langue.set(code)
    try:
        yield
    finally:
        _langue.reset(jeton)


def _p(cle, **par_langue):
    T[cle] = par_langue


def texte(cle, **valeurs):
    """Texte de la langue courante ; ``valeurs`` remplit les paramètres {annee}, {sites}…"""
    t = T[cle][_langue.get()]
    return t.format(**valeurs) if valeurs else t


# ---------------------------------------------------------------- identité de l'installation
_p("SOUS_TITRE", fr="Exemplia · démo", en="Exemplia · demo", es="Exemplia · demo", de="Exemplia · Demo", it="Exemplia · demo",
   nl="Exemplia · demo", pt="Exemplia · demo")
_p("CONTACT", fr="l'équipe Développement durable", en="the Sustainability team", es="el equipo de Desarrollo sostenible",
   de="das Nachhaltigkeitsteam", it="il team Sostenibilità", nl="het team Duurzaamheid", pt="a equipa de Sustentabilidade")

# ---------------------------------------------------------------- noms d'organisations qui se traduisent (la clé est le nom français)
NOMS_ORGANISATIONS = {
    "Exemplia Groupe": dict(en="Exemplia Group", es="Grupo Exemplia", de="Exemplia Gruppe", it="Gruppo Exemplia", nl="Exemplia Groep",
                            pt="Grupo Exemplia"),
    "France": dict(en="France", es="Francia", de="Frankreich", it="Francia", nl="Frankrijk", pt="França"),
    "Espagne": dict(en="Spain", es="España", de="Spanien", it="Spagna", nl="Spanje", pt="Espanha"),
    "Allemagne": dict(en="Germany", es="Alemania", de="Deutschland", it="Germania", nl="Duitsland", pt="Alemanha"),
    "Siège de Lyon": dict(en="Lyon head office", es="Sede de Lyon", de="Hauptsitz Lyon", it="Sede di Lyon", nl="Hoofdkantoor Lyon",
                          pt="Sede de Lyon"),
    "Usine de Villefranche": dict(en="Villefranche plant", es="Fábrica de Villefranche", de="Werk Villefranche",
                                  it="Stabilimento di Villefranche", nl="Fabriek Villefranche", pt="Fábrica de Villefranche"),
    "Usine de Roanne": dict(en="Roanne plant", es="Fábrica de Roanne", de="Werk Roanne", it="Stabilimento di Roanne",
                            nl="Fabriek Roanne", pt="Fábrica de Roanne"),
    "Entrepôt de Mâcon": dict(en="Mâcon warehouse", es="Almacén de Mâcon", de="Lager Mâcon", it="Magazzino di Mâcon",
                              nl="Magazijn Mâcon", pt="Armazém de Mâcon"),
    "Centre de tri de Vénissieux": dict(en="Vénissieux sorting centre", es="Centro de clasificación de Vénissieux",
                                        de="Sortierzentrum Vénissieux", it="Centro di smistamento di Vénissieux",
                                        nl="Sorteercentrum Vénissieux", pt="Centro de triagem de Vénissieux"),
}


def nom_organisation(cle):
    """Nom affiché de l'organisation de clé ``cle`` (son nom français) dans la langue courante."""
    return NOMS_ORGANISATIONS.get(cle, {}).get(_langue.get(), cle)


# ---------------------------------------------------------------- textes rédigés du groupe (Markdown)
_p("GEN-INTRO",
   fr="Exemplia conçoit et fabrique des emballages en carton ondulé pour l'industrie et la distribution. Ce rapport couvre les "
      "**cinq filiales** du groupe et leurs **{sites} sites** en France, en Espagne et en Allemagne.",
   en="Exemplia designs and manufactures corrugated cardboard packaging for industry and retail. This report covers the "
      "**five subsidiaries** of the group and their **{sites} sites** in France, Spain and Germany.",
   es="Exemplia diseña y fabrica envases de cartón ondulado para la industria y la distribución. Este informe abarca las "
      "**cinco filiales** del grupo y sus **{sites} centros** en Francia, España y Alemania.",
   de="Exemplia entwickelt und fertigt Verpackungen aus Wellpappe für Industrie und Handel. Dieser Bericht umfasst die "
      "**fünf Tochtergesellschaften** des Konzerns und ihre **{sites} Standorte** in Frankreich, Spanien und Deutschland.",
   it="Exemplia progetta e produce imballaggi in cartone ondulato per l'industria e la distribuzione. Questo rapporto riguarda "
      "le **cinque filiali** del gruppo e i suoi **{sites} siti** in Francia, Spagna e Germania.",
   nl="Exemplia ontwerpt en produceert verpakkingen van golfkarton voor industrie en distributie. Dit rapport omvat de "
      "**vijf dochterondernemingen** van de groep en hun **{sites} locaties** in Frankrijk, Spanje en Duitsland.",
   pt="A Exemplia concebe e fabrica embalagens de cartão canelado para a indústria e a distribuição. Este relatório abrange as "
      "**cinco filiais** do grupo e os seus **{sites} locais** em França, Espanha e Alemanha.")
_p("GEN-CONFORMITE",
   fr="Le présent rapport de durabilité d'Exemplia pour l'exercice {annee} a été établi conformément à la norme volontaire de "
      "publication d'informations en matière de durabilité (règlement délégué (UE) 2026/1560), modules de base et complet.",
   en="This sustainability report of Exemplia for the year {annee} has been prepared in accordance with the voluntary standard "
      "for sustainability reporting (Delegated Regulation (EU) 2026/1560), Basic and Comprehensive Modules.",
   es="Este informe de sostenibilidad de Exemplia correspondiente al ejercicio {annee} se ha elaborado de conformidad con la "
      "norma voluntaria de divulgación de información sobre sostenibilidad (Reglamento Delegado (UE) 2026/1560), módulos básico y completo.",
   de="Dieser Nachhaltigkeitsbericht von Exemplia für das Berichtsjahr {annee} wurde in Übereinstimmung mit dem freiwilligen "
      "Standard für die Nachhaltigkeitsberichterstattung (Delegierte Verordnung (EU) 2026/1560) erstellt, Basismodul und umfassendes Modul.",
   it="Il presente rapporto di sostenibilità di Exemplia per l'esercizio {annee} è stato redatto in conformità alla norma "
      "volontaria per l'informativa di sostenibilità (regolamento delegato (UE) 2026/1560), moduli di base e completo.",
   nl="Dit duurzaamheidsverslag van Exemplia voor verslagjaar {annee} is opgesteld in overeenstemming met de vrijwillige "
      "standaard voor duurzaamheidsrapportage (gedelegeerde verordening (EU) 2026/1560), basismodule en uitgebreide module.",
   pt="O presente relatório de sustentabilidade da Exemplia para o exercício {annee} foi elaborado em conformidade com a norma "
      "voluntária de divulgação de informação em matéria de sustentabilidade (Regulamento Delegado (UE) 2026/1560), módulos de base e completo.")
_p("GEN-CERTIF-DESC",
   fr="- **ISO 14001** (management environnemental) : usines de Villefranche, Roanne et Zaragoza, certifiées par un organisme "
      "accrédité depuis 2019, renouvelées en {renouvellement}.\n- **ISO 45001** (santé et sécurité) : usine de Leipzig, depuis "
      "2022.\n- **Chaîne de contrôle FSC®** : tous les sites de production.",
   en="- **ISO 14001** (environmental management): Villefranche, Roanne and Zaragoza plants, certified by an accredited body "
      "since 2019, renewed in {renouvellement}.\n- **ISO 45001** (health and safety): Leipzig plant, since 2022.\n- **FSC® chain "
      "of custody**: all production sites.",
   es="- **ISO 14001** (gestión ambiental): fábricas de Villefranche, Roanne y Zaragoza, certificadas por un organismo "
      "acreditado desde 2019 y renovadas en {renouvellement}.\n- **ISO 45001** (seguridad y salud): fábrica de Leipzig, desde "
      "2022.\n- **Cadena de custodia FSC®**: todos los centros de producción.",
   de="- **ISO 14001** (Umweltmanagement): Werke Villefranche, Roanne und Zaragoza, seit 2019 von einer akkreditierten Stelle "
      "zertifiziert, {renouvellement} erneuert.\n- **ISO 45001** (Arbeitsschutz): Werk Leipzig, seit 2022.\n- **FSC®-Chain-of-"
      "Custody**: alle Produktionsstandorte.",
   it="- **ISO 14001** (gestione ambientale): stabilimenti di Villefranche, Roanne e Zaragoza, certificati da un organismo "
      "accreditato dal 2019 e rinnovati nel {renouvellement}.\n- **ISO 45001** (salute e sicurezza): stabilimento di Leipzig, dal "
      "2022.\n- **Catena di custodia FSC®**: tutti i siti produttivi.",
   nl="- **ISO 14001** (milieumanagement): fabrieken in Villefranche, Roanne en Zaragoza, sinds 2019 gecertificeerd door een "
      "geaccrediteerde instelling, vernieuwd in {renouvellement}.\n- **ISO 45001** (gezondheid en veiligheid): fabriek in "
      "Leipzig, sinds 2022.\n- **FSC®-chain of custody**: alle productielocaties.",
   pt="- **ISO 14001** (gestão ambiental): fábricas de Villefranche, Roanne e Zaragoza, certificadas por um organismo acreditado "
      "desde 2019 e renovadas em {renouvellement}.\n- **ISO 45001** (saúde e segurança): fábrica de Leipzig, desde 2022.\n- "
      "**Cadeia de custódia FSC®**: todos os locais de produção.")
_p("ECO-CIRCULAIRE-DESC",
   fr="- Matière première : **{recycle} %** de papier et carton recyclés.\n- Écoconception : emballages mono-matériau, sans "
      "plastique, conçus pour être recyclés.\n- Palettes en bois réparées et réemployées entre les sites.\n- Chutes de production "
      "reprises par le centre de tri de Vénissieux.",
   en="- Raw material: **{recycle}%** recycled paper and board.\n- Ecodesign: single-material packaging, plastic-free, designed "
      "to be recycled.\n- Wooden pallets repaired and reused between sites.\n- Production offcuts taken back by the Vénissieux "
      "sorting centre.",
   es="- Materia prima: **{recycle} %** de papel y cartón reciclados.\n- Ecodiseño: envases monomaterial, sin plástico, concebidos "
      "para ser reciclados.\n- Palés de madera reparados y reutilizados entre los centros.\n- Recortes de producción recuperados "
      "por el centro de clasificación de Vénissieux.",
   de="- Rohstoff: **{recycle} %** Altpapier und Recyclingkarton.\n- Ökodesign: Monomaterial-Verpackungen ohne Kunststoff, auf "
      "Recycling ausgelegt.\n- Holzpaletten werden repariert und zwischen den Standorten wiederverwendet.\n- Produktionsabschnitte "
      "nimmt das Sortierzentrum Vénissieux zurück.",
   it="- Materia prima: **{recycle}%** di carta e cartone riciclati.\n- Ecodesign: imballaggi monomateriale, senza plastica, "
      "progettati per essere riciclati.\n- Pallet in legno riparati e riutilizzati tra i siti.\n- Ritagli di produzione recuperati "
      "dal centro di smistamento di Vénissieux.",
   nl="- Grondstof: **{recycle}%** gerecycled papier en karton.\n- Ecodesign: verpakkingen van één materiaal, zonder plastic, "
      "ontworpen om te worden gerecycled.\n- Houten pallets worden hersteld en hergebruikt tussen de locaties.\n- Productiesnippers "
      "worden teruggenomen door het sorteercentrum in Vénissieux.",
   pt="- Matéria-prima: **{recycle}%** de papel e cartão reciclados.\n- Ecodesign: embalagens de um só material, sem plástico, "
      "concebidas para serem recicladas.\n- Paletes de madeira reparadas e reutilizadas entre os locais.\n- Aparas de produção "
      "recuperadas pelo centro de triagem de Vénissieux.")
_p("STR-PRODUITS",
   fr="Caisses et barquettes en carton ondulé, présentoirs pour la distribution, emballages de protection sur mesure ; "
      "recyclage de papiers et cartons usagés (Exemplia Recyclage).",
   en="Corrugated cardboard boxes and trays, retail display units, custom protective packaging; recycling of used paper and "
      "board (Exemplia Recyclage).",
   es="Cajas y bandejas de cartón ondulado, expositores para la distribución, envases de protección a medida; reciclaje de papel "
      "y cartón usados (Exemplia Recyclage).",
   de="Kisten und Schalen aus Wellpappe, Displays für den Handel, maßgefertigte Schutzverpackungen; Recycling von Altpapier und "
      "Altkarton (Exemplia Recyclage).",
   it="Scatole e vassoi in cartone ondulato, espositori per la distribuzione, imballaggi protettivi su misura; riciclo di carta "
      "e cartone usati (Exemplia Recyclage).",
   nl="Dozen en trays van golfkarton, displays voor de detailhandel, beschermende verpakkingen op maat; recycling van gebruikt "
      "papier en karton (Exemplia Recyclage).",
   pt="Caixas e tabuleiros de cartão canelado, expositores para a distribuição, embalagens de proteção por medida; reciclagem de "
      "papel e cartão usados (Exemplia Recyclage).")
_p("STR-MARCHES",
   fr="Clients industriels et de la distribution (B2B), surtout en France, en Espagne et en Allemagne ; agroalimentaire, "
      "boissons et produits d'hygiène.",
   en="Industrial and retail customers (B2B), mainly in France, Spain and Germany; food, beverages and hygiene products.",
   es="Clientes industriales y de la distribución (B2B), sobre todo en Francia, España y Alemania; alimentación, bebidas y "
      "productos de higiene.",
   de="Kunden aus Industrie und Handel (B2B), vor allem in Frankreich, Spanien und Deutschland; Lebensmittel, Getränke und "
      "Hygieneprodukte.",
   it="Clienti industriali e della distribuzione (B2B), soprattutto in Francia, Spagna e Germania; alimentare, bevande e "
      "prodotti per l'igiene.",
   nl="Klanten uit industrie en detailhandel (B2B), vooral in Frankrijk, Spanje en Duitsland; voeding, dranken en "
      "hygiëneproducten.",
   pt="Clientes industriais e da distribuição (B2B), sobretudo em França, Espanha e Alemanha; alimentação, bebidas e produtos "
      "de higiene.")
_p("STR-RELATIONS",
   fr="Fournisseurs de papier recyclé et de papier kraft certifiés, transporteurs routiers sous contrat, une centaine de "
      "clients réguliers dont dix réalisent la moitié du chiffre d'affaires.",
   en="Certified recycled-paper and kraft-paper suppliers, contracted road hauliers, about a hundred regular customers of which "
      "ten account for half of the revenue.",
   es="Proveedores de papel reciclado y de papel kraft certificados, transportistas por carretera con contrato, un centenar de "
      "clientes habituales, diez de los cuales generan la mitad de la facturación.",
   de="Zertifizierte Lieferanten von Recyclingpapier und Kraftpapier, Straßentransporteure unter Vertrag, rund hundert "
      "Stammkunden, von denen zehn die Hälfte des Umsatzes erzielen.",
   it="Fornitori certificati di carta riciclata e di carta kraft, trasportatori su strada con contratto, un centinaio di clienti "
      "abituali, dieci dei quali realizzano metà del fatturato.",
   nl="Gecertificeerde leveranciers van gerecycled papier en kraftpapier, wegtransporteurs onder contract, ongeveer honderd "
      "vaste klanten, van wie er tien de helft van de omzet realiseren.",
   pt="Fornecedores certificados de papel reciclado e de papel kraft, transportadores rodoviários contratados, cerca de cem "
      "clientes habituais, dos quais dez realizam metade do volume de negócios.")
_p("STR-ENJEUX-DESC",
   fr="La stratégie **« Carton 2030 »** vise 90 % de fibres recyclées, la baisse des émissions de l'énergie et le remplacement "
      "des emballages plastiques des clients par du carton.",
   en="The **“Cardboard 2030”** strategy aims for 90 % recycled fibres, lower energy-related emissions and replacing "
      "customers' plastic packaging with cardboard.",
   es="La estrategia **«Cartón 2030»** persigue un 90 % de fibras recicladas, la reducción de las emisiones de la energía y la "
      "sustitución de los envases de plástico de los clientes por cartón.",
   de="Die Strategie **„Karton 2030“** zielt auf 90 % Recyclingfasern, geringere energiebedingte Emissionen und den Ersatz von "
      "Kunststoffverpackungen der Kunden durch Karton.",
   it="La strategia **«Cartone 2030»** punta al 90% di fibre riciclate, alla riduzione delle emissioni legate all'energia e alla "
      "sostituzione degli imballaggi in plastica dei clienti con il cartone.",
   nl="De strategie **“Karton 2030”** mikt op 90% gerecyclede vezels, lagere emissies uit energie en het vervangen van "
      "plastic verpakkingen van klanten door karton.",
   pt="A estratégia **«Cartão 2030»** visa 90% de fibras recicladas, a redução das emissões da energia e a substituição das "
      "embalagens de plástico dos clientes por cartão.")
_p("GOV-C2-DESC",
   fr="Politique environnementale (énergie, eau, déchets), politique santé et sécurité, code de conduite et charte achats "
      "responsables. Ces textes sont publiés sur le site internet du groupe.",
   en="Environmental policy (energy, water, waste), health and safety policy, code of conduct and responsible purchasing "
      "charter. These documents are published on the group's website.",
   es="Política ambiental (energía, agua, residuos), política de seguridad y salud, código de conducta y carta de compras "
      "responsables. Estos documentos se publican en el sitio web del grupo.",
   de="Umweltpolitik (Energie, Wasser, Abfall), Arbeitsschutzpolitik, Verhaltenskodex und Charta für verantwortungsvollen "
      "Einkauf. Diese Dokumente sind auf der Website des Konzerns veröffentlicht.",
   it="Politica ambientale (energia, acqua, rifiuti), politica di salute e sicurezza, codice di condotta e carta degli acquisti "
      "responsabili. Questi documenti sono pubblicati sul sito web del gruppo.",
   nl="Milieubeleid (energie, water, afval), beleid voor gezondheid en veiligheid, gedragscode en handvest voor verantwoord "
      "inkopen. Deze documenten staan op de website van de groep.",
   pt="Política ambiental (energia, água, resíduos), política de saúde e segurança, código de conduta e carta de compras "
      "responsáveis. Estes documentos estão publicados no sítio web do grupo.")
_p("GOV-C2-CIBLES",
   fr="- Émissions des scopes 1 et 2 : **-42 %** en 2030 par rapport à 2023.\n- Taux de fréquence des accidents divisé par deux "
      "d'ici 2027.\n- 100 % d'électricité renouvelable en France dès 2027.",
   en="- Scope 1 and 2 emissions: **-42 %** in 2030 compared with 2023.\n- Accident frequency rate halved by 2027.\n- 100 % "
      "renewable electricity in France from 2027.",
   es="- Emisiones de los alcances 1 y 2: **-42 %** en 2030 respecto a 2023.\n- Tasa de frecuencia de accidentes reducida a la "
      "mitad de aquí a 2027.\n- 100 % de electricidad renovable en Francia desde 2027.",
   de="- Emissionen der Scopes 1 und 2: **-42 %** im Jahr 2030 gegenüber 2023.\n- Unfallhäufigkeitsrate bis 2027 halbiert.\n- "
      "100 % Ökostrom in Frankreich ab 2027.",
   it="- Emissioni degli ambiti 1 e 2: **-42%** nel 2030 rispetto al 2023.\n- Tasso di frequenza degli infortuni dimezzato entro "
      "il 2027.\n- 100% di elettricità rinnovabile in Francia dal 2027.",
   nl="- Emissies van scope 1 en 2: **-42%** in 2030 ten opzichte van 2023.\n- Ongevallenfrequentie gehalveerd tegen 2027.\n- "
      "100% hernieuwbare elektriciteit in Frankrijk vanaf 2027.",
   pt="- Emissões dos âmbitos 1 e 2: **-42%** em 2030 face a 2023.\n- Taxa de frequência de acidentes reduzida para metade até "
      "2027.\n- 100% de eletricidade renovável em França a partir de 2027.")
_p("GOV-C2-RESPONSABLE",
   fr="Le directeur général, avec la directrice du développement durable, membre du comité exécutif.",
   en="The chief executive officer, together with the sustainability director, a member of the executive committee.",
   es="El director general, junto con la directora de desarrollo sostenible, miembro del comité ejecutivo.",
   de="Die Geschäftsführung gemeinsam mit der Leiterin Nachhaltigkeit, Mitglied der Geschäftsleitung.",
   it="Il direttore generale, insieme alla direttrice dello sviluppo sostenibile, membro del comitato esecutivo.",
   nl="De algemeen directeur, samen met de directeur duurzaamheid, lid van het directiecomité.",
   pt="O diretor-geral, com a diretora de desenvolvimento sustentável, membro da comissão executiva.")
_p("GES-ACTIONS",
   fr="1. Chaudière biomasse à Leipzig (en service depuis mars 2025).\n2. Extension des panneaux solaires à Villefranche et "
      "Zaragoza.\n3. Contrats d'électricité renouvelable pour tous les sites français.\n4. Récupération de chaleur sur les "
      "onduleuses.\n5. Chariots élévateurs électriques dans les entrepôts.",
   en="1. Biomass boiler at Leipzig (in service since March 2025).\n2. Extension of the solar panels at Villefranche and "
      "Zaragoza.\n3. Renewable electricity contracts for all French sites.\n4. Heat recovery on the corrugators.\n5. Electric "
      "forklift trucks in the warehouses.",
   es="1. Caldera de biomasa en Leipzig (en servicio desde marzo de 2025).\n2. Ampliación de los paneles solares en Villefranche "
      "y Zaragoza.\n3. Contratos de electricidad renovable para todos los centros franceses.\n4. Recuperación de calor en las "
      "onduladoras.\n5. Carretillas elevadoras eléctricas en los almacenes.",
   de="1. Biomassekessel in Leipzig (in Betrieb seit März 2025).\n2. Ausbau der Solaranlagen in Villefranche und Zaragoza.\n3. "
      "Ökostromverträge für alle französischen Standorte.\n4. Wärmerückgewinnung an den Wellpappenanlagen.\n5. Elektrische "
      "Gabelstapler in den Lagern.",
   it="1. Caldaia a biomassa a Leipzig (in servizio da marzo 2025).\n2. Ampliamento dei pannelli solari a Villefranche e "
      "Zaragoza.\n3. Contratti di elettricità rinnovabile per tutti i siti francesi.\n4. Recupero di calore sulle linee di "
      "cartone ondulato.\n5. Carrelli elevatori elettrici nei magazzini.",
   nl="1. Biomassaketel in Leipzig (in gebruik sinds maart 2025).\n2. Uitbreiding van de zonnepanelen in Villefranche en "
      "Zaragoza.\n3. Contracten voor hernieuwbare elektriciteit voor alle Franse locaties.\n4. Warmteterugwinning op de "
      "golfkartonmachines.\n5. Elektrische heftrucks in de magazijnen.",
   pt="1. Caldeira de biomassa em Leipzig (em funcionamento desde março de 2025).\n2. Ampliação dos painéis solares em "
      "Villefranche e Zaragoza.\n3. Contratos de eletricidade renovável para todos os locais franceses.\n4. Recuperação de calor "
      "nas máquinas de cartão canelado.\n5. Empilhadores elétricos nos armazéns.")
_p("GES-PLAN-DESC",
   fr="Plan de transition adopté par le conseil d'administration le 27 novembre 2025 : trajectoire de réduction des scopes 1 et "
      "2 alignée sur 1,5 °C, sortie du fioul en 2026, investissements de 6 M€ sur cinq ans, suivi annuel en comité exécutif.",
   en="Transition plan adopted by the board of directors on 27 November 2025: scope 1 and 2 reduction pathway aligned with "
      "1.5 °C, phase-out of heating oil in 2026, investments of EUR 6 million over five years, annual follow-up by the executive "
      "committee.",
   es="Plan de transición adoptado por el consejo de administración el 27 de noviembre de 2025: trayectoria de reducción de los "
      "alcances 1 y 2 alineada con 1,5 °C, abandono del fuelóleo en 2026, inversiones de 6 M€ en cinco años, seguimiento anual "
      "en el comité ejecutivo.",
   de="Transitionsplan, am 27. November 2025 vom Verwaltungsrat verabschiedet: Reduktionspfad für Scope 1 und 2 im Einklang mit "
      "1,5 °C, Ausstieg aus Heizöl 2026, Investitionen von 6 Mio. € über fünf Jahre, jährliche Überprüfung in der "
      "Geschäftsleitung.",
   it="Piano di transizione adottato dal consiglio di amministrazione il 27 novembre 2025: traiettoria di riduzione degli ambiti "
      "1 e 2 allineata a 1,5 °C, uscita dall'olio combustibile nel 2026, investimenti di 6 M€ in cinque anni, monitoraggio annuale "
      "in comitato esecutivo.",
   nl="Transitieplan goedgekeurd door de raad van bestuur op 27 november 2025: reductiepad voor scope 1 en 2 in lijn met 1,5 °C, "
      "afbouw van stookolie in 2026, investeringen van 6 M€ over vijf jaar, jaarlijkse opvolging in het directiecomité.",
   pt="Plano de transição adotado pelo conselho de administração a 27 de novembro de 2025: trajetória de redução dos âmbitos 1 e "
      "2 alinhada com 1,5 °C, abandono do fuelóleo em 2026, investimentos de 6 M€ ao longo de cinco anos, acompanhamento anual "
      "na comissão executiva.")
_p("CLI-ALEAS",
   fr="- **Physiques** : canicules et sécheresses (sites espagnols, usine de Roanne), inondation du site de Leipzig.\n- "
      "**Transition** : hausse du prix du carbone et de l'énergie, exigences des clients sur les emballages.",
   en="- **Physical**: heatwaves and droughts (Spanish sites, Roanne plant), flooding of the Leipzig site.\n- **Transition**: "
      "higher carbon and energy prices, customer requirements on packaging.",
   es="- **Físicos**: olas de calor y sequías (centros españoles, fábrica de Roanne), inundación del centro de Leipzig.\n- **De "
      "transición**: alza del precio del carbono y de la energía, exigencias de los clientes sobre los envases.",
   de="- **Physische**: Hitzewellen und Dürren (spanische Standorte, Werk Roanne), Überschwemmung am Standort Leipzig.\n- "
      "**Übergangsbezogene**: höhere CO₂- und Energiepreise, Anforderungen der Kunden an Verpackungen.",
   it="- **Fisici**: ondate di calore e siccità (siti spagnoli, stabilimento di Roanne), alluvione del sito di Leipzig.\n- **Di "
      "transizione**: aumento del prezzo del carbonio e dell'energia, requisiti dei clienti sugli imballaggi.",
   nl="- **Fysieke**: hittegolven en droogte (Spaanse locaties, fabriek in Roanne), overstroming van de locatie in Leipzig.\n- "
      "**Transitie**: hogere prijzen voor koolstof en energie, eisen van klanten aan verpakkingen.",
   pt="- **Físicos**: ondas de calor e secas (locais espanhóis, fábrica de Roanne), inundação do local de Leipzig.\n- **De "
      "transição**: subida do preço do carbono e da energia, exigências dos clientes quanto às embalagens.")
_p("CLI-EXPOSITION",
   fr="Analyse des sites avec les données climatiques publiques (scénarios du GIEC) et entretiens avec les directeurs de site ; "
      "sensibilité des procédés à l'eau et à la chaleur, dépendance au gaz.",
   en="Analysis of the sites using public climate data (IPCC scenarios) and interviews with site managers; sensitivity of "
      "processes to water and heat, dependence on gas.",
   es="Análisis de los centros con datos climáticos públicos (escenarios del IPCC) y entrevistas con los directores de centro; "
      "sensibilidad de los procesos al agua y al calor, dependencia del gas.",
   de="Analyse der Standorte anhand öffentlicher Klimadaten (IPCC-Szenarien) und Gesprächen mit den Standortleitungen; "
      "Empfindlichkeit der Prozesse gegenüber Wasser und Hitze, Abhängigkeit von Gas.",
   it="Analisi dei siti con dati climatici pubblici (scenari dell'IPCC) e interviste con i responsabili dei siti; sensibilità dei "
      "processi all'acqua e al calore, dipendenza dal gas.",
   nl="Analyse van de locaties met openbare klimaatgegevens (IPCC-scenario's) en gesprekken met de locatiedirecteuren; "
      "gevoeligheid van de processen voor water en hitte, afhankelijkheid van gas.",
   pt="Análise dos locais com dados climáticos públicos (cenários do IPCC) e entrevistas com os diretores de local; "
      "sensibilidade dos processos à água e ao calor, dependência do gás.")
_p("CLI-HORIZONS",
   fr="Court terme (moins de 3 ans) : prix de l'énergie. Moyen terme (3 à 10 ans) : sécheresses en Espagne. Long terme "
      "(au-delà de 10 ans) : inondations à Leipzig.",
   en="Short term (less than 3 years): energy prices. Medium term (3 to 10 years): droughts in Spain. Long term (beyond 10 "
      "years): flooding in Leipzig.",
   es="Corto plazo (menos de 3 años): precio de la energía. Medio plazo (de 3 a 10 años): sequías en España. Largo plazo (más "
      "de 10 años): inundaciones en Leipzig.",
   de="Kurzfristig (unter 3 Jahren): Energiepreise. Mittelfristig (3 bis 10 Jahre): Dürren in Spanien. Langfristig (über 10 "
      "Jahre): Überschwemmungen in Leipzig.",
   it="Breve termine (meno di 3 anni): prezzo dell'energia. Medio termine (da 3 a 10 anni): siccità in Spagna. Lungo termine "
      "(oltre 10 anni): alluvioni a Leipzig.",
   nl="Korte termijn (minder dan 3 jaar): energieprijzen. Middellange termijn (3 tot 10 jaar): droogte in Spanje. Lange termijn "
      "(meer dan 10 jaar): overstromingen in Leipzig.",
   pt="Curto prazo (menos de 3 anos): preço da energia. Médio prazo (3 a 10 anos): secas em Espanha. Longo prazo (mais de 10 "
      "anos): inundações em Leipzig.")
_p("CLI-EFFETS",
   fr="Coût de l'énergie : risque **élevé** à court terme. Arrêts de production liés à l'eau : risque **moyen**. Dommages "
      "liés aux inondations : risque **faible**.",
   en="Energy cost: **high** risk in the short term. Water-related production stoppages: **medium** risk. Flood damage: "
      "**low** risk.",
   es="Coste de la energía: riesgo **alto** a corto plazo. Paradas de producción por falta de agua: riesgo **medio**. Daños por "
      "inundación: riesgo **bajo**.",
   de="Energiekosten: **hohes** Risiko kurzfristig. Produktionsstillstände wegen Wasser: **mittleres** Risiko. "
      "Hochwasserschäden: **geringes** Risiko.",
   it="Costo dell'energia: rischio **alto** a breve termine. Fermi di produzione legati all'acqua: rischio **medio**. Danni da "
      "alluvione: rischio **basso**.",
   nl="Energiekosten: **hoog** risico op korte termijn. Productiestops door water: **gemiddeld** risico. Schade door "
      "overstroming: **laag** risico.",
   pt="Custo da energia: risco **elevado** a curto prazo. Paragens de produção ligadas à água: risco **médio**. Danos de "
      "inundação: risco **baixo**.")
_p("SOC-CODE-AUTRE-DESC",
   fr="Harcèlement moral et sexuel, liberté d'association et droit à la négociation collective.",
   en="Bullying and sexual harassment, freedom of association and the right to collective bargaining.",
   es="Acoso moral y sexual, libertad de asociación y derecho a la negociación colectiva.",
   de="Mobbing und sexuelle Belästigung, Vereinigungsfreiheit und das Recht auf Tarifverhandlungen.",
   it="Molestie morali e sessuali, libertà di associazione e diritto alla contrattazione collettiva.",
   nl="Pesten en seksuele intimidatie, vrijheid van vereniging en recht op collectieve onderhandelingen.",
   pt="Assédio moral e sexual, liberdade de associação e direito à negociação coletiva.")

# ---------------------------------------------------------------- commentaires de saisie (réponses N/A, écarts, fermeture)
_p("BIOMASSE", fr="Chaudière biomasse en service depuis mars 2025 (plaquettes forestières).",
   en="Biomass boiler in service since March 2025 (wood chips).",
   es="Caldera de biomasa en servicio desde marzo de 2025 (astillas forestales).",
   de="Biomassekessel seit März 2025 in Betrieb (Waldhackschnitzel).",
   it="Caldaia a biomassa in servizio da marzo 2025 (cippato forestale).",
   nl="Biomassaketel in gebruik sinds maart 2025 (houtsnippers).",
   pt="Caldeira de biomassa em funcionamento desde março de 2025 (estilha florestal).")
_p("FERME_ELEC", fr="Site fermé le 30/06/2025 : six mois d'activité.", en="Site closed on 30 June 2025: six months of activity.",
   es="Centro cerrado el 30 de junio de 2025: seis meses de actividad.", de="Standort am 30. Juni 2025 geschlossen: sechs Monate Betrieb.",
   it="Sito chiuso il 30 giugno 2025: sei mesi di attività.", nl="Locatie gesloten op 30 juni 2025: zes maanden activiteit.",
   pt="Local encerrado a 30 de junho de 2025: seis meses de atividade.")
_p("FERME_EFF", fr="Site fermé le 30/06/2025 : salariés reclassés à Dortmund ou partis.",
   en="Site closed on 30 June 2025: employees moved to Dortmund or left.",
   es="Centro cerrado el 30 de junio de 2025: empleados reubicados en Dortmund o salidos de la empresa.",
   de="Standort am 30. Juni 2025 geschlossen: Beschäftigte nach Dortmund versetzt oder ausgeschieden.",
   it="Sito chiuso il 30 giugno 2025: dipendenti trasferiti a Dortmund o usciti.",
   nl="Locatie gesloten op 30 juni 2025: werknemers overgeplaatst naar Dortmund of vertrokken.",
   pt="Local encerrado a 30 de junho de 2025: trabalhadores transferidos para Dortmund ou saídos.")
_p("POL_NA", fr="Site non soumis à la déclaration des rejets de polluants.", en="Site not subject to pollutant release reporting.",
   es="Centro no sujeto a la declaración de emisiones de contaminantes.", de="Standort nicht meldepflichtig für Schadstoffemissionen.",
   it="Sito non soggetto alla dichiarazione delle emissioni di inquinanti.",
   nl="Locatie valt niet onder de rapportageplicht voor uitstoot van verontreinigende stoffen.",
   pt="Local não sujeito à declaração de emissões de poluentes.")
_p("ZONE_NA", fr="Aucune zone sensible à proximité.", en="No sensitive area nearby.", es="Ninguna zona sensible cerca.",
   de="Keine sensible Zone in der Nähe.", it="Nessuna zona sensibile nelle vicinanze.", nl="Geen gevoelig gebied in de buurt.",
   pt="Nenhuma zona sensível nas proximidades.")
_p("ZONE_ROANNE", fr="Site Natura 2000 « Gorges de la Loire »", en="Natura 2000 site “Gorges de la Loire”",
   es="Sitio Natura 2000 «Gorges de la Loire»", de="Natura-2000-Gebiet „Gorges de la Loire“", it="Sito Natura 2000 «Gorges de la Loire»",
   nl="Natura 2000-gebied “Gorges de la Loire”", pt="Sítio Natura 2000 «Gorges de la Loire»")
_p("ZONE_LEIPZIG", fr="Natura 2000 « Leipziger Auensystem »", en="Natura 2000 “Leipziger Auensystem”", es="Natura 2000 «Leipziger Auensystem»",
   de="Natura 2000 „Leipziger Auensystem“", it="Natura 2000 «Leipziger Auensystem»", nl="Natura 2000 “Leipziger Auensystem”",
   pt="Natura 2000 «Leipziger Auensystem»")
_p("FORME_AUTRE_NA", fr="Forme juridique de la liste (société par actions simplifiée).",
   en="Legal form from the list (simplified joint-stock company).", es="Forma jurídica de la lista (sociedad por acciones simplificada).",
   de="Rechtsform aus der Liste (vereinfachte Aktiengesellschaft).", it="Forma giuridica dell'elenco (società per azioni semplificata).",
   nl="Rechtsvorm uit de lijst (vereenvoudigde naamloze vennootschap).", pt="Forma jurídica da lista (sociedade por ações simplificada).")
_p("S3_ACTIFS_AMONT", fr="Aucun actif loué en amont hors des scopes 1 et 2.", en="No upstream leased assets outside scopes 1 and 2.",
   es="Ningún activo arrendado aguas arriba fuera de los alcances 1 y 2.",
   de="Keine vorgelagerten geleasten Vermögenswerte außerhalb von Scope 1 und 2.",
   it="Nessun bene in leasing a monte al di fuori degli ambiti 1 e 2.", nl="Geen geleasde activa stroomopwaarts buiten scope 1 en 2.",
   pt="Nenhum ativo arrendado a montante fora dos âmbitos 1 e 2.")
_p("S3_TRANSFO", fr="Emballages livrés prêts à l'emploi : pas de transformation chez les clients.",
   en="Packaging delivered ready to use: no processing at customers.",
   es="Envases entregados listos para usar: sin transformación en los clientes.",
   de="Verpackungen werden gebrauchsfertig geliefert: keine Weiterverarbeitung bei den Kunden.",
   it="Imballaggi consegnati pronti all'uso: nessuna trasformazione presso i clienti.",
   nl="Verpakkingen worden gebruiksklaar geleverd: geen verwerking bij de klanten.",
   pt="Embalagens entregues prontas a usar: sem transformação nos clientes.")
_p("S3_ACTIFS_AVAL", fr="Aucun actif donné en location.", en="No assets leased out.", es="Ningún activo arrendado a terceros.",
   de="Keine vermieteten Vermögenswerte.", it="Nessun bene concesso in locazione.", nl="Geen activa verhuurd.",
   pt="Nenhum ativo dado em arrendamento.")
_p("S3_FRANCHISES", fr="Pas de franchise.", en="No franchises.", es="Sin franquicias.", de="Keine Franchise.", it="Nessun franchising.",
   nl="Geen franchises.", pt="Sem franquias.")
_p("S3_INVEST", fr="Pas d'investissement financier significatif.", en="No significant financial investments.",
   es="Sin inversiones financieras significativas.", de="Keine wesentlichen Finanzinvestitionen.",
   it="Nessun investimento finanziario significativo.", nl="Geen significante financiële investeringen.",
   pt="Sem investimentos financeiros significativos.")
_p("PLAN_ADOPTE", fr="Plan adopté le 27/11/2025.", en="Plan adopted on 27 November 2025.", es="Plan adoptado el 27 de noviembre de 2025.",
   de="Plan am 27. November 2025 verabschiedet.", it="Piano adottato il 27 novembre 2025.", nl="Plan goedgekeurd op 27 november 2025.",
   pt="Plano adotado a 27 de novembro de 2025.")
_p("INCIDENT_AUTRE", fr="Aucun incident confirmé.", en="No confirmed incident.", es="Ningún incidente confirmado.",
   de="Kein bestätigter Vorfall.", it="Nessun incidente confermato.", nl="Geen bevestigd incident.", pt="Nenhum incidente confirmado.")
_p("INCIDENT_CHAINE", fr="Aucun incident confirmé dans la chaîne de valeur.", en="No confirmed incident in the value chain.",
   es="Ningún incidente confirmado en la cadena de valor.", de="Kein bestätigter Vorfall in der Wertschöpfungskette.",
   it="Nessun incidente confermato nella catena del valore.", nl="Geen bevestigd incident in de waardeketen.",
   pt="Nenhum incidente confirmado na cadeia de valor.")
_p("ECART_FUITE", fr="Fuite sur le groupe froid de l'atelier d'impression, réparée en mai.",
   en="Leak on the chiller of the printing workshop, repaired in May.",
   es="Fuga en el grupo de frío del taller de impresión, reparada en mayo.",
   de="Leckage am Kühlaggregat der Druckerei, im Mai repariert.",
   it="Perdita sul gruppo frigorifero del reparto stampa, riparata a maggio.",
   nl="Lek in de koelinstallatie van de drukkerij, in mei hersteld.",
   pt="Fuga no grupo de frio da oficina de impressão, reparada em maio.")
_p("ECART_CHALEUR", fr="Nouveau contrat avec le réseau de chaleur ; consigne de chauffage à 19 °C.",
   en="New contract with the district heating network; heating set to 19 °C.",
   es="Nuevo contrato con la red de calor; consigna de calefacción a 19 °C.",
   de="Neuer Vertrag mit dem Fernwärmenetz; Heizungssollwert 19 °C.",
   it="Nuovo contratto con la rete di teleriscaldamento; temperatura di riscaldamento a 19 °C.",
   nl="Nieuw contract met het warmtenet; verwarming ingesteld op 19 °C.",
   pt="Novo contrato com a rede de calor; temperatura de aquecimento a 19 °C.")

# ---------------------------------------------------------------- justifications d'alertes
_p("J_HANNOVER", fr="Site fermé le 30/06/2025 : six mois d'activité, salariés reclassés à Dortmund ou partis.",
   en="Site closed on 30 June 2025: six months of activity, employees moved to Dortmund or left.",
   es="Centro cerrado el 30 de junio de 2025: seis meses de actividad, empleados reubicados en Dortmund o salidos de la empresa.",
   de="Standort am 30. Juni 2025 geschlossen: sechs Monate Betrieb, Beschäftigte nach Dortmund versetzt oder ausgeschieden.",
   it="Sito chiuso il 30 giugno 2025: sei mesi di attività, dipendenti trasferiti a Dortmund o usciti.",
   nl="Locatie gesloten op 30 juni 2025: zes maanden activiteit, werknemers overgeplaatst naar Dortmund of vertrokken.",
   pt="Local encerrado a 30 de junho de 2025: seis meses de atividade, trabalhadores transferidos para Dortmund ou saídos.")
_p("J_DORTMUND", fr="Reprise de l'activité de l'entrepôt d'Hannover depuis juillet 2025.",
   en="Activity of the Hannover warehouse taken over since July 2025.",
   es="Actividad del almacén de Hannover asumida desde julio de 2025.", de="Übernahme der Tätigkeit des Lagers Hannover seit Juli 2025.",
   it="Attività del magazzino di Hannover rilevata da luglio 2025.", nl="Activiteit van het magazijn in Hannover overgenomen sinds juli 2025.",
   pt="Atividade do armazém de Hannover assumida desde julho de 2025.")
_p("J_FE", fr="Facteur mis à jour avec la valeur publiée pour l'année (même source que l'an dernier).",
   en="Factor updated with the value published for the year (same source as last year).",
   es="Factor actualizado con el valor publicado para el año (misma fuente que el año pasado).",
   de="Faktor mit dem für das Jahr veröffentlichten Wert aktualisiert (dieselbe Quelle wie im Vorjahr).",
   it="Fattore aggiornato con il valore pubblicato per l'anno (stessa fonte dell'anno scorso).",
   nl="Factor bijgewerkt met de voor het jaar gepubliceerde waarde (dezelfde bron als vorig jaar).",
   pt="Fator atualizado com o valor publicado para o ano (mesma fonte do ano passado).")
_p("J_PLAN", fr="Plan de transition adopté par le conseil d'administration le 27/11/2025.",
   en="Transition plan adopted by the board of directors on 27 November 2025.",
   es="Plan de transición adoptado por el consejo de administración el 27 de noviembre de 2025.",
   de="Transitionsplan am 27. November 2025 vom Verwaltungsrat verabschiedet.",
   it="Piano di transizione adottato dal consiglio di amministrazione il 27 novembre 2025.",
   nl="Transitieplan goedgekeurd door de raad van bestuur op 27 november 2025.",
   pt="Plano de transição adotado pelo conselho de administração a 27 de novembro de 2025.")
_p("J_LEIPZIG_GAZ", fr="Chaudière biomasse en service depuis mars 2025 : le gaz ne sert plus qu'en appoint.",
   en="Biomass boiler in service since March 2025: gas is now used only as backup.",
   es="Caldera de biomasa en servicio desde marzo de 2025: el gas solo se usa como apoyo.",
   de="Biomassekessel seit März 2025 in Betrieb: Gas dient nur noch als Reserve.",
   it="Caldaia a biomassa in servizio da marzo 2025: il gas serve ormai solo come integrazione.",
   nl="Biomassaketel in gebruik sinds maart 2025: gas wordt alleen nog als aanvulling gebruikt.",
   pt="Caldeira de biomassa em funcionamento desde março de 2025: o gás serve agora apenas de apoio.")
_p("J_CA", fr="Nouvelle administratrice nommée en juin 2025.", en="New director appointed in June 2025.",
   es="Nueva consejera nombrada en junio de 2025.", de="Neue Verwaltungsrätin im Juni 2025 berufen.",
   it="Nuova consigliera nominata a giugno 2025.", nl="Nieuwe bestuurder benoemd in juni 2025.",
   pt="Nova administradora nomeada em junho de 2025.")
_p("J_DEFAUT", fr="Écart vérifié avec le responsable du site : valeur confirmée.",
   en="Variance checked with the site manager: value confirmed.",
   es="Desviación comprobada con el responsable del centro: valor confirmado.",
   de="Abweichung mit der Standortleitung geprüft: Wert bestätigt.",
   it="Scostamento verificato con il responsabile del sito: valore confermato.",
   nl="Afwijking gecontroleerd met de locatieverantwoordelijke: waarde bevestigd.",
   pt="Desvio verificado com o responsável do local: valor confirmado.")
_p("J_FE_ELEC_2026", fr="Facteur 2026 publié par la base nationale, même source que l'an dernier.",
   en="2026 factor published by the national database, same source as last year.",
   es="Factor de 2026 publicado por la base nacional, misma fuente que el año pasado.",
   de="Faktor 2026 von der nationalen Datenbank veröffentlicht, dieselbe Quelle wie im Vorjahr.",
   it="Fattore 2026 pubblicato dalla banca dati nazionale, stessa fonte dell'anno scorso.",
   nl="Factor 2026 gepubliceerd door de nationale databank, dezelfde bron als vorig jaar.",
   pt="Fator de 2026 publicado pela base nacional, mesma fonte do ano passado.")

# ---------------------------------------------------------------- lignes de tableaux
_p("MAT_RECYCLE", fr="Papier et carton recyclés", en="Recycled paper and board", es="Papel y cartón reciclados",
   de="Recyceltes Papier und Karton", it="Carta e cartone riciclati", nl="Gerecycled papier en karton", pt="Papel e cartão reciclados")
_p("MAT_KRAFT", fr="Papier kraft vierge certifié FSC", en="Virgin kraft paper, FSC-certified", es="Papel kraft virgen certificado FSC",
   de="FSC-zertifiziertes Kraftpapier aus Frischfasern", it="Carta kraft vergine certificata FSC", nl="FSC-gecertificeerd nieuw kraftpapier",
   pt="Papel kraft virgem certificado FSC")
_p("MAT_AMIDON", fr="Amidon (colle)", en="Starch (glue)", es="Almidón (cola)", de="Stärke (Klebstoff)", it="Amido (colla)",
   nl="Zetmeel (lijm)", pt="Amido (cola)")
_p("MAT_ENCRES", fr="Encres à l'eau", en="Water-based inks", es="Tintas al agua", de="Wasserbasierte Druckfarben", it="Inchiostri all'acqua",
   nl="Inkten op waterbasis", pt="Tintas à base de água")
_p("MAT_FILM", fr="Film polypropylène", en="Polypropylene film", es="Película de polipropileno", de="Polypropylenfolie",
   it="Film di polipropilene", nl="Polypropyleenfolie", pt="Película de polipropileno")

# ---------------------------------------------------------------- vues de la Visualisation et listes de KPI
_p("VUE1_NOM", fr="Comité de direction", en="Executive committee", es="Comité de dirección", de="Geschäftsleitung",
   it="Comitato di direzione", nl="Directiecomité", pt="Comissão executiva")
_p("VUE1_DESC", fr="Les chiffres clés du groupe, d'une année sur l'autre.", en="The group's key figures, year on year.",
   es="Las cifras clave del grupo, año tras año.", de="Die Kennzahlen des Konzerns im Jahresvergleich.",
   it="Le cifre chiave del gruppo, anno su anno.", nl="De kerncijfers van de groep, jaar na jaar.",
   pt="Os números-chave do grupo, de um ano para o outro.")
_p("VUE2_NOM", fr="Énergie et climat", en="Energy and climate", es="Energía y clima", de="Energie und Klima", it="Energia e clima",
   nl="Energie en klimaat", pt="Energia e clima")
_p("VUE2_DESC", fr="Consommations d'énergie et émissions, par année et par pays.", en="Energy use and emissions, by year and by country.",
   es="Consumos de energía y emisiones, por año y por país.", de="Energieverbrauch und Emissionen, nach Jahr und Land.",
   it="Consumi di energia ed emissioni, per anno e per paese.", nl="Energieverbruik en emissies, per jaar en per land.",
   pt="Consumos de energia e emissões, por ano e por país.")
_p("VUE3_NOM", fr="Mon périmètre", en="My scope", es="Mi perímetro", de="Mein Zuständigkeitsbereich", it="Il mio perimetro",
   nl="Mijn werkterrein", pt="O meu perímetro")
_p("VUE3_DESC", fr="Les valeurs de mes sites, d'une année sur l'autre.", en="The values of my sites, year on year.",
   es="Los valores de mis centros, año tras año.", de="Die Werte meiner Standorte im Jahresvergleich.",
   it="I valori dei miei siti, anno su anno.", nl="De waarden van mijn locaties, jaar na jaar.",
   pt="Os valores dos meus locais, de um ano para o outro.")
_p("ESSENTIELS", fr="{theme} – essentiels", en="{theme} – essentials", es="{theme} – esenciales", de="{theme} – Wesentliches",
   it="{theme} – essenziali", nl="{theme} – essentieel", pt="{theme} – essenciais")

# ---------------------------------------------------------------- justificatifs (titre dans le document, nom du fichier)
_p("P_ELEC", fr="Récapitulatif annuel d'électricité 2025", en="Annual electricity summary 2025", es="Resumen anual de electricidad 2025",
   de="Jahresübersicht Strom 2025", it="Riepilogo annuale dell'elettricità 2025", nl="Jaaroverzicht elektriciteit 2025",
   pt="Resumo anual de eletricidade 2025")
_p("P_GO", fr="Attestation de garanties d'origine 2025", en="Certificate of guarantees of origin 2025",
   es="Certificado de garantías de origen 2025", de="Bescheinigung der Herkunftsnachweise 2025",
   it="Attestazione delle garanzie di origine 2025", nl="Attest van garanties van oorsprong 2025",
   pt="Certificado de garantias de origem 2025")
_p("P_BIOMASSE", fr="Livraisons de plaquettes forestières 2025", en="Wood chip deliveries 2025", es="Entregas de astillas forestales 2025",
   de="Lieferungen von Waldhackschnitzeln 2025", it="Consegne di cippato forestale 2025", nl="Leveringen van houtsnippers 2025",
   pt="Entregas de estilha florestal 2025")
_p("P_ACCIDENTS", fr="Registre des accidents du travail 2025", en="Register of work accidents 2025",
   es="Registro de accidentes de trabajo 2025", de="Register der Arbeitsunfälle 2025", it="Registro degli infortuni sul lavoro 2025",
   nl="Register van arbeidsongevallen 2025", pt="Registo de acidentes de trabalho 2025")
_p("P_ISO", fr="Certificats ISO 14001 en vigueur", en="ISO 14001 certificates in force", es="Certificados ISO 14001 vigentes",
   de="Gültige ISO-14001-Zertifikate", it="Certificati ISO 14001 in vigore", nl="Geldige ISO 14001-certificaten",
   pt="Certificados ISO 14001 em vigor")
_p("P_LYON", fr="Factures d'électricité 2026 (janvier à octobre)", en="Electricity invoices 2026 (January to October)",
   es="Facturas de electricidad 2026 (de enero a octubre)", de="Stromrechnungen 2026 (Januar bis Oktober)",
   it="Fatture di elettricità 2026 (da gennaio a ottobre)", nl="Elektriciteitsfacturen 2026 (januari tot oktober)",
   pt="Faturas de eletricidade 2026 (de janeiro a outubro)")
# Noms de fichier : le nom français pour le français, l'anglais pour les autres langues (les justificatifs de l'Espagne et
# de l'Allemagne gardent leur nom d'origine, dans la langue du pays)
FICHIERS_ANGLAIS = {
    "facture-electricite-2025-villefranche.pdf": "electricity-summary-2025-villefranche.pdf",
    "garanties-origine-2025.pdf": "guarantees-of-origin-2025.pdf",
    "biomasse-livraisons-2025.pdf": "biomass-deliveries-2025.pdf",
    "registre-accidents-2025.pdf": "accident-register-2025.pdf",
    "certificats-iso-14001.pdf": "iso-14001-certificates.pdf",
    "factures-electricite-2026-lyon.pdf": "electricity-invoices-2026-lyon.pdf",
}
TITRE_PREUVE = {  # nom du fichier français -> clé du titre
    "facture-electricite-2025-villefranche.pdf": "P_ELEC", "garanties-origine-2025.pdf": "P_GO", "biomasse-livraisons-2025.pdf": "P_BIOMASSE",
    "registre-accidents-2025.pdf": "P_ACCIDENTS", "certificats-iso-14001.pdf": "P_ISO", "factures-electricite-2026-lyon.pdf": "P_LYON",
}
_p("PDF_EXERCICE", fr="{organisation} - exercice {exercice}", en="{organisation} - reporting year {exercice}",
   es="{organisation} - ejercicio {exercice}", de="{organisation} - Berichtsjahr {exercice}", it="{organisation} - esercizio {exercice}",
   nl="{organisation} - verslagjaar {exercice}", pt="{organisation} - exercício {exercice}")
_p("PDF_FICTIF", fr="Document fictif de la demonstration Probant (Exemplia).", en="Fictitious document of the Probant demonstration (Exemplia).",
   es="Documento ficticio de la demostracion de Probant (Exemplia).", de="Fiktives Dokument der Probant-Demo (Exemplia).",
   it="Documento fittizio della dimostrazione di Probant (Exemplia).", nl="Fictief document van de Probant-demo (Exemplia).",
   pt="Documento ficticio da demonstracao do Probant (Exemplia).")

# ---------------------------------------------------------------- règles de cohérence (nom et description, la clé est le nom français)
# Une règle n'a pas de traductions : la démo écrit son nom et sa description dans la langue de l'installation.
REGLES = {
    "Déchets dangereux ≤ déchets générés": {
        "en": ("Hazardous waste ≤ waste generated", "Hazardous waste is part of the waste generated."),
        "es": ("Residuos peligrosos ≤ residuos generados", "Los residuos peligrosos forman parte de los residuos generados."),
        "de": ("Gefährliche Abfälle ≤ erzeugte Abfälle", "Gefährliche Abfälle sind Teil der erzeugten Abfälle."),
        "it": ("Rifiuti pericolosi ≤ rifiuti prodotti", "I rifiuti pericolosi fanno parte dei rifiuti prodotti."),
        "nl": ("Gevaarlijk afval ≤ geproduceerd afval", "Gevaarlijk afval maakt deel uit van het geproduceerde afval."),
        "pt": ("Resíduos perigosos ≤ resíduos gerados", "Os resíduos perigosos fazem parte dos resíduos gerados.")},
    "Déchets préparés pour le réemploi ≤ déchets générés": {
        "en": ("Waste prepared for reuse ≤ waste generated", "Waste prepared for reuse is part of the waste generated."),
        "es": ("Residuos preparados para su reutilización ≤ residuos generados",
               "Los residuos preparados para su reutilización forman parte de los residuos generados."),
        "de": ("Zur Wiederverwendung vorbereitete Abfälle ≤ erzeugte Abfälle",
               "Zur Wiederverwendung vorbereitete Abfälle sind Teil der erzeugten Abfälle."),
        "it": ("Rifiuti preparati per il riutilizzo ≤ rifiuti prodotti", "I rifiuti preparati per il riutilizzo fanno parte dei rifiuti prodotti."),
        "nl": ("Afval voorbereid voor hergebruik ≤ geproduceerd afval",
               "Afval dat is voorbereid voor hergebruik maakt deel uit van het geproduceerde afval."),
        "pt": ("Resíduos preparados para reutilização ≤ resíduos gerados",
               "Os resíduos preparados para reutilização fazem parte dos resíduos gerados.")},
    "Déchets recyclés ≤ déchets générés": {
        "en": ("Recycled waste ≤ waste generated", "Recycled waste is part of the waste generated."),
        "es": ("Residuos reciclados ≤ residuos generados", "Los residuos reciclados forman parte de los residuos generados."),
        "de": ("Recycelte Abfälle ≤ erzeugte Abfälle", "Recycelte Abfälle sind Teil der erzeugten Abfälle."),
        "it": ("Rifiuti riciclati ≤ rifiuti prodotti", "I rifiuti riciclati fanno parte dei rifiuti prodotti."),
        "nl": ("Gerecycled afval ≤ geproduceerd afval", "Gerecycled afval maakt deel uit van het geproduceerde afval."),
        "pt": ("Resíduos reciclados ≤ resíduos gerados", "Os resíduos reciclados fazem parte dos resíduos gerados.")},
    "Eau rejetée par les procédés ≤ eau prélevée": {
        "en": ("Water discharged by processes ≤ water withdrawn", "Water discharged by processes cannot exceed water withdrawn."),
        "es": ("Agua vertida por los procesos ≤ agua extraída", "El agua vertida por los procesos no puede superar el agua extraída."),
        "de": ("Von Prozessen abgeleitetes Wasser ≤ entnommenes Wasser",
               "Das von Prozessen abgeleitete Wasser darf das entnommene Wasser nicht übersteigen."),
        "it": ("Acqua scaricata dai processi ≤ acqua prelevata", "L'acqua scaricata dai processi non può superare l'acqua prelevata."),
        "nl": ("Door processen geloosd water ≤ onttrokken water", "Het door processen geloosde water mag niet hoger zijn dan het onttrokken water."),
        "pt": ("Água descarregada pelos processos ≤ água captada", "A água descarregada pelos processos não pode exceder a água captada.")},
    "Effectif féminin ≤ effectif total": {
        "en": ("Female headcount ≤ total headcount", "Female headcount cannot exceed total headcount."),
        "es": ("Plantilla femenina ≤ plantilla total", "La plantilla femenina no puede superar la plantilla total."),
        "de": ("Weibliche Beschäftigte ≤ Gesamtbelegschaft", "Die Zahl der weiblichen Beschäftigten darf die Gesamtbelegschaft nicht übersteigen."),
        "it": ("Organico femminile ≤ organico totale", "L'organico femminile non può superare l'organico totale."),
        "nl": ("Vrouwelijke werknemers ≤ totaal aantal werknemers", "Het aantal vrouwelijke werknemers mag het totaal niet overschrijden."),
        "pt": ("Efetivo feminino ≤ efetivo total", "O efetivo feminino não pode exceder o efetivo total.")},
    "Effectif masculin ≤ effectif total": {
        "en": ("Male headcount ≤ total headcount", "Male headcount cannot exceed total headcount."),
        "es": ("Plantilla masculina ≤ plantilla total", "La plantilla masculina no puede superar la plantilla total."),
        "de": ("Männliche Beschäftigte ≤ Gesamtbelegschaft", "Die Zahl der männlichen Beschäftigten darf die Gesamtbelegschaft nicht übersteigen."),
        "it": ("Organico maschile ≤ organico totale", "L'organico maschile non può superare l'organico totale."),
        "nl": ("Mannelijke werknemers ≤ totaal aantal werknemers", "Het aantal mannelijke werknemers mag het totaal niet overschrijden."),
        "pt": ("Efetivo masculino ≤ efetivo total", "O efetivo masculino não pode exceder o efetivo total.")},
    "Salariés couverts par une convention ≤ effectif total": {
        "en": ("Employees covered by agreements ≤ total headcount",
               "Employees covered by collective agreements are part of the total headcount."),
        "es": ("Empleados cubiertos por un convenio ≤ plantilla total",
               "Los empleados cubiertos por un convenio colectivo forman parte de la plantilla total."),
        "de": ("Durch Tarifvertrag abgedeckte Beschäftigte ≤ Gesamtbelegschaft",
               "Beschäftigte, die durch einen Tarifvertrag abgedeckt sind, sind Teil der Gesamtbelegschaft."),
        "it": ("Dipendenti coperti da un contratto ≤ organico totale",
               "I dipendenti coperti da un contratto collettivo fanno parte dell'organico totale."),
        "nl": ("Werknemers onder een cao ≤ totaal aantal werknemers",
               "Werknemers die onder een collectieve arbeidsovereenkomst vallen, maken deel uit van het totaal."),
        "pt": ("Trabalhadores abrangidos por um acordo ≤ efetivo total",
               "Os trabalhadores abrangidos por um acordo coletivo fazem parte do efetivo total.")},
    "Salariés en CDI ≤ effectif total": {
        "en": ("Employees on permanent contracts ≤ total headcount", "Employees on permanent contracts are part of the total headcount."),
        "es": ("Empleados con contrato indefinido ≤ plantilla total", "Los empleados con contrato indefinido forman parte de la plantilla total."),
        "de": ("Unbefristet Beschäftigte ≤ Gesamtbelegschaft", "Unbefristet Beschäftigte sind Teil der Gesamtbelegschaft."),
        "it": ("Dipendenti a tempo indeterminato ≤ organico totale", "I dipendenti a tempo indeterminato fanno parte dell'organico totale."),
        "nl": ("Werknemers met een vast contract ≤ totaal aantal werknemers",
               "Werknemers met een vast contract maken deel uit van het totaal aantal werknemers."),
        "pt": ("Trabalhadores com contrato sem termo ≤ efetivo total", "Os trabalhadores com contrato sem termo fazem parte do efetivo total.")},
    "Électricité renouvelable achetée ≤ électricité achetée": {
        "en": ("Purchased renewable electricity ≤ purchased electricity", "Purchased renewable electricity is part of the purchased electricity."),
        "es": ("Electricidad renovable comprada ≤ electricidad comprada", "La electricidad renovable comprada forma parte de la electricidad comprada."),
        "de": ("Zugekaufter Strom aus erneuerbaren Quellen ≤ zugekaufter Strom",
               "Zugekaufter Strom aus erneuerbaren Quellen ist Teil des zugekauften Stroms."),
        "it": ("Elettricità rinnovabile acquistata ≤ elettricità acquistata", "L'elettricità rinnovabile acquistata fa parte dell'elettricità acquistata."),
        "nl": ("Gekochte hernieuwbare elektriciteit ≤ gekochte elektriciteit",
               "Gekochte hernieuwbare elektriciteit maakt deel uit van de gekochte elektriciteit."),
        "pt": ("Eletricidade renovável adquirida ≤ eletricidade adquirida", "A eletricidade renovável adquirida faz parte da eletricidade adquirida.")},
}
