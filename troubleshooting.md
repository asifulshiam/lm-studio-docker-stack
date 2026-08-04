# Troubleshooting

Failures in this stack cluster into a handful of shapes, and most of them present as something they aren't. An empty model list looks like a Docker networking problem and is usually a stopped server. A reasoning model that returns nothing looks like a broken connection and is a token budget. Work the ladder before changing configuration.

> See the [main README](README.md) for the canonical tested-on version matrix.

---

## Start here

Four commands, in this order. Most problems resolve before the fourth.

```bash
lms server status                                   # 1. is the model server up?
curl -s http://localhost:1234/v1/models | jq -r '.data[].id'   # 2. is it serving?
docker ps --format '{{.Names}}\t{{.Status}}'        # 3. is the container running?
docker exec <container> sh -c \
  "curl -s -o /dev/null -w '%{http_code}\n' \
   http://host.docker.internal:1234/v1/models"      # 4. can the container reach it?
```

A `200` from step 4 means networking is fine and the problem is inside the application. Anything else means it isn't.

---

## No models in the picker

The single most common failure, and it has two causes that look identical.

**The server isn't running.** LM Studio is a desktop application with an API attached, not a background service. Close the app and every container fails at once. Containers keep retrying, so this presents as a UI that never populates rather than an error.

```bash
lms server status
lms server start
```

**The endpoint points at `localhost`.** Inside a container, `localhost` is the container. A request to `http://localhost:1234` looks for a model server running in that container, finds nothing, and fails silently — the container starts perfectly and the model list is simply empty. Use `http://host.docker.internal:1234/v1` instead, and note the `/v1` suffix, which is easy to drop.

Docker Desktop supplies `host.docker.internal` on macOS and Windows with no configuration. The `extra_hosts` declaration in every Compose file here is portability rather than a requirement:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

`host-gateway` is the Linux mechanism, where the name is not provided automatically. Declaring it means these files work unchanged on either platform — and on Linux, its absence is exactly the silent-empty-model-list failure described above.

<details>
<summary><b>Why a wide bind is the wrong fix</b></summary>

A common suggestion is to bind the server to `0.0.0.0` so containers can reach it. That isn't necessary — `host.docker.internal` reaches the host through the default loopback bind — and it exposes an API with no authentication, no token, and no rate limit to anything that can reach your machine on the network.

See [`lm-studio/server-config.md`](lm-studio/server-config.md) for the bind address discussion and the SSH-tunnel alternative for genuine remote access.

</details>

---

## Port conflicts

Four ports are in play. Every one is an environment variable with a default, so a conflict never means editing YAML.

| Service | Default host port | Variable |
|---------|-------------------|----------|
| LM Studio API | `1234` | `lms server start -p <port>` |
| Open WebUI | `3000` | `OPEN_WEBUI_PORT` |
| Vane | `3001` | `VANE_PORT` |
| SillyTavern | `8000` | `SILLYTAVERN_PORT` |

Find the occupant, then move your service:

```bash
lsof -i :3000
OPEN_WEBUI_PORT=3010 docker compose up -d
```

Or put the variable in a `.env` beside the Compose file — Compose reads it automatically and the repo's ignore rules keep it out of git.

**Changing the API port has reach.** Every container points at `1234` through `LM_STUDIO_URL`. Move the server and each service needs the new value, or they all fail at once in a way that looks like the server went down.

**Only host ports are configurable.** The container-side ports are fixed by the images. `"${OPEN_WEBUI_PORT:-3000}:8080"` maps a host port you choose onto a container port you don't.

---

## A model returns nothing at all

The response arrives empty, or the interface shows a thinking indicator with nothing beneath it. This is not a connection failure. The response budget ran out before the model finished thinking.

**Check whether the model reasons before you assume it doesn't.** Two models in this stack do, and only one of them is described that way — a multimodal model here spent 153 of 199 tokens thinking before producing a two-line answer. A model that isn't labelled as a reasoning model can still behave like one.

Reasoning models spend their token allowance on the reasoning phase, and the visible answer comes after. Measured on this stack with the ceiling raised until generation completed naturally:

| Prompt type | Tokens the model actually used |
|-------------|--------------------------------|
| Multi-step word problem | 2,150 |
| Open-ended question | over 4,095 |
| Short summarisation | 395 |

An open-ended question about laptop memory consumed more than 4,095 tokens and had not finished. Against a 300-token default — which at least one interface here ships with — the budget is exhausted before the answer begins, every time.

**Budget 2,500 tokens minimum for a reasoning model, 4,000 or more for anything open-ended.** Non-reasoning models don't need this, which is why it catches people out: the same setting works fine until the model changes.

Confirm what a model actually spent by asking the API directly — `usage.completion_tokens_details.reasoning_tokens` in a non-streamed response separates thinking from answer:

```bash
curl -s http://localhost:1234/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"<model-key>","max_tokens":800,
       "messages":[{"role":"user","content":"Which is larger, 9.11 or 9.9?"}]}' \
  | jq '.usage'
```

