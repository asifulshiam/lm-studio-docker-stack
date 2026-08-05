# Fixed-context grounding test

Isolates synthesis from retrieval. No search runs. Every model receives byte-identical
context, so any difference in output is the model rather than the pipeline.

Results and interpretation are in [`README.md`](README.md); this file is the fixture
itself, so a reader can reproduce arm B exactly.

The passage below is **written for this test**, not scraped. Facts are accurate; wording is
original. Same rationale as the generated benchmark test image: reproducible, hand-checkable,
no copyright exposure.

## Settings (identical across all runs)

- Web search: **OFF**
- Temperature: 0 · Seed: 0 · max_tokens: 4000
- New chat per run · 3 repeats per model

## The paste block

Paste everything between the rules as a single message.

---

Below are excerpts from several tennis reference pages. Answer only from these excerpts.

**Excerpt 1 — Championships overview**
The 2026 Championships were the 139th edition, held at the All England Club from 29 June
to 12 July 2026. Video review was used in matches for the first time in tournament history.

**Excerpt 2 — Men's singles, 2026**
Defending champion Jannik Sinner beat Alexander Zverev in the final by 6-7(7-9), 7-6(7-2),
6-3, 6-4. The win gave Sinner a second Wimbledon crown and a fifth major overall. Zverev
became the first man born in the 1990s to reach a final at all four majors, and the fifth in
the Open Era to finish as runner-up at all four.

**Excerpt 3 — Notable runs, 2026**
Novak Djokovic passed Roger Federer's record for men's singles match wins at Wimbledon,
reaching 107. His quarter-final against Felix Auger-Aliassime lasted five hours and fifteen
minutes, the longest quarter-final the tournament has recorded.

**Excerpt 4 — Women's singles, 2026**
Linda Noskova won the title on Saturday 11 July, recovering against Karolina Muchova on
Centre Court after a late comeback attempt.

**Excerpt 5 — Men's singles, 2025**
Sinner took his first Wimbledon title, beating defending champion Carlos Alcaraz 4-6, 6-4,
6-4, 6-4, and ending Alcaraz's twenty-match winning streak at the tournament.

**Excerpt 6 — Men's singles, 2024**
Carlos Alcaraz successfully defended his title against Novak Djokovic.

Question: Who won the 2026 Wimbledon men's singles title, and what was the score in the final?

---

## Ground truth

Winner: **Jannik Sinner**, defeating **Alexander Zverev**
Score: **6-7(7-9), 7-6(7-2), 6-3, 6-4**

## Scoring

| Tier | Test | Note |
|------|------|------|
| 1 | Names Sinner | Guessable from training — passing this alone proves nothing |
| 2 | Names Zverev as opponent | First real signal; training-era guesses favour Alcaraz or Djokovic |
| 3 | All four sets exact, in order | The grounding test |
| 4 | Tiebreak digits (7-9) and (7-2) correct | Finest detail available |
| 5 | No year confusion | Excerpts 5 and 6 are the trap |

Record per run: tier reached, plus the verbatim score given. Note any fabricated quotation
marks or invented attribution — that pattern appeared once in the pipeline arm and is worth
tracking here.

## What each distractor catches

- **Excerpt 5** carries a full four-set scoreline from a *different year*. A model
  pattern-matching on "four sets" without checking the year lands here. Three of six sources
  in one pipeline run were wrong-year pages, so this mirrors reality.
- **Excerpt 6** offers a winner with no score, tempting a fabricated one.
- **Excerpt 4** is a same-tournament result from the wrong draw.
- **Excerpt 3** contains numbers (107, 5:15) that are not scores, testing whether the model
  distinguishes a scoreline from any nearby figure.

## Model order

1. `mistralai/ministral-3-3b` — pairs against its nine pipeline runs
2. `google/gemma-2-9b` — **8K, excluded from the pipeline arm; runs here**
3. `deepseek/deepseek-r1-0528-qwen3-8b` — cited sources then answered from training in the
   original Vane test
4. `zai-org/glm-4.6v-flash` — reasoning model; watch for empty returns under budget

Unload between models (`lms unload -a`) — models accumulate rather than swap, and two
resident sets compete for the accelerator budget. See [`../troubleshooting.md`](../troubleshooting.md).

## Perishability

These facts postdate every model tested here, which is the point. They will not stay ahead
of future models' training. Re-running this later means substituting equivalent facts that
postdate whatever is being tested — the design (headline fact that can be bluffed, detail
that cannot, wrong-year distractor carrying a complete plausible answer) is the part that
transfers.
