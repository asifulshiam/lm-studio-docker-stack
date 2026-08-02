# Server configuration

Settings in LM Studio live in three different places, and knowing which is which saves a lot of time hunting through tabs for something that's actually a request parameter.

| Where | What lives there | How it's set |
|-------|------------------|--------------|
| **Server flags** | Port, bind address, CORS | `lms server start` options |
| **Load-time flags** | Context length, GPU offload, TTL, concurrency | `lms load` options |
| **Per-request** | Temperature, top-k, top-p, penalties, max tokens | JSON body of each API call |
| **GUI only** | Flash attention, KV cache offload, CPU thread count | Load tab in the application |

The practical consequence: if a setting isn't taking effect, check whether you're setting it in the right layer. Temperature configured in the GUI is a default for the built-in chat window — it does not apply to requests arriving from Open WebUI, which sends its own.

---

## Server flags

```bash
lms server start                          # port 1234, bound to 127.0.0.1
lms server start -p 1235                  # different port
lms server start --cors                   # allow browser-origin requests
lms server start --bind 0.0.0.0           # accept connections from the network
```

With no `-p`, the server reuses whatever port it ran on last.

### Port

Default `1234`. Change it if something else has claimed the port:

```bash
lsof -i :1234
```

Changing it means updating every container that points at the API — each service's Compose file in this repo references the port through an environment variable for exactly that reason.

### CORS

Required only if a browser page makes requests directly to the API from JavaScript. The containers in this stack are server-side clients, so they don't need it. Enable it for local web development against the API, and leave it off otherwise.

### Bind address — read before using `0.0.0.0`

The default `127.0.0.1` accepts connections from the local machine only. Binding to `0.0.0.0` accepts them from anything that can reach your machine on the network.

**The API has no authentication.** There is no token, no password, and no rate limit. Anyone who can reach the port can send requests, load models, and consume your GPU. On a home network behind a router that's a considered risk; on café, campus, coworking, or hotel Wi-Fi it means handing an inference endpoint to strangers.

If you need access from another device, prefer an SSH tunnel over binding wide:

```bash
# From the remote machine — forwards its local 1234 to the Mac's 1234
ssh -N -L 1234:localhost:1234 user@mac-hostname
```

The tunnel is authenticated, encrypted, and disappears when you close it. Docker containers on the same host do **not** need `0.0.0.0` — they reach the host through `host.docker.internal`, which the default bind already serves.

---

## Load-time flags

```bash
lms load <model-key> -c <tokens> --gpu <ratio> --ttl <seconds> -y
```

### Context length — the memory lever

`-c` sets the context window, and the KV cache allocated for it is often a larger memory cost than the weights. Cutting context is usually more effective than switching to a smaller model.

Each model has a ceiling it was trained for; requesting more than the maximum fails, and requesting far less than you need causes silent truncation mid-conversation.

| Model | Maximum | Practical on 16 GB |
|-------|---------|--------------------|
| `mistralai/ministral-3-3b` | 256K | 64K |
| `zai-org/glm-4.6v-flash` | 128K | 64K |
| `deepseek/deepseek-r1-0528-qwen3-8b` | 32K | 32K |
| `google/gemma-2-9b` | 8K | 8K |

Gemma's 8K is a property of the model, not a memory compromise — it can't go higher.

### GPU offload

`--gpu max` puts all layers on the Metal GPU, which is what you want on Apple Silicon. Automatic is the default and is usually correct; the flag exists for when it isn't. `--gpu off` forces CPU inference, which is dramatically slower and mainly useful for diagnosing whether a problem is GPU-related.

### TTL and concurrency

`--ttl <seconds>` unloads a model after that much idle time. Worth setting habitually, since it's the mechanism that stops forgotten models from occupying memory.

`--parallel <count>` sets how many predictions can run at once. Higher concurrency starts each request sooner but slows each one down. For a single-user stack the default is fine; raise it only if several UIs are genuinely in use simultaneously.

---

## Per-request parameters

Sampling settings travel in the request body, not the server config:

```bash
curl -s http://localhost:1234/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek/deepseek-r1-0528-qwen3-8b",
    "messages": [{"role": "user", "content": "Explain KV cache in two sentences."}],
    "temperature": 0.5,
    "top_k": 100,
    "repeat_penalty": 1.1,
    "max_tokens": 800
  }' | jq -r '.choices[0].message.content'
```

Each UI in this stack sends its own values and exposes them in its settings — Open WebUI under model parameters, SillyTavern under presets. Change them there, not in LM Studio.

### Starting points

Values worth trying, arrived at through use rather than theory:

| Model | Temperature | Top-K | Top-P | Repeat penalty |
|-------|-------------|-------|-------|----------------|
| `deepseek/deepseek-r1-0528-qwen3-8b` | 0.5 | 100 | — | 1.1 |
| `zai-org/glm-4.6v-flash` | 0.5 | 100 | 0.6 | 1.1 |
| `google/gemma-2-9b` | 0.8 | 100 | 0.95 | 1.1 |
| `mistralai/ministral-3-3b` | 0.7 | 100 | — | 1.1 |

Two notes on how these differ from common defaults. Reasoning models benefit from lower temperature — 0.5 for DeepSeek keeps chains of thought from wandering, and raising it produces more creative but less reliable reasoning. And a top-k of 100 rather than the more typical 40 noticeably improved vocabulary variety on these models without hurting coherence.

---

## GUI-only settings

Not reachable from the CLI. Set them in the Load tab before loading, or accept the defaults.

| Setting | Recommended | Why |
|---------|-------------|-----|
| Flash Attention | On | Reduces attention memory; supported across these models |
| Keep Model in Memory | On | Prevents reload between requests |
| Offload KV Cache to GPU | On | Keeps cache in Metal memory rather than system RAM |
| CPU Threads | Leave default | Only matters when layers run on CPU |
| Context Overflow | Truncate Middle | Preserves the system prompt and recent turns when context fills |

Context Overflow is the one that changes behavior most visibly. When a conversation exceeds the window, truncating the middle keeps both the instructions at the start and the recent exchange, which is almost always better than dropping either end.

---

## Scripting notes

```bash
lms load <model-key> -c 32768 --gpu max --ttl 3600 -y   # -y skips prompts
lms unload -a                                            # bare unload prompts when ambiguous
lms ps --json | jq .                                     # machine-readable state
lms ls --json                                            # machine-readable inventory
```

Three behaviors that will bite an unattended script:

**`lms unload` with no argument prompts** when more than one model is loaded. Pass an identifier or `-a`.

**`lms load` stacks rather than swaps.** Explicit loads don't trigger auto-evict, so a script that loads models in sequence accumulates them. Unload between loads.

**`lms server start` reuses the last port** when `-p` is omitted. Pass the port explicitly in scripts rather than inheriting whatever the last interactive run left behind.
