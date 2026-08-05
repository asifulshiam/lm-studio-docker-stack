# Model selection guide

Five models, four of which generate text. Choosing between them on a 16 GB machine comes down to three questions: how fast do you need the answer, how long does the conversation need to be, and does it involve an image.

Speed and memory here are measured. Answer quality is not — no benchmark in this repo ranks these models by how good their output is, and this guide doesn't pretend otherwise.

> See the [main README](README.md) for the canonical tested-on version matrix.

---

## Start here

| If you need | Reach for | Because |
|-------------|-----------|---------|
| An answer quickly | Ministral 3B | 50.7 tok/s — roughly 2.5× the slowest here |
| Multi-step reasoning or debugging | DeepSeek R1 8B | Strongest reasoning model here. Budget the tokens (see below) |
| Reading a screenshot, table, or chart | Ministral 3B | Matched the larger model on accuracy at 2.5× the speed |
| A harder visual task | GLM 4.6V Flash | Reasons about what it sees, at a cost in latency and tokens |
| A long conversation | Ministral 3B or GLM 4.6V | Both run at 64K context. Gemma caps at 8K |
| A second opinion on a short prompt | Gemma 2 9B | Different model family, different training. Slowest of the four |
| Document retrieval or search | Not a chat choice | See [the embedding model](#the-embedding-model) |

Throughput figures come from [`benchmarks/`](benchmarks/), measured on 16 GB of unified memory.

---

## The four generative models

### Ministral 3B — the default

The fastest by a wide margin, at 50.7 tok/s, and the smallest at 2.99 GB of weights. It runs at 64K context, which is more room than most conversations need.

**It also handles images**, which is easy to miss given its size. On a screenshot-extraction task it read a six-row table — names, statuses, latencies — with no errors, matching the 9B multimodal model while processing the image in 3.3 seconds against 8.1.

Reach for it first, including for most visual tasks. When it's adequate, nothing else here is worth the wait, and it leaves the most memory free for everything else on the machine.

**It reads retrieved text as well as anything here.** Given web results directly it extracted a four-set score with both tiebreak margins, identically across repeated runs, past a decoy answer from a different year — matching the 9B and both reasoning models. See [`web-search/`](web-search/).

Where it struggles is driving a multi-step pipeline itself. In Vane it never triggered a search at all, answering from parameters and producing text that read like an answer — the worst failure mode available, because nothing signals that retrieval didn't happen ([`perplexica/`](perplexica/)). The same split shows up in Open WebUI, where it writes its own search queries: the queries were often poor, and the reading of what they returned was reliable.

### DeepSeek R1 8B — reasoning, with a caveat about budget

Reasons before answering, and the one to use when a problem has steps. **Two models here do this** — GLM 4.6V is the other, which is not obvious from its description as a vision model. It ran at 36.0 tok/s on short answers and 33.1 on long ones.

**It needs far more response budget than defaults allow.** The thinking phase consumes the same token allowance as the answer, and consumes most of it:

| Task | Tokens actually used |
|------|----------------------|
| Multi-step word problem | 2,150 |
| Short summarisation | 395 |
| Open-ended question | over 4,095 |

Set the response limit to **4,000 minimum, and higher for open-ended prompts**. Below that the budget runs out mid-thought and no answer is produced at all — not a truncated one, an empty one. Budget by whether the model reasons rather than by how the prompt looks: it returned empty at 4,000 on a question with a one-line answer. This is the single most common way a reasoning model appears broken when it isn't, and it applies to GLM 4.6V equally. [`troubleshooting.md`](troubleshooting.md) covers how that surfaces.

It's also the least predictable model here on repeat. At temperature 0 and a fixed seed the three non-reasoning models returned byte-identical answers across runs; this one ranged from 12 seconds to 3 minutes on identical input, and aborted once in the MLX engine. Worth knowing before building anything that assumes repeatability.

Its 32K context is the shortest of the three long-context models here, which matters for retrieval-heavy work where documents compete with the conversation for room.

### GLM 4.6V Flash — sees, and reasons about it

Multimodal and, less obviously, a reasoning model. On a chart-reading task it spent 153 of 199 tokens thinking before answering — 77% of the budget — which makes it accurate on visual questions that need a comparison, and expensive on ones that don't.

At 30.3 tok/s it sits mid-pack, and at 7.09 GB it's the largest here. On 16 GB it's effectively a solo model.

**It is not automatically the right choice for images.** On straightforward extraction — reading a table off a screenshot — Ministral matched it exactly while processing the image 2.5× faster and decoding 1.8× faster on under half the memory. Reach for GLM when the visual question needs reasoning rather than transcription, and accept the latency.

Three rough edges worth knowing. It needs the same generous token budget as any reasoning model, or it returns nothing. It wraps its final answer in `<|begin_of_box|>` markers that leak into the response text, which render as literal garbage in a chat interface. And its reasoning sometimes arrives in the response body rather than a separate thinking block — the answer is correct, preceded by several sentences of the model talking itself through the problem. Both are the model's output, not a rendering fault; [`troubleshooting.md`](troubleshooting.md) covers what can and can't be done about it.

### Gemma 2 9B — the short-context outlier

The slowest at 20.4 tok/s, and slower than its size alone explains — it sustains noticeably less throughput per gigabyte than the other GGUF model here, for reasons [`benchmarks/`](benchmarks/) treats as an open question rather than a settled one.

**Its 8K context is a hard ceiling**, a property of the model rather than a memory compromise. That's the constraint that decides most cases: 8K fills quickly once documents are retrieved into it, and in search-augmented chat it generated correct queries, retrieved 27 results, and then had no room left to synthesise them.

The ceiling is the whole story, and it cuts both ways. Given retrieved text that fits — a few hundred tokens rather than 27 pages — it answered exactly and repeatably, matching models with eight times the window ([`web-search/`](web-search/)). Keep what reaches it small and it's a capable reader.

It's a different model family with different training, which is a real reason to reach for it on a short prompt where you want an independent take. Just don't plan a long conversation or a retrieval-heavy one around it.

---

## The embedding model

`text-embedding-nomic-embed-text-v1.5` doesn't generate text and has no meaningful tokens/sec figure. It converts text into vectors so retrieval can find relevant passages — the backend for document search rather than a model you chat with.

At 84 MB it's negligible against everything else here, and it ships bundled with LM Studio rather than needing a download.

**Both UIs that do retrieval ignore it by default.** Open WebUI downloads `all-MiniLM-L6-v2` into its own container on first boot; Vane bundles the same model and runs it on CPU. Neither uses the model server's embedding model unless you point them at it, which means retrieval quality is independent of whichever chat model you have loaded — not obvious, and worth knowing before tuning the wrong thing.

Nomic is the larger and generally stronger of the two; MiniLM is lighter and doesn't compete for memory. Which wins depends on your documents. [`open-webui/`](open-webui/) covers how to switch.

---

## What actually determines whether a model fits

Not system RAM. The number that governs it is the accelerator budget:

```bash
lms runtime survey
```

On a 16 GB machine that reports roughly **11.8 GiB** of Metal-accessible memory. That, not the 16, is the ceiling.

### Context length is the lever, not parameter count

The same 3B model, estimated at two context lengths:

| Context | Estimated total |
|---------|-----------------|
| 8,192 | 3.40 GiB |
| 65,536 | 7.05 GiB |

Same weights, same file — doubling from context alone. Cutting context frees more memory than switching to a smaller model usually does, and it's the first thing to try when something won't load.

Estimated at a **matched** 8K context, the four models order exactly by size:

| Model | Weights | Estimated at 8K |
|-------|---------|-----------------|
| Ministral 3B | 2.99 GB | 3.40 GiB |
| DeepSeek R1 8B | 4.62 GB | 6.02 GiB |
| Gemma 2 9B | 5.76 GB | 6.73 GiB |
| GLM 4.6V | 7.09 GB | 9.25 GiB |

There's no shortcut hiding in the formats — a bigger model costs more. What varies is how much context you ask for.

```bash
lms load <model-key> -c 8192 --estimate-only
```

Two caveats on that command. It reports a conservative ceiling rather than a prediction, and estimates for MLX-format models don't currently vary with the context length passed — those rows carry a `LOW` confidence flag, which is worth believing.

### Running two at once

Models stay resident rather than swapping, so loading a second leaves the first in memory. Two small models fit comfortably on this budget; a large one plus anything else does not. Set `--ttl` so forgotten models release themselves, and check `lms ps` when memory feels tight. [`lm-studio/`](lm-studio/) covers the mechanics.

---

## Sampling settings

Model choice is most of the outcome, but sampling parameters shape it. Reasoning models want lower temperature than chat models — starting points per model, and which layer each setting belongs in, are in [`lm-studio/server-config.md`](lm-studio/server-config.md).

---

## Scope

This is about choosing among the models in this stack for a given task, on the memory budget of a 16 GB Apple Silicon machine. Model quality rankings, fine-tuning, and evaluation methodology are out — the measured claims here are speed, memory, and context, and the qualitative notes are observations from use rather than benchmarks. For the numbers themselves see [`benchmarks/`](benchmarks/); for models failing in specific ways, [`perplexica/`](perplexica/) and [`troubleshooting.md`](troubleshooting.md).
