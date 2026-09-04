# 03. Алгоритм

## 0. Огляд

```
resolve(name, hints, mode):
  R0  understand(name)                     -> QueryHypothesis
  R1  anchor_discovery(hypothesis)         -> Anchor (identifiers, variant, category) | ambiguity
  R2  harvest(anchor, schema)              -> claims
  R3  loop while budget and gain > eps:
        holes = coverage_gaps(claims, schema)
        leads = hole_driven_search(anchor, holes)
        claims += harvest(leads)
  R4  truth = truth_discovery(claims)      -> resolved fields
  R5  guard(truth)                         -> validated fields + unresolved
  R6  assemble(...) ; learn(...)
```

Раунди R2-R3 повністю паралельні всередині себе. R4 запускається інкрементально після кожного раунду, щоб стрімити проміжний стан і рахувати `gain`.

## 1. R0. Query Understanding

```python
def understand(name: str, hints: Hints) -> QueryHypothesis:
    text = unicode_nfkc(name).strip()
    ids = extract_identifiers(text)              # GTIN (checksum ok), ASIN, MPN-patterns
    brand = detect_brand(text, pkg, hints)       # словник -> PKG aliases -> LLM
    model, variant_tokens = split_model_variant(text, brand)
    category = classify_category(text, brand, model, pkg)   # top-3 з ймовірностями
    aliases = pkg.lookup_aliases(text, brand, model)         # можливо, вже знаємо товар
    variants = generate_query_variants(brand, model, variant_tokens, category, langs_for(brand, category))
    return QueryHypothesis(ids, brand, model, variant_tokens, category, aliases, variants)
```

Особливості:

- Код моделі зберігається дослівно й у "нормалізованому" вигляді (без пробілів/дефісів, upper), обидва йдуть у запити.
- Якщо `pkg.lookup_aliases` дає сильний хіт (cosine > 0.95 по alias-embeddings і збіг бренду), R1 пропускається: якір беремо з PKG, а в R2 виконується лише refresh застарілих полів.

## 2. R1. Anchor Discovery

Мета: знайти **ідентифікатори** та однозначно визначити товар і варіант.

```python
async def anchor_discovery(h: QueryHypothesis, ctx) -> Anchor | Ambiguity:
    tasks = []
    for conn in connectors.with_capability("lookup_by_id") if h.ids:
        tasks.append(conn.lookup(h.ids, ctx))
    for q in h.variants[:K_ANCHOR]:
        for conn in connectors.ranked_for(h.category, purpose="anchor"):   # виробник, Icecat, Wikidata, GS1, дистриб'ютори, Google
            tasks.append(conn.search(q, ctx))
    leads = flatten(await gather_with_budget(tasks, ctx.budget.anchor))

    pages = await fetch_many(top_by_prior(leads, N_ANCHOR_PAGES), ctx)
    cands = []
    for p in pages:
        ids = extract_identifiers(p)                          # JSON-LD gtin/mpn/sku, текстові патерни, PDF-заголовки
        title_entity = parse_entity(p.title, p.h1, p.breadcrumbs)
        cands.append(EntityCandidate(ids, title_entity, source=p.source, tier=p.tier))

    clusters = cluster_by_identifiers_and_model(cands)       # union-find по спільних GTIN/MPN, потім fuzzy по моделі
    scored = [(c, anchor_score(c, h)) for c in clusters]
    best, second = top2(scored)
    if best.score < T_ANCHOR or (second and best.score - second.score < T_MARGIN):
        return Ambiguity(options=[c.summary for c, _ in scored[:5]])
    return Anchor.from_cluster(best)
```

`anchor_score` враховує: кількість незалежних джерел у кластері, наявність джерела рівня A, точність збігу моделі з гіпотезою, узгодженість варіантних осей з `variant_tokens`.

**Неоднозначність.** Поведінка керується параметром `on_ambiguity`:

- `auto` (за замовчуванням для batch): беремо найкращий кластер, виставляємо `identity.confidence` і `warnings[]` з альтернативами;
- `ask`: повертаємо `disambiguation_needed` з варіантами (для інтерактивного UI);
- `all`: резолвимо кожен варіант окремим піддокументом (корисно для каталогізації).

## 3. R2. Harvest

```python
async def harvest(anchor, schema, leads, ctx) -> list[Claim]:
    pages = await fetch_many(leads, ctx)                      # per-domain concurrency, cache, proxies
    claims = []
    for p in pages:
        m = entity_match(p, anchor)                           # 0..1 + variant_axes_match
        if m.score < T_MATCH_MIN: continue
        extracted = await run_extractors(p, schema_for(anchor.category))   # structured || tables || pdf || llm паралельно
        for e in extracted:
            if not grounded(e.value, e.span, p.text): continue     # захист від галюцинацій
            e = normalize(e, schema)
            if e.field in schema.variant_specific and not m.variant_ok: continue
            claims.append(Claim(entity_match=m, source=p.source, **e))
    return claims
```

