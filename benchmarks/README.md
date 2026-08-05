# Benchmarks

Measured tokens/sec for the four generative models in this stack, on one 16 GB Apple Silicon laptop, with the harness that produced them.

**The headline: throughput is not a constant.** The same model measured 36.0 tok/s on short answers and 31.3 tok/s on a 4,000-token one — a 9% decline driven entirely by output length. Any single number quoted without the generation length attached is missing the part that changes it.

> See the [main README](../README.md) for the canonical tested-on version matrix.

---

## Short-answer throughput

Fixed token budgets, three warm repeats per prompt, median reported.

| Model | Format | Generation tok/s | Range | End-to-end tok/s | Warm TTFT |
|-------|--------|------------------|-------|------------------|-----------|
| `mistralai/ministral-3-3b` | GGUF | **50.7** | 50.2–51.7 | 47.8 | 0.30s |
| `deepseek/deepseek-r1-0528-qwen3-8b` | MLX | **36.0** | 34.3–36.4 | 34.4 | 0.33s |
| `zai-org/glm-4.6v-flash` | MLX | **30.3** | 29.5–30.6 | 27.6 | 0.82s |
| `google/gemma-2-9b` | GGUF | **20.4** | 19.5–21.1 | 18.8 | 0.64s |

Two rates, because quoting one of them hides something. **Generation** measures decode speed from the first token to the last, which is what the model is capable of. **End-to-end** divides by total request time including prompt processing, which is what you actually wait through. The gap widens on short answers, where prompt processing is a larger share of the total.

Full per-prompt data, environment, and reproduction steps: [`measurements.md`](measurements.md).

---

## Long answers are slower

The same models measured again with a 4,096-token ceiling instead of a few hundred:

| Model | Short answers | Long answers | Change |
|-------|---------------|--------------|--------|
| `deepseek/deepseek-r1-0528-qwen3-8b` | 36.0 | 33.1 | −8% |
| `zai-org/glm-4.6v-flash` | 30.3 | 29.4 | −3% |

Within a single run the effect is cleaner still, because the only variable is how much the model wrote:

| Output length | DeepSeek R1 | GLM 4.6V |
|---------------|-------------|----------|
| ~300–400 tokens | 34.4 | 30.6 |
| ~4,095 tokens | 31.3 | 26.5 |
| | **−9%** | **−13%** |

Attention cost grows with the KV cache, and the cache grows with every token generated. A long answer is slower per token than a short one from the same model on the same hardware.

<details>
<summary><b>Why this matters for quoted benchmark numbers</b></summary>

Published tokens/sec figures rarely state how long the generated answer was. Given a 9–13% spread between short and long outputs on identical hardware, two sources can disagree by more than 10% while both being correct and honest.

It also means the number you feel in a chat interface is not the number in a benchmark table. Benchmarks tend toward short outputs; real conversations run long, and long is the slower end of the range.

The practical version: treat any single tokens/sec figure as the top of a range rather than a point, unless the generation length is stated alongside it.

</details>

---

## Reasoning models need far more room than the defaults give them

Running with a generous ceiling revealed how much these models actually generate when nothing cuts them off:

| Prompt | DeepSeek R1 needed | GLM 4.6V needed |
|--------|--------------------|-----------------|
| Multi-step word problem | 2,150 | 299 |
| Write a function | 4,095+ | 622 |
| Summarise a passage | 395 | 508 |
| Open-ended question | 4,095+ | 2,287 |
| Translate a sentence | 529 | 4,095+ |

`4,095+` means the model was still generating when the ceiling stopped it.

The open-ended question is a casual request for advice about laptop memory. DeepSeek R1 spent more than 4,095 tokens on it and had not finished. A reasoning model's visible answer is the small part; the thinking phase consumes the same budget and consumes most of it.

**This is why a default response limit produces no answer at all.** A 300-token cap — the default in at least one UI in this stack — is roughly a seventh of what this model needs for a simple question. The budget is exhausted mid-thought, and what arrives is an empty response rather than a truncated one. See [`../sillytavern/`](../sillytavern/) for how that surfaces in practice.

Budget at least **4,000 tokens** for a reasoning model, and more if the answer might be involved. The floor is set by the thinking phase rather than the visible answer — a closed-form question with a one-line answer consumed a full 4,000-token budget in a separate run ([`../web-search/`](../web-search/)) — so budget by whether the model reasons, not by how short the answer looks.

---

## An image costs seconds, not tokens per second

Both multimodal models here were measured on the same image with paired text-only controls asking a comparable question, so the cost of the image is a delta rather than a figure standing alone.

| Model | Time to first token, with image | Text control | Cost of the image |
|-------|--------------------------------|--------------|-------------------|
| `zai-org/glm-4.6v-flash` | 9.74s | 1.60s | **+8.1s** |
| `mistralai/ministral-3-3b` | 3.86s | 0.55s | **+3.3s** |

