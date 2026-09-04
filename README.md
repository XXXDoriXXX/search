# Product Truth Engine (PTE)

Дизайн системи, яка за назвою товару збирає **максимум даних про саме цей товар**, вирішує конфлікти між джерелами і повертає чистий JSON, у якому кожне поле має доказ (provenance), впевненість і статус верифікації.

Ключова ідея, що відрізняє PTE від Perplexity / Exa / Tavily: ми не "шукаємо і переказуємо", ми **встановлюємо факти**. Кожне значення проходить через identifier-anchoring, entity matching, незалежне голосування джерел, hard-constraints і abstain-політику. Якщо факт не доведено, система повертає `unknown` з кандидатами, а не правдоподібну вигадку.

## Зміст

| # | Документ | Про що |
|---|----------|--------|
| 01 | [Проблема та критерії прийняття](docs/01-problem-and-acceptance-criteria.md) | Що означає "100% правильно", тири товарів, режими, вимірювані AC |
| 02 | [Архітектура](docs/02-architecture.md) | Компоненти, потік даних, паралелізм, стек |
| 03 | [Алгоритм](docs/03-algorithm.md) | Адаптивний багатораундовий пошук, truth discovery, псевдокод |
| 04 | [Джерела та дефіцитні товари](docs/04-sources-and-rare-products.md) | Таксономія джерел за авторитетом, playbook для рідкісних товарів |
| 05 | [Схема виходу](docs/05-output-schema.md) | Envelope поля, core-схема, категорійні розширення |
| 06 | [Варіанти та trade-off](docs/06-options-and-tradeoffs.md) | Варіанти A/B/C по кожному шару, рекомендація |
| 07 | [Brainstorm](docs/07-brainstorm.md) | Ідеї з оцінкою impact/effort |
| 08 | [Оцінка та roadmap](docs/08-evaluation-and-roadmap.md) | Golden dataset, метрики, фази |

## Прототип (робочий код)

Пакет `pte/` реалізує весь пайплайн з док 03 і проходить end-to-end на офлайн-корпусі з реальними пастками вебу.

```bash
pip install -r requirements.txt
python3 fixtures/demo/build.py                       # синтетичний корпус: виробник (JSON-LD), агрегатор, 3 магазини з однією скопійованою
                                                     # помилкою, сусідня модель GSR 12V-35, PDF datasheet, форум
python3 -m pte "Bosch GSR 12V-35 FC" --offline --fixtures fixtures/demo/index.json --trace --json out.json
python3 -m pytest -q                                 # 21 тест: одиниці, sibling-логіка, copy-chain, abstain, grounding, схема
python3 eval/run_eval.py                             # метрики AC-C1..C7 на golden set
```

Що робить прототип на демо-корпусі (усе видно в `--trace`):

| Пастка | Що роблять answer engines | Що робить PTE |
|---|---|---|
| Три магазини скопіювали spec-блок з помилкою "30 Nm" | "консенсус" 3 проти 1 | Копії згорнуті в 1 голос; перемагає 35 Nm від виробника + PDF + агрегатора; 30 Nm лишається кандидатом з причиною `copy-chain` |
| Сторінка сусідньої моделі GSR 12V-35 (без FC) | змішує спеки | entity match 0.15, жодне значення не потрапляє у вихід |
| Вага 0.8 kg (з батареєю) vs 0.59 kg (без) | бере будь-яку | 590 g `verified` 3 голосами, 800 g кандидат з `context` |
| Гарантія: магазини 24 міс vs форум 3 роки | впевнено називає одне | `conflict`, value=null, обидва кандидати з доказами, `search_log` |
| Поле відсутнє після першого раунду | нічого | hole-driven запит `"GSR 12V-35 FC" warranty` знаходить форум у раунді 2 |
| Значення, якого нема в тексті джерела | галюцинація | grounding check відкидає claim ще до голосування; AC-C4 = 0 |

Live-режим (потрібна мережа; у цій сесії egress-політика блокує все, крім PyPI, тому live не запускався):

