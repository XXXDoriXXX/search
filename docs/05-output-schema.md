# 05. Схема виходу

Повна JSON Schema: [`schema/product.schema.json`](../schema/product.schema.json). Приклад: [`examples/output.example.json`](../examples/output.example.json) (ілюстративний: показує форму відповіді, значення не є верифікованими фактами; валідується проти схеми).

## 1. Envelope поля

Кожен атрибут (крім `meta`, `identity.status`, `offers`) загорнутий у однаковий envelope. Це дає уніфіковану обробку, стрімінг оновлень і можливість клієнту фільтрувати за статусом (`?min_status=verified`).

```json
{
  "value": 1.2,
  "unit": "kg",
  "raw": ["1,2 кг", "1.2 kg", "2.65 lb"],
  "status": "verified",
  "confidence": 0.97,
  "sources": [
    {"url": "https://www.bosch-professional.com/...", "tier": "A", "snippet": "Weight: 1.2 kg", "fetched_at": "2026-09-04T10:11:12Z", "snapshot": "sha256:..."},
    {"url": "https://icecat.biz/...", "tier": "B", "snippet": "Weight 1.2 kg", "fetched_at": "...", "snapshot": "sha256:..."}
  ],
  "candidates": [
    {"value": 1.3, "unit": "kg", "score": 0.08, "sources": ["https://shop.example/..."], "rejected_reason": "outvoted; likely includes battery"}
  ],
  "resolution": {"method": "weighted_vote", "independent_votes": 2, "margin": 0.89, "constraints_checked": ["range:power_tool.weight"]},
  "applies_to": "variant"
}
```

| Ключ | Опис |
|------|------|
| `value` | Канонічне значення (число, рядок, масив, об'єкт) або `null` |
| `unit` | Канонічна одиниця (SI за замовчуванням) або відсутній |
| `raw` | Оригінальні рядки з джерел (для аудиту та локалізації) |
| `status` | `verified` \| `single_source` \| `conflict` \| `inferred` \| `unknown` |
| `confidence` | 0..1, калібрована (док 08) |
| `sources[]` | Докази; для `verified` ≥ 2 незалежних або 1 tier A |
| `candidates[]` | Альтернативи, що програли, з причиною |
| `resolution` | Як прийнято рішення: метод, голоси, margin, constraints, `judge_reason` якщо був арбітр |
| `applies_to` | `variant` \| `family` \| `shared_across_variants` |
| `inferred_from` | тільки для `inferred`: звідки виведено |
| `as_of` | тільки для time-varying |

## 2. Верхній рівень

```
{
  "identity":      { status, confidence, brand, manufacturer, model, model_normalized, variant{axes}, mpn, gtins[], asin, other_ids[], category_path[], canonical_name, aliases[], lifecycle{status, release_date, discontinued_date, successor, predecessor}, alternatives_considered[] },
  "core":          { загальні атрибути, однакові для всіх категорій },
  "attributes":    { категорійні атрибути за онтологією категорії },
  "extra":         { атрибути, знайдені у джерелах, але відсутні в онтології (ключ = нормалізована назва з джерела) },
  "media":         { images[], documents[] (datasheet, manual, DoC), videos[] },
  "offers":        [ { seller, region, price, currency, availability, url, as_of } ],
  "relations":     { variants[], accessories[], compatible_with[], replaces[], replaced_by[] },
  "unresolved":    [ { field, status, reason, search_log[] } ],
  "warnings":      [ ... ],
  "meta":          { run_id, mode, rounds, duration_ms, cost_usd, sources_consulted, connectors_failed[], schema_version, generated_at }
}
```

### 2.1 `identity`

`identity.status`: `resolved` | `resolved_with_ambiguity` | `unresolved`. При `resolved_with_ambiguity` у `alternatives_considered[]` перелічені інші кластери з їх score. `variant.axes` — об'єкт типу `{ "color": "black", "storage_gb": 256, "region": "EU" }`; осі беруться з онтології категорії.

### 2.2 `core` (для всіх категорій)

| Поле | Тип |
|------|-----|
| `description_short`, `description_long` | string (з джерел, не генерується) |
| `dimensions` | `{length, width, height}` mm, з `context` (`product` \| `package`) |
| `weight` | g, з `context` (`net` \| `gross` \| `with_battery`) |
| `color`, `material`, `country_of_origin` | enum/string |
| `warranty` | `{months, type}` |
| `in_the_box[]` | list |
| `certifications[]` | list (CE, FCC, RoHS, IP-рейтинг як окреме поле `ip_rating`) |
| `energy_label` | `{class, eprel_id}` |
| `msrp` | `{amount, currency, region, as_of}` |
| `release_date`, `eol_date` | date |
| `package` | `{dimensions, weight, gtin}` |

### 2.3 `attributes` (категорійні)

Онтологія категорій: дерево (`electronics > smartphones`), у кожного вузла набір атрибутів з типом, одиницею, tolerance, діапазоном, `variant_specific` прапором, синонімами (uk/en/de/pl/ru/zh/ja) і `expected_in: [datasheet|manual|retail]` (використовується hole-driven search). Джерела онтології для старту: schema.org, Icecat category features, GS1 GPC, Amazon browse-node атрибути, Wikidata properties. Онтологія версіонується.

Атрибути, знайдені у джерелах поза онтологією, йдуть в `extra` під нормалізованим ключем і після накопичення частоти автоматично пропонуються до онтології (док 08).

### 2.4 `offers`

Не факти, а спостереження. Не голосуються, агрегуються. Кожен з `as_of`, `seller`, `region`, `condition` (`new`/`used`/`refurbished`). Кеш 1 год.

### 2.5 `unresolved`

```json
{ "field": "attributes.battery_capacity_mah", "status": "conflict",
  "reason": "tier A says 2000, three C-tier copies say 2500; judge abstained",
  "candidates": [...],
  "search_log": ["\"GSR 12V-35 FC\" battery capacity", "\"GSR 12V-35 FC\" Akku Kapazität", "site:bosch-professional.com \"GSR 12V-35 FC\""] }
```

## 3. Гарантії, що перевіряються схемою та Guard

- `status = verified` ⇒ `len(independent(sources)) ≥ 2` або `any(tier == A)`; `confidence ≥ 0.85`.
- `status = conflict` ⇒ `value = null`, `len(candidates) ≥ 2`.
- `status = inferred` ⇒ `inferred_from` присутній.
- `status = unknown` ⇒ `value = null`, `sources = []`, є запис у `unresolved`.
- Немає `value` без `sources` (крім `inferred` і `unknown`).
- `gtins[]` усі з валідною контрольною сумою.