Where to set it: [`sillytavern/`](sillytavern/) under the response-length slider, Open WebUI under model parameters, or `max_tokens` in the request body. Full data in [`benchmarks/`](benchmarks/).

---

## The first message is slow, then it's fine

Expected. The first request after a model loads pays for reading weights from disk and initialising the runtime — between 3.7 and 10 seconds on this hardware, roughly tracking model size. Subsequent requests answer in well under a second.

This is paid once per load, not once per conversation. Models stay resident until their idle timeout expires rather than being evicted when another model is requested, so a model you keep using stays warm.

```bash
lms ps          # what's loaded, and how long each has left
```

If every message is slow rather than just the first, the model is being unloaded between requests — check the TTL it was loaded with.

---

## A model won't load, or everything slows down

Memory, almost always. The number that governs what fits is not system RAM but the accelerator budget:

```bash
lms runtime survey
```

On a 16 GB machine that reports roughly **11.8 GiB** of Metal-accessible memory. That ceiling is what models compete for.

**Check before loading:**

```bash
lms load <model-key> -c 8192 --estimate-only
```

Two caveats on the estimate. It reports a conservative ceiling rather than a prediction, and it reports its own confidence — a `LOW` rating is worth believing. Estimates for MLX-format models do not currently vary with the context length you pass, so for those the figure describes the weights and runtime rather than the full picture.

### Context length is the lever

Cutting context frees more memory than switching to a smaller model usually does. The same 3B model, estimated at two context lengths:

| Context | Estimated total |
|---------|-----------------|
| 8,192 | 3.40 GiB |
| 65,536 | 7.05 GiB |

Same weights, same file, double the memory. If a model won't fit, reduce `-c` before reaching for a smaller model.

```bash
lms load <model-key> -c 16384 --gpu max --ttl 3600 -y
```

### Models accumulate

Loading a second model leaves the first resident — this is the behaviour most likely to surprise you, because just-in-time loading is widely assumed to evict. A UI switching models mid-conversation stacks a second model on top of the first, and memory is reclaimed by idle timeout rather than by eviction.

```bash
lms ps           # see everything resident
lms unload -a    # reclaim it all
```

A bare `lms unload` prompts interactively when more than one model is loaded, which makes it unsafe in a script. Pass an identifier or `-a`. More in [`lm-studio/`](lm-studio/).

---

## Container-specific behaviour

Three things that look like faults and aren't. Each is covered where it belongs:

**Open WebUI reports `unhealthy` for the first few minutes.** It downloads its own embedding model on first boot. Self-resolving — watch `docker logs` for `Application startup complete` rather than restarting. See [`open-webui/`](open-webui/).

**SillyTavern returns 403 to everything, then refuses to start.** Its default IP whitelist can't accommodate requests arriving through Docker's NAT, and disabling the whitelist without authentication makes it exit rather than run exposed. Both are handled by the Compose file here, and credentials are mandatory by design. See [`sillytavern/`](sillytavern/).

**Vane retrieves good sources and then answers from training data.** A model capability limit on 16 GB rather than a configuration problem, documented with the evidence in [`perplexica/`](perplexica/).

### Starting one service without its dependencies

```bash
docker compose up -d --no-deps <service>
```

Naming a service alone does **not** skip `depends_on` — Compose still starts what the service declares it needs. `--no-deps` is what actually limits startup to the one container.

---

## Strange markers in the response text

Some models wrap their final answer in special tokens that are meant to be internal and instead arrive in the response body — `<|begin_of_box|>` and `<|end_of_box|>` around the answer, for instance. Chat interfaces render them literally, so the output looks corrupted.

Nothing in the stack is misconfigured when this happens; the tokens are in the model's output. There's no setting that removes them. If it matters for your use, strip them client-side or pick a model that doesn't emit them — not every model here does.

---

## When the browser won't connect

**Type `http://` explicitly.** Browsers with HTTPS-Only or HTTPS-First enabled upgrade the request, and these services answer in plain HTTP. The result is a TLS parse error rather than a page, which reads as a dead service.

**Check the container is publishing where you think.** `docker ps` shows the actual mapping, which is authoritative over whatever the Compose file said before your last override.

---

## Using more than one backend

If you want a single endpoint in front of several model servers — LM Studio alongside another local backend, or local plus remote — a proxy layer such as LiteLLM sits between the UIs and the backends and presents one OpenAI-compatible API. Nothing in this stack requires it, and it isn't shipped here, but it's the standard answer to "I want both without reconfiguring every UI."

---

## Scope

This covers the failures that come from wiring these particular components together: server availability, container-to-host networking, ports, memory, and response budgets. Application features live in each service's section, and problems with the models themselves — quality, refusals, capability limits — are the model's, not the stack's. For measured latency and throughput figures referenced above, see [`benchmarks/`](benchmarks/).