Ліди для R2 формуються з: результатів R1 (усі сторінки кластера), `lookup_by_id` по знайдених identifiers у всіх конекторах, які це вміють, та top-K пошукових результатів по кожному query variant.

## 4. R3. Hole-driven search

```python
def coverage_gaps(fields, schema) -> list[Hole]:
    holes = []
    for f in schema.fields:
        st = fields.get(f)
        if st is None or st.status in ("unknown", "single_source", "conflict") or st.confidence < T_FIELD:
            holes.append(Hole(f, priority=schema.weight[f] * (1 - (st.confidence if st else 0))))
    return sorted(holes, key=lambda h: -h.priority)

def hole_queries(anchor, hole) -> list[QueryVariant]:
    m = anchor.best_model_string
    return [
        f'"{m}" {hole.field.human_name}',
        f'"{m}" {hole.field.human_name_lang[lang]}' for lang in anchor.langs,
        f'"{anchor.mpn}" {hole.field.human_name}' if anchor.mpn else None,
        f'{anchor.brand} {m} datasheet' if hole.field.in_datasheet else None,
        f'{anchor.brand} {m} manual pdf' if hole.field.in_manual else None,
    ]
```

Раунд виконується, поки:

- є бюджет;
- `gain = Σ Δconfidence` за попередній раунд > ε (типово 0.02 × кількість полів);
- у черзі є holes з priority вище порога.

Поля, для яких conflict залишається після 2 раундів, отримують спеціальний запит "розв'язувача": `"{model}" "{candidate_a}"` та `"{model}" "{candidate_b}"`, щоб знайти незалежні свідчення саме за кандидатами.

## 5. R4. Truth Discovery

### 5.1 Підготовка claims

1. **Value equivalence.** Для кожного поля claims групуються в класи еквівалентності за типом:
   - numeric: після конвертації одиниць, tolerance з схеми (`weight: ±2%`, `screen_size: ±0.05"`), округлення виробника (`6.1"` = `6.12"`);
   - string: NFKC, casefold, видалення пунктуації, транслітерація, synonym table;
   - enum: mapping до канону;
   - list: Jaccard ≥ 0.8 → об'єднання, з розміткою елементів, які підтверджені кожним джерелом;
   - date: ISO, з tolerance на "місяць/рік".
