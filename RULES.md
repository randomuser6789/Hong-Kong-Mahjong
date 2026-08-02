# Hong Kong Old Style Mahjong — Rules Specification (開心鬥一番 variant)

This file is the single source of truth for game logic. Do NOT deviate from it
or invent fan values. If a rule is ambiguous or missing, STOP and ask.

Values marked [VERIFIED] were confirmed against 開心鬥一番 and/or
mahjonggame.hk/learn/hk-mahjong/scoring. Do not change them.

## 1. Tiles (144 total)
- Suits (數牌): 萬 (characters), 筒 (dots), 索 (bamboo). Ranks 1–9, ×4 = 108.
- Honors (字牌): winds 東南西北 ×4 = 16; dragons 中發白 ×4 = 12.
- Bonus (花牌): flowers 梅蘭菊竹 + seasons 春夏秋冬, one each = 8.
- Total: 108 + 16 + 12 + 8 = 144.

### Tile encoding (for code)
- 0–8   = 萬 1–9
- 9–17  = 筒 1–9
- 18–26 = 索 1–9
- 27–30 = winds 東南西北
- 31–33 = dragons 中發白
- 34–41 = flowers/seasons (bonus)

## 2. Winning hand structure
- Standard: 4 melds + 1 pair (眼).
  - Meld = 順子 (sequence, same suit, 3 consecutive; honors CANNOT sequence)
          or 刻子 (triplet) or 槓 (kong).
- Special hands (do not follow 4+1):
  - 十三么 (Thirteen Orphans): one each of 1/9 in all suits + all 7 honors,
    plus a duplicate of any one.
- 七對子 (Seven Pairs): NOT a valid hand in this ruleset. [VERIFIED — excluded]

## 3. Minimum to win (起糊)
- Minimum: **3 fan (三番起糊)**. [VERIFIED]
- Bonus/flower fan DO count toward reaching the minimum. [VERIFIED]

## 4. Fan table (番數) — [VERIFIED against source]
Fan values are ADDITIVE and stack unless marked "Limit". Limit hands pay the
maximum regardless of computed total.

### 1 fan
| Hand | 中文 | Fan |
|------|------|-----|
| All Chows | 平糊 | 1 |
| Concealed (win by discard, no calls) | 門前清 | 1 |
| Self-draw | 自摸 | 1 |
| Dragon pung/kong (each) | 箭刻 | 1 |
| Seat wind pung/kong | 門風 | 1 |
| Prevailing wind pung/kong | 圈風 | 1 |
| No flowers | 無花 | 1 |
| Win on kong-replacement | 槓上開花 | 1 |
| Rob the kong | 搶槓 | 1 |
| Win on last tile | 海底撈月 | 1 |
| Own flower/season (each) | 花 | 1 |

Note: round wind == seat wind counts twice (2 fan total).

### 2 fan
| Hand | 中文 | Fan |
|------|------|-----|
| Full set of 4 flowers OR 4 seasons | 一台花 | 2 |

### 3 fan
| Hand | 中文 | Fan |
|------|------|-----|
| Half flush (one suit + honors) | 混一色 | 3 |
| All pungs | 對對糊 | 3 |

### 5 fan
| Hand | 中文 | Fan |
|------|------|-----|
| Small Three Dragons | 小三元 | 5 |

### 7 fan
| Hand | 中文 | Fan |
|------|------|-----|
| Full flush (one suit, no honors) | 清一色 | 7 |

### 8 fan
| Hand | 中文 | Fan |
|------|------|-----|
| Great Three Dragons | 大三元 | 8 |
| Small Four Winds | 小四喜 | 8 |

### 10 fan
| Hand | 中文 | Fan |
|------|------|-----|
| All Honors | 字一色 | 10 |
| Great Four Winds | 大四喜 | 10 |

### Limit hands (pay the cap regardless of total)
| Hand | 中文 |
|------|------|
| Thirteen Orphans | 十三么 |
| All Kongs (four kongs + pair) | 十八羅漢 |
| Heavenly Hand (dealer wins on deal) | 天糊 |
| Earthly Hand (non-dealer wins on first draw) | 地糊 |

### Stacking examples (for tests)
- Concealed + All Pungs + Full Flush = 1 + 3 + 7 = 11 fan.
- Full Flush + All Pungs = 7 + 3 = 10 fan.
- Great Four Winds + All Pungs + Half Flush = 10 + 3 + 3 = 16 → capped to 13.
- Absorption: 大三元/小三元/大四喜/小四喜 absorb their component 箭刻/門風/圈風
  pung fans, but do NOT absorb 對對糊 — all-pungs stacks whenever the hand is
  in fact all pungs.

## 5. Cap (封頂 / 爆棚)
- Cap at **13 fan**. [VERIFIED] Any hand ≥ 13 pays the 13-fan amount.

## 6. Payment
Fan → points, doubling schedule, extended to the 13-fan cap:

| Fan | Points |
|-----|--------|
| 3 | 8 |
| 4 | 16 |
| 5 | 24 |
| 6 | 32 |
| 7 | 48 |
| 8 | 64 |
| 9 | 96 |
| 10 | 128 |
| 11 | 192 |
| 12 | 256 |
| 13 (cap) | 384 |

(Note: 11/12/13-fan point values are extrapolated by doubling — verify against
開心鬥一番 if the app displays payouts at those fan levels.)

- Discard win (出銃): discarder pays the full amount alone. [VERIFIED]
- Self-draw (自摸): all three players pay. [VERIFIED]
- False win (詐糊): penalty applies. [VERIFIED]

## 7. Play flow
- Seats 東南西北; dealer (莊) is 東.
- Dealer keeps dealing (連莊) on a win or draw. [VERIFIED]
- 13 tiles each; dealer draws to 14 to open each turn.
- **No dead wall.** All tiles after dealing form one wall: 144 − 53 dealt
  (13×3 + dealer's 14) = 91 drawable tiles. Normal turns draw from the
  front; kong and flower replacements draw from the back of the same wall.
- 流局 (exhaustive draw): when the wall is empty (front and back meet), the hand
  ends in a draw — no winner, no payment.
- A kong called when the wall is already empty is still legal — it forms
  the meld normally, but draws no replacement tile (there is none). Play
  proceeds straight toward 流局 with no crash and no special-casing beyond
  skipping the replacement draw.
- Discard priority: 食糊 > 碰/槓 > 上 (pung/kong beats chow); win beats all.
- Flowers drawn are set aside face-up and immediately replaced from the back of
  the wall.

## 8. Explicit invariants (for tests)
- Shanten never increases after an optimal draw-and-discard.
- A declared win must satisfy min-fan (3, flowers count) AND a valid structure.
- Non-bonus tiles never exceed 4 of a kind; each flower appears at most once.
- Fan computation is deterministic given a fixed hand + win context.