# 08. Оцінка та roadmap

## 1. Golden dataset

Без нього критерії прийняття не мають сенсу. Склад першої версії:

| Сегмент | Кількість | Як збираємо |
|---|---|---|
| T1 mainstream, 10 категорій × 15 | 150 | Ручна верифікація по сайту виробника + datasheet |
| T2 long-tail, ті ж категорії | 100 | те саме + два незалежні джерела |
| T3 rare/discontinued/B2B | 100 | Datasheet/архів; частина полів свідомо `unknown` в еталоні |
| Пастки: варіанти | 50 | Пари/трійки товарів, що відрізняються одним токеном (колір, пам'ять, FC/не FC, EU/US) |
| Пастки: конфлікти | 50 | Товари, де у вебі відома розбіжність (одруківка виробника, зміна ревізії) |
| Шумні назви | 50 | Транслітерація, одруківки, обрізані назви, змішані мови |

Кожен запис: вхідна назва, еталонні identifiers, еталонні поля з посиланнями на докази, список "заборонених" значень (з сусідніх варіантів), очікуваний статус кожного поля. Зберігається у репо у `eval/golden/*.jsonl`, версіонується, зміни через review.

## 2. Метрики

| Метрика | Формула | AC |
|---|---|---|
| Entity accuracy | правильний anchor / усі | AC-C1 |
| Field precision@status | правильних значень зі статусом S / усіх зі статусом S | AC-C2, C3 |
| Coverage | полів зі значенням / полів у еталоні з відомим значенням | AC-R1, R2 |
| Fabrication rate | значень без grounding / усіх значень | AC-C4 |
| Variant leakage | значень із "заборонених" / усіх | AC-C7 |
| Conflict recall | конфліктів, помічених як `conflict` або вирішених правильно / відомих конфліктів | AC-C5 |
| Calibration (ECE) | розбіжність confidence vs точність по бінах | звіт |
| Latency p50/p95, cost | | AC-P1, P2, P6 |
| Baseline delta | PTE − Perplexity/Exa на тій самій схемі | AC-B1..B3 |

Порівняння з бейзлайнами: однаковий промпт зі схемою, structured output, ті самі 500 товарів, ручна перевірка розбіжностей.

## 3. CI

- `eval:smoke` (30 товарів, кеш snapshot-ів) на кожен PR: fabrication rate = 0, entity accuracy ≥ 0.97.
- `eval:full` (весь golden, з кешем) щоночі: усі AC, тренд у дашборді.
- `eval:live` (без кешу, 100 товарів) щотижня: ловить зміни сайтів і деградацію конекторів.
- Регресія будь-якого blocking-AC блокує merge.

## 4. Калібрування confidence

Після кожного `eval:full` будується ізотонічна регресія `raw_confidence → observed_precision` окремо для статусів і категорій. Пороги `T_FIELD`, `T_ANCHOR`, `T_MARGIN` перераховуються так, щоб `verified` тримав ≥ 99.5%.

## 5. Roadmap

Фази без жорстких дат; кожна закінчується вимірюваним гейтом.

### Фаза 0. Фундамент
- Онтологія 10 категорій, envelope-схема, golden dataset v0 (150 T1).
- Query Understanding, Fetcher з кешем, structured + table екстрактори, Postgres PKG.
- **Гейт:** entity accuracy ≥ 95% на T1, fabrication 0.

### Фаза 1. Truth Engine
- Claims store, equivalence classes, copy-chain detection, CRH-голосування, hard constraints, статуси, guard.
- Конектори: Google, Bing, Brave, Icecat Open, Wikidata, 3 маркетплейси, manufacturer `site:`.
- **Гейт:** AC-C1..C6 на T1; coverage T1 ≥ 85%.

### Фаза 2. Повнота
- Hole-driven search, LLM-екстрактор з grounding, PDF, ledger, LLM-judge, стрімінг.
- Golden v1 (+T2, пастки).
- **Гейт:** AC-R1, AC-C7, бейзлайни AC-B1/B2.

### Фаза 3. Дефіцитні товари
- Wayback, Common Crawl, дистриб'ютори, регуляторні бази, cross-lingual, sibling inference, vision/OCR, `deep`-режим.
- Golden v2 (+T3).
- **Гейт:** AC-R3, AC-B3.

### Фаза 4. Масштаб і навчання
- Temporal, batch API, gain-per-cost планування, PKG-first, ontology auto-growth, human-in-the-loop, adversarial verifier.
- **Гейт:** AC-P3, AC-P6, calibration ECE ≤ 0.05.

## 6. Ризики

| Ризик | Мітигація |
|---|---|
| Джерела змінюють розмітку | Контрактні тести на кожен конектор у `eval:live`, layered extraction як fallback |
| Квоти/вартість пошукових API | Кеш, PKG-first, Brave як дешевий базовий індекс, gain-per-cost |
| Юридичні обмеження скрейпінгу | ToS-політика доменів, API де є, архіви |
| Виробник сам помиляється | Tier A не абсолют: суперечність tier A vs ≥3 незалежних B → `conflict`, не `verified` |
| Дрейф LLM | Пінінг версій моделі, golden-регресія, grounding check незалежний від LLM |