2. **Independence detection.** Claims з різних джерел зливаються в один "голос", якщо:
   - MinHash-подібність spec-блоку > 0.9 (магазини копіюють одна в одної);
   - домени належать одному власнику (список афіліацій: Rozetka/Prom, Amazon/*.amazon.*, Ceneo/Allegro тощо);
   - джерело явно посилається на інше як на першоджерело.
   Такий кластер отримує вагу `max(w_i) × (1 + 0.1 × log(n))`, а не `Σ w_i`.
3. **Hard constraints (pre-filter).** Претенденти, що порушують: контрольну суму GTIN, тип, діапазон категорії (`smartphone.weight ∈ [80, 400] g`), крос-польові інваріанти (`battery_wh ≈ battery_mah × voltage / 1000 ± 10%`, `aspect_ratio ≈ res_w / res_h`) — відкидаються з причиною у trace.

### 5.2 Ваги джерел

```
w(claim) = prior(tier)                       # A:1.0 B:0.75 C:0.45 D:0.25 E:0.15
         × ledger(source, category, field)   # Beta posterior mean, старт 0.5
         × entity_match.score
         × extractor_confidence
         × freshness(field, fetched_at)      # 1.0 для immutable; спад для time-varying
         × specificity(page)                 # сторінка саме про цей товар (1.0) vs листинг/порівняння (0.6)
```

### 5.3 Ітеративне голосування (CRH-стиль)

```python
def truth_discovery(claims_by_field, iters=10):
    w = {s: initial_weight(s) for s in sources(claims_by_field)}
    for _ in range(iters):
        truth = {}
        for field, groups in claims_by_field.items():          # groups = equivalence classes
            score = {g: sum(w[c.source] * c.local_weight for c in g.claims_independent) for g in groups}
            truth[field] = argmax(score), softmax_margin(score)
        # оновлення ваг: джерело, що часто суперечить істині, втрачає вагу
        for s in w:
            agree = sum(1 for c in claims_of(s) if c.group is truth[c.field].group)
            total = len(claims_of(s))
            w[s] = initial_weight(s) * (alpha + agree) / (alpha + beta + total)   # згладжений Beta
        if converged(truth): break
    return truth
```

Ключова відмінність від наївного "більшість перемагає": вага джерела **всередині прогону** підлаштовується під його узгодженість з рештою доказів, а межпрогонна вага живе в ledger. Джерело, яке помиляється у вазі, автоматично отримує менший голос і по габаритах.

### 5.4 Статуси

| Статус | Умова |
|--------|-------|
| `verified` | ≥2 незалежні голоси за переможця, margin ≥ 0.6, немає голосу рівня A за іншого кандидата; **або** 1 голос рівня A без суперечностей |
| `single_source` | 1 незалежний голос, немає суперечностей, confidence ≥ 0.5 |
| `conflict` | margin < 0.6 або рівень A суперечить більшості; у виході `value = null`, `candidates[]` з доказами, `resolution_hint` |
| `inferred` | значення виведене (з сімейства моделей, з формули, з `shared_across_variants`), не знайдене явно; **ніколи** не рахується у precision `verified` |
| `unknown` | claims відсутні; `search_log` пояснює, що шукали |

### 5.5 LLM-арбітр (лише для `conflict`)

Отримує: поле, кандидатів, по 3 evidence-фрагменти на кандидата з URL і tier, відомі інваріанти. Повертає структуровано: `choice | abstain`, `reason`, `which_evidence_is_about_other_variant[]`. Його голос має вагу рівня B і йде в ту саму формулу, тобто він може переважити суперечку між двома C-джерелами, але не перебити виробника. Найчастіша корисна робота арбітра — помітити, що одне з джерел описує **сусідню модель**, після чого ці claims знижуються в entity_match і голосування переграється.

## 6. R5. Guard

1. JSON Schema + Pydantic валідація.
2. Повторний прогін hard constraints на фінальному наборі (крос-польові інваріанти могли зламатись після вибору різних переможців).
3. Grounding re-check: фінальне значення знаходиться у snapshot хоча б одного цитованого джерела.
4. Variant leakage: якщо поле `variant_specific` і всі докази з `variant_ok=false` — поле переводиться в `unknown`.
5. Time-varying поля (`offers[]`) виносяться окремо з `as_of`, ніколи не голосуються, а агрегуються (min/median/list).

## 7. R6. Assemble & Learn

- Складання документа за схемою (док 05), `unresolved[]` з причинами і `search_log`.
- Запис у PKG: aliases (усі назви зі сторінок з entity_match ≥ 0.9), identifiers, resolved fields, relations (successor/predecessor/variants, знайдені на сторінках виробника).
- Оновлення ledger: для кожного джерела, що голосувало, `alpha += agree`, `beta += disagree` по `(domain, category, field)`.
- Запис trace та метрик прогону.

## 8. Складність та бюджет (режим `standard`, T1)

| Крок | Типова кількість | Час |
|------|------------------|-----|
| R0 | 1 LLM-виклик або 0 | < 1 с |
| R1 | 8-15 пошукових запитів, 10-20 fetch | 4-8 с |
| R2 | 30-60 fetch, 30-60 structured/table extractions, 10-20 LLM extractions | 8-15 с |
| R3 ×2 | 10-30 запитів, 20-40 fetch | 8-20 с |
| R4-R6 | CPU + ≤3 LLM-арбітражі | 1-3 с |

Усі числа налаштовуються бюджетом; для `fast` R3 вимикається, LLM-екстрактор лишається тільки для сторінок рівня A.

## 9. Чому це сильніше за Perplexity / Exa

| Аспект | Perplexity / Exa | PTE |
|--------|------------------|-----|
| Ідентичність | Немає; змішує варіанти та сусідні моделі | Identifier-anchoring + entity matcher з variant axes |
| Джерела | Один індекс, top-N сторінок | Десятки конекторів, вертикальні бази, PDF, архіви, регіональні індекси |
| Конфлікти | LLM обирає "правдоподібне" | Зважене незалежне голосування + constraints + ledger |
| Копії | 10 магазинів з однією помилкою = "консенсус" | Копії згортаються в 1 голос |
| Повнота | Один прохід | Hole-driven ітерації до насичення |
| Правдивість | Цитати на рівні речення | Grounding check на рівні значення, abstain |
| Пам'ять | Немає | PKG + ledger: система стає точнішою з кожним прогоном |

Perplexity, Exa, Tavily при цьому підключаються як конектори рівня E: їх відповіді використовуються як **ліди** (URL для fetch), а не як докази.