**Decode speed is unaffected.** Both models generated at the same rate whether the prompt carried an image or not — any difference sat at the edge of run-to-run variation. The vision tower runs during prompt processing, so an image is paid for once, up front, before the first token appears. Once generation starts, it costs nothing.

The practical version: an interface that pauses for several seconds after you attach a screenshot and then answers at normal speed is behaving correctly.

### The smaller model is not the worse choice here

On a screenshot-extraction task — reading a six-row table of names, statuses, and latencies — the 3B model matched the 9B exactly, every value correct, while processing the image in less than half the time on under half the memory.

The larger model earns its cost on visual questions that need reasoning rather than transcription; it spent 77% of its output budget thinking before answering a chart-comparison question. For reading text off an image, the small model is the better default. See [`../model-selection-guide.md`](../model-selection-guide.md).

<details>
<summary><b>Running the vision set</b></summary>

```bash
python3 bench.py --models <multimodal-id> \
  --prompts prompts-vision.json --repeats 3 --unload-between
```

The image is `dashboard.png` at 1024×640, generated by `make-test-image.py` in this directory so it can be regenerated or altered rather than being an opaque binary. Vision models tile an image into tokens by resolution, so these figures are specific to that size.

A text-only model will fail the image prompts. The harness records that as a failure with a reason rather than a zero.

</details>

---

## Cold start costs seconds, not milliseconds

The first request after a model loads pays for reading weights from disk and initialising the runtime:

| Model | Cold TTFT | Warm TTFT | Ratio |
|-------|-----------|-----------|-------|
| `mistralai/ministral-3-3b` | 3.7s | 0.30s | 12× |
| `google/gemma-2-9b` | 4.5s | 0.64s | 7× |
| `deepseek/deepseek-r1-0528-qwen3-8b` | 7.2s | 0.33s | 22× |
| `zai-org/glm-4.6v-flash` | 10.0s | 0.82s | 12× |

Cold time roughly tracks model size. It is paid once per load, not once per session — and because models stay resident until their idle timeout rather than being evicted on the next request, a model you keep using stays warm. See [`../lm-studio/`](../lm-studio/) on TTL and what actually reclaims memory.

The practical consequence: a UI that feels slow on its first message and fine afterwards is not misconfigured. That is the cold start, and it is normal.

---

## Gemma 2 is slower than its size predicts

Gemma 2 9B runs at 20.4 tok/s against Ministral 3B's 50.7 — expected, given roughly twice the weights. But normalising for size doesn't close the gap. Both run on the same GGUF engine, and Gemma ran at the *smallest* context of the four models measured, so it carried the least KV-cache overhead:

| Model (GGUF only) | Weights | Context | tok/s | Weights × tok/s |
|-------------------|---------|---------|-------|-----------------|
| `mistralai/ministral-3-3b` | 2.99 GB | 64K | 50.7 | 152 GB/s |
| `google/gemma-2-9b` | 5.76 GB | 8K | 20.4 | 117 GB/s |

Same engine, same quantisation level, and Gemma sustains 23% less effective throughput per gigabyte of weights while carrying the lighter cache. Something model-specific is costing it.

<details>
<summary><b>A hypothesis, offered as one</b></summary>

Gemma 2 uses an unusually large vocabulary — around 256,000 tokens against 32,000–150,000 for most models this size. The output projection runs over the full vocabulary for every token generated, so a larger vocabulary is a per-token cost that scales with neither parameter count nor context length.

That would explain the shape of the gap. It has not been isolated here, and this repo has not measured it directly, so treat it as a plausible explanation rather than a finding. Gemma's 8K context ceiling is a separate property of the model, not a memory compromise.

</details>

---

## Reproduce it

The harness is [`bench.py`](bench.py) — Python standard library only, no virtualenv, no dependencies to install. The prompt set is [`prompts.json`](prompts.json), five prompts covering reasoning, code, summarisation, chat, and translation.

```bash
python3 bench.py --list                    # what the server is serving
python3 bench.py --models <id> --repeats 1 # smoke test one model
```

The full run, smallest model first:

```bash
caffeinate -i python3 bench.py \
  --models <id1>,<id2>,<id3>,<id4> \
  --repeats 3 --unload-between \
  --out results.json | tee run.md
```

`--unload-between` evicts models before each one so cold-start timings are real; drop it to leave your running stack alone. `caffeinate -i` matters — a full run takes 30–45 minutes and an idle sleep partway through costs you all of it.

The harness reports empty cells and a failures table when a model returns nothing, rather than a zero that reads like a measurement. Token counts come from the server's own usage block; if a server doesn't send one, the output labels those rows as approximate rather than mixing the weaker source in silently.

---

## Scope

These are decode-throughput and latency measurements for text generation on one machine, with the methodology and harness shipped so they can be checked or re-run elsewhere. Answer quality is not measured — nothing here says which model is *better*, only which is faster and by how much. Vision inputs are out: the multimodal model is measured on its text path only. For choosing a model on grounds other than speed, see [`../model-selection-guide.md`](../model-selection-guide.md).