```bash
export SERPER_API_KEY=...   # Google через serper.dev (опційно)
export BRAVE_API_KEY=...    # Brave Search (опційно)
export ANTHROPIC_API_KEY=... # вмикає LLM-екстрактор для сторінок tier A/B (опційно)
python3 -m pte "Bosch GSR 12V-35 FC" --tier-a bosch-professional.com --tier-b icecat.biz --json out.json
export PERPLEXITY_API_KEY=... && python3 eval/baselines/perplexity.py && python3 eval/run_eval.py --live --baseline eval/baselines/out/perplexity.jsonl
```

Без ключів працюють DuckDuckGo HTML і Wikidata; Wayback-конектор потребує списку доменів виробника.

Структура:

| Модуль | Роль |
|---|---|
| `pte/query.py` | R0: бренд, код моделі (з транслітом змішаних кодів), варіантні осі, категорія, query variants, hole-запити |
| `pte/connectors/` | `SourceConnector` протокол, реєстр з circuit breaker; DuckDuckGo, Brave, Serper, Wikidata, Wayback, Fixture |
| `pte/fetch.py` | httpx + content-addressed кеш, per-domain concurrency, HTML→текст зі збереженням таблиць, PDF→текст |
| `pte/extract/` | JSON-LD/OG, key-value/таблиці з розщепленням `hard/soft`, опційний LLM з обов'язковим evidence |
| `pte/match.py` | Entity match: identifiers → точний код → sibling-детекція за кількістю входжень |
| `pte/independence.py` | Copy-chain: shingle-Jaccard spec-блоків + власники доменів → кластери |
| `pte/truth.py` | Класи еквівалентності з tolerance, CRH-ітерації ваг, статуси `verified/single_source/conflict/unknown`, Ledger |
| `pte/guard.py` | Діапазони, grounding, крос-польові інваріанти, GTIN checksum |
| `pte/pipeline.py` | Оркестрація раундів, бюджети, hole-driven цикл з early-stop, збірка документа |
| `eval/` | Golden set, метрики AC, бейзлайн Perplexity |

Що ще не реалізовано з дизайну: Temporal-оркестрація, Common Crawl, регуляторні бази, vision/OCR, LLM-арбітр для `conflict`, персистентний PKG (ledger зараз in-memory), онтологія лише для 2 категорій.

Машиночитані артефакти:

- [`schema/product.schema.json`](schema/product.schema.json) — JSON Schema вихідного документа.
- [`examples/output.example.json`](examples/output.example.json) — ілюстративний приклад відповіді.

## TL;DR рекомендованого варіанта

1. **Identifier-first.** Перший раунд шукає не "дані", а якорі: MPN, GTIN/EAN/UPC, ASIN, ID виробника. Усе подальше прив'язується до якоря, інакше дані про сусідню модифікацію змішуються з цільовою.
2. **Гібридне discovery.** Пошукові API (Google/Bing/Brave/Yandex/Baidu/Exa/Tavily) для розвідки + вертикальні конектори (виробник, datasheet PDF, Icecat, Wikidata, дистриб'ютори, маркетплейси, регуляторні бази) + архіви (Wayback, Common Crawl) для дефіцитних товарів + власний Product Knowledge Graph, що росте з кожним запитом.
3. **Hole-driven search.** Після першого проходу система рахує покриття схеми та генерує точкові запити під кожне відсутнє або конфліктне поле, поки є бюджет або поки приріст не впаде нижче порога.
4. **Truth discovery, а не "LLM вирішить".** Ітеративне зважене голосування (CRH-стиль) з урахуванням авторитету, свіжості, якості entity-match, **незалежності джерел** (копії не рахуються як голоси) та hard-constraints (контрольна сума GTIN, діапазони, крос-польові формули). LLM використовується як екстрактор і як арбітр-голосувальник, ніколи як єдине джерело істини.
5. **Abstain-політика.** Поле виходить зі статусом `verified` лише за наявності незалежного підтвердження. Інакше `single_source`, `conflict`, `inferred` або `unknown`, завжди з кандидатами та доказами.
6. **Паралелізм як DAG** з бюджетами (час, гроші, запити), circuit breaker на кожен конектор, спекулятивним виконанням та early-stop при насиченні впевненості.
