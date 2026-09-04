# 04. Джерела та дефіцитні товари

## 1. Таксономія джерел за авторитетом

| Tier | Prior | Клас | Приклади |
|------|-------|------|----------|
| **A** | 1.00 | Першоджерела | Сайт виробника (product page, spec sheet), datasheet/manual PDF, регуляторні бази (FCC ID, EU DoC, Bluetooth SIG Launch Studio, Wi-Fi Alliance, ENERGY STAR, EPREL для EU energy labels), GS1 GEPIR/Verified by GS1 |
| **B** | 0.75 | Куровані каталоги | Icecat / Open Icecat, Wikidata/Wikipedia, GSMArena, Notebookcheck, TechPowerUp GPU/CPU DB, PCPartPicker, Digi-Key / Mouser / Farnell / TME / RS (електроніка та промисловість), Octopart, Autodoc/TecDoc (автозапчастини), Open Food Facts / Open Beauty Facts, UPCitemdb, Barcode Lookup |
| **C** | 0.45 | Великі маркетплейси і агрегатори з structured data | Amazon, eBay (incl. sold listings), Walmart, AliExpress, Rozetka, Prom.ua, Allegro, Ceneo, Idealo, Geizhals, Hotline.ua, e-katalog, PriceRunner, Kakaku.com, JD/Tmall/1688 |
| **D** | 0.25 | Спільноти | Reddit, спеціалізовані форуми, YouTube (транскрипти оглядів), iFixit, ManualsLib, відгуки |
| **E** | 0.15 | Answer engines (тільки як ліди) | Perplexity Sonar, Exa, Tavily, You.com |

Prior — стартова вага; ledger далі коригує її за фактичною поведінкою кожного домену у кожній категорії.

## 2. Пошукові індекси (discovery)

Різні індекси бачать різний веб. Для T3 це критично.

| Індекс | Роль |
|--------|------|
| Google (SerpAPI/Serper) | Основний; `site:` для виробників, `filetype:pdf` |
| Bing API | Інший crawl, кращий по PDF/старих сторінках |
| Brave Search API | Незалежний індекс, дешевий |
| Yandex XML | Товари з СНД, кирилічні назви, регіональні магазини |
| Baidu / Sogou | Китайські виробники, 1688/Taobao-каталоги |
| Naver | Корейські бренди |
| Exa | Нейропошук "схожих сторінок" від сторінки виробника |
| Tavily / Perplexity | Швидкі ліди |
| Common Crawl CDX + WARC | Офлайн-індекс усього вебу за роки: пошук по URL-патернах виробника, витяг старих сторінок |
| Wayback Machine CDX | Знята продукція, закриті магазини |
| Google Patents / Espacenet | Промислові компоненти: назви, параметри у патентах виробника |

## 3. Playbook для дефіцитних товарів (T3)

Кожна тактика — окрема нода DAG, що вмикається у `deep` або коли після R1 anchor не знайдено.

1. **Identifier pivot.** Знайшли будь-який ID (MPN на фото шильдика, GTIN у старому листингу) → `lookup_by_id` у всі бази. Один ID часто розблоковує 10 сторінок, які не знаходяться за назвою.
2. **Wayback replay.** CDX-запит по `manufacturer.com/*model*` та по URL магазинів, що зникли. Snapshots з Wayback мають tier джерела-оригіналу з множником свіжості 0.9.
3. **Common Crawl mining.** Пошук по CDX-індексу за URL-патерном і за точним рядком коду моделі у WARC-текстах (через колонковий індекс `columnar index` + Athena/DuckDB).
4. **Datasheet hunting.** `filetype:pdf "{model}"`, каталоги виробника (annual catalogs містять тисячі знятих моделей), дистриб'юторські PDF, ManualsLib, archive.org texts.
5. **Distributor catalogs.** Для промисловості: Digi-Key/Mouser/Farnell/TME зберігають сторінки obsolete-компонентів з повними параметрами і посиланням на replacement.
6. **Cross-lingual expansion.** Запити рідною мовою бренду (de, ja, zh, ko, it, pl) і регіональними індексами. Японські та німецькі каталоги часто повніші за англійські.
7. **Marketplace archaeology.** eBay sold/completed listings, Amazon old ASIN (через `dp/ASIN` навіть якщо "currently unavailable"), OLX/Avito архіви через Wayback, Allegro archive.
8. **Sibling inference з явною позначкою.** Якщо знайдено сімейство (`GSR 12V-35` та `GSR 12V-35 FC` ділять двигун), спільні атрибути сімейства виводяться зі статусом `inferred` та `inferred_from: {product_id, relation}`. Ніколи не `verified`.
9. **Regulatory databases.** FCC ID (радіо-модулі, фото внутрішностей, manual), EU EPREL (енергетика, точні цифри), CE DoC PDF на сайті виробника, UL/ETL сертифікати, ATEX для промисловості. Часто це єдине джерело для B2B.
10. **Successor/predecessor graph.** Сторінка наступника часто містить порівняння з попередником, включно з спеками попередника.
11. **Community & media.** Огляди на YouTube (транскрипт), форуми з фото шильдика, iFixit teardown. Tier D, але для T3 це може бути єдиний доказ маси або розмірів.
12. **Vision.** Фото товару/шильдика/упаковки → OCR штрихкода і MPN; фото спек-таблиці → таблиця. Позначка `ocr=true`.
13. **Query mutation.** Мутації коду моделі: варіації пробілів/дефісів, регіональні суфікси (`/EU`, `-UK`, `(US)`), латиниця↔кирилиця, типові одруківки, стара назва бренду (ребрендинги).
14. **Recursive alias discovery.** Кожна знайдена сторінка з entity_match ≥ 0.9 дає нові aliases (title, "also known as", article numbers дистриб'юторів). Вони стають новими запитами наступного раунду.

Критерій успіху для T3 (AC-R3): знайдено якір або сторінка рівня A/B. Якщо ні — вихід має `identity.status = "unresolved"`, `search_log` з усіма спробами та `closest_matches[]`.

## 4. Регіональні пакети конекторів

| Регіон | Конектори |
|--------|-----------|
| UA | Rozetka, Prom.ua, Hotline.ua, e-katalog, OLX, Comfy, Foxtrot, Citrus, Allo |
| PL | Allego, Ceneo, Morele, x-kom |
| DE/AT | Idealo, Geizhals, Amazon.de, Conrad, Reichelt |
| US | Amazon, Walmart, BestBuy, Newegg, B&H, Home Depot |
| JP | Kakaku, Rakuten, Amazon.jp, Yodobashi |
| CN | JD, Tmall, 1688, ZOL (спеки) |

Регіон обирається з hints, мови запиту та бренду; у `deep` перебираються всі, де ledger показує ненульовий gain для категорії.

## 5. Політика fetch

- `allow`: HTML/API з robots.txt і rate limits.
- `api_only`: домени з офіційним API або ліцензованим фідом (Icecat, GS1, деякі маркетплейси). Скрейпінг HTML заборонено конфігом.
- `deny`: ToS явно забороняє; беремо тільки те, що доступне через пошуковий snippet або Wayback.
- Проксі-пул за регіоном; Playwright тільки при JS-рендері або challenge; ніяких обходів CAPTCHA.
- Snapshot зберігається з `robots_ok`, `fetch_mode`, `region`, щоб eval міг відтворити прогін.
