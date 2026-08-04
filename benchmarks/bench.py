#!/usr/bin/env python3
"""
bench.py - tokens/sec measurement harness for an OpenAI-compatible local model server.

Standard library only. No virtualenv, no pip install, no network access beyond the
model server itself. Runs on the python3 that ships with macOS.

What it measures, per (model, prompt) pair:

  ttft_s      time to first token - how long the server spends on prompt processing
              and cold-start work before any content comes back
  gen_tps     generation throughput - completion tokens divided by the wall time
              between the first content chunk and the last one. Excludes prompt
              processing, so this is the number that describes decode speed.
  e2e_tps     end-to-end throughput - completion tokens divided by total request
              wall time. Always lower than gen_tps, and it is the number a user
              actually feels.

Both rates are reported because quoting only one of them is how benchmark tables
end up unfalsifiable. Token counts come from the server's own usage block when it
sends one; if it does not, the harness counts streamed chunks instead and labels
the row so the weaker source is visible rather than silently averaged in.

Usage:
    python3 bench.py --models all
    python3 bench.py --models deepseek-r1,gemma-2 --repeats 5 --unload-between
    python3 bench.py --list
"""

import argparse
import base64
import json
import os
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request

DEFAULT_BASE = "http://localhost:1234/v1"
DEFAULT_PROMPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts.json")


# ---------------------------------------------------------------- small helpers

def median_or_none(values):
    """Median of the numeric entries, or None if there are none.

    Written this way on purpose: a benchmark run where every request failed must
    produce an empty cell, not a crash and not a zero that reads like a measurement.
    """
    nums = [v for v in values if isinstance(v, (int, float))]
    if not nums:
        return None
    return statistics.median(nums)


def fmt(value, places=1):
    if value is None:
        return "-"
    return "{:.{p}f}".format(value, p=places)


def sanitize_error(text, limit=140):
    """Flatten an error string so it can live inside a Markdown table cell.

    Servers return HTML error pages, and a raw multi-line body silently destroys
    every row after it. Collapse whitespace, escape pipes, truncate.
    """
    if not text:
        return "unknown error"
    flat = " ".join(str(text).split()).replace("|", "\\|")
    if len(flat) > limit:
        flat = flat[:limit].rstrip() + " ..."
    return flat


def eprint(*args):
    print(*args, file=sys.stderr)


# ---------------------------------------------------------------- server access

def get_models(base_url, timeout):
    """Ask the server which models it knows about."""
    url = base_url.rstrip("/") + "/models"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as exc:
        raise SystemExit("Could not reach the model server at {}: {}".format(url, exc))

    entries = payload.get("data")
    if not isinstance(entries, list) or not entries:
        raise SystemExit("Model server returned no models. Is anything downloaded?")

    ids = []
    for entry in entries:
        if isinstance(entry, dict) and entry.get("id"):
            ids.append(entry["id"])
    if not ids:
        raise SystemExit("Model server returned entries with no usable id field.")
    return ids


def unload_all(verbose=True):
    """Best-effort model eviction between models, so each one starts cold.

    Shells out to the LM Studio CLI. If it is not installed the harness says so
    and carries on rather than dying, because eviction is a nicety and the
    measurement is still valid without it as long as the report says so.
    """
    try:
        proc = subprocess.run(
            ["lms", "unload", "--all"],
            capture_output=True, text=True, timeout=120,
        )
    except FileNotFoundError:
        return "skipped: lms not on PATH"
    except subprocess.TimeoutExpired:
        return "skipped: lms unload timed out"
    except Exception as exc:
        return "skipped: {}".format(exc)

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        return "failed: {}".format(detail[0] if detail else "exit {}".format(proc.returncode))
    if verbose:
        eprint("  unloaded all models")
    return "ok"


def build_messages(prompt_spec, prompts_dir):
    """Assemble the messages array, attaching an image when the prompt names one.

    Raises IOError if the image is missing so the caller can record it as a run
    failure rather than crashing the sweep partway through.
    """
    messages = []
    if prompt_spec.get("system"):
        messages.append({"role": "system", "content": prompt_spec["system"]})

    image_name = prompt_spec.get("image")
    if not image_name:
        messages.append({"role": "user", "content": prompt_spec["prompt"]})
        return messages

    path = os.path.join(prompts_dir, image_name)
    with open(path, "rb") as handle:
        encoded = base64.b64encode(handle.read()).decode("ascii")
    mime = "image/png" if path.lower().endswith(".png") else "image/jpeg"
    messages.append({
        "role": "user",
        "content": [
            {"type": "text", "text": prompt_spec["prompt"]},
            {"type": "image_url",
             "image_url": {"url": "data:{};base64,{}".format(mime, encoded)}},
        ],
    })
    return messages


def run_once(base_url, model, prompt_spec, args, include_usage=True):
    """Single streamed completion. Returns a result dict; never raises."""
    try:
        messages = build_messages(prompt_spec, args.prompts_dir)
    except (OSError, ValueError) as exc:
        return {
            "model": model, "prompt_id": prompt_spec["id"],
            "category": prompt_spec.get("category", "uncategorised"),
            "ok": False, "error": "could not attach image: {}".format(exc),
            "ttft_s": None, "gen_tps": None, "e2e_tps": None, "total_s": None,
            "tokens": None, "token_source": None, "chars": 0, "malformed_chunks": 0,
            "has_image": True,
        }

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": args.max_tokens or prompt_spec.get("max_tokens", 512),
        "temperature": args.temperature,
        "stream": True,
    }
    if include_usage:
        payload["stream_options"] = {"include_usage": True}
    if args.seed is not None:
        payload["seed"] = args.seed

    result = {
        "model": model,
        "prompt_id": prompt_spec["id"],
        "category": prompt_spec.get("category", "uncategorised"),
        "ok": False,
        "error": None,
        "ttft_s": None,
        "gen_tps": None,
        "e2e_tps": None,
        "total_s": None,
        "tokens": None,
        "token_source": None,
        "chars": 0,
        "malformed_chunks": 0,
        "has_image": bool(prompt_spec.get("image")),
    }

    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )

    start = time.perf_counter()
    first_token_at = None
    last_token_at = None
    chunk_tokens = 0
    usage_tokens = None
    chars = 0
    malformed = 0

    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8", "replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                body = line[5:].strip()
                if body == "[DONE]":
                    break
                try:
                    obj = json.loads(body)
                except ValueError:
                    malformed += 1
                    continue

                usage = obj.get("usage")
                if isinstance(usage, dict):
                    reported = usage.get("completion_tokens")
                    if isinstance(reported, int) and reported > 0:
                        usage_tokens = reported

                choices = obj.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                piece = delta.get("content") or delta.get("reasoning_content") or ""
                if not piece:
                    continue
                now = time.perf_counter()
                if first_token_at is None:
                    first_token_at = now
                last_token_at = now
                chunk_tokens += 1
                chars += len(piece)

    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        # Older servers reject stream_options. Retry once without it rather than
        # reporting a capability gap as a model failure.
        if include_usage and exc.code in (400, 422) and "stream_options" in detail:
            return run_once(base_url, model, prompt_spec, args, include_usage=False)
        result["error"] = "HTTP {} {}".format(exc.code, detail.strip() or exc.reason)
        return result
    except urllib.error.URLError as exc:
        result["error"] = "connection failed: {}".format(exc.reason)
        return result
    except TimeoutError:
        result["error"] = "timed out after {}s".format(args.timeout)
        return result
    except Exception as exc:
        result["error"] = "{}: {}".format(type(exc).__name__, exc)
        return result

    end = time.perf_counter()
    result["total_s"] = end - start
    result["chars"] = chars
    result["malformed_chunks"] = malformed

    if first_token_at is None:
        # Server answered, model produced nothing. A real outcome worth recording,
        # not a zero-token row to be averaged into a throughput figure.
        result["error"] = "empty completion (no content returned)"
        return result

    if usage_tokens is not None:
        tokens, source = usage_tokens, "usage"
    else:
        tokens, source = chunk_tokens, "chunks"

    result["tokens"] = tokens
    result["token_source"] = source
    result["ttft_s"] = first_token_at - start

    gen_window = (last_token_at - first_token_at) if last_token_at else 0.0
    if gen_window > 0 and tokens > 0:
        result["gen_tps"] = tokens / gen_window
    if result["total_s"] > 0 and tokens > 0:
        result["e2e_tps"] = tokens / result["total_s"]

    result["ok"] = True
    return result


# ---------------------------------------------------------------- reporting

def summarise(model, cold, warm_runs):
    good = [r for r in warm_runs if r["ok"]]
    return {
        "model": model,
        "warm_attempts": len(warm_runs),
        "warm_ok": len(good),
        "failures": len(warm_runs) - len(good),
        "gen_tps_median": median_or_none([r["gen_tps"] for r in good]),
        "gen_tps_min": min([r["gen_tps"] for r in good if r["gen_tps"] is not None], default=None),
        "gen_tps_max": max([r["gen_tps"] for r in good if r["gen_tps"] is not None], default=None),
        "e2e_tps_median": median_or_none([r["e2e_tps"] for r in good]),
        "ttft_median": median_or_none([r["ttft_s"] for r in good]),
        "cold_ttft": cold["ttft_s"] if cold and cold.get("ok") else None,
        "cold_error": None if (cold and cold.get("ok")) else (cold or {}).get("error"),
        "token_sources": sorted({r["token_source"] for r in good if r["token_source"]}),
    }


def print_markdown(summaries, per_prompt, ttft_by_cat, args):
    print()
    print("### Throughput by model")
    print()
    print("| Model | Generation tok/s (median) | Range | End-to-end tok/s | Warm TTFT (s) | Cold TTFT (s) | Runs ok |")
    print("|---|---|---|---|---|---|---|")
    for s in summaries:
        rng = "-"
        if s["gen_tps_min"] is not None and s["gen_tps_max"] is not None:
            rng = "{}-{}".format(fmt(s["gen_tps_min"]), fmt(s["gen_tps_max"]))
        print("| `{}` | {} | {} | {} | {} | {} | {}/{} |".format(
            s["model"], fmt(s["gen_tps_median"]), rng, fmt(s["e2e_tps_median"]),
            fmt(s["ttft_median"], 2), fmt(s["cold_ttft"], 2),
            s["warm_ok"], s["warm_attempts"],
        ))

    print()
    print("### Generation tok/s by prompt category")
    print()
    categories = sorted({c for pairs in per_prompt.values() for c in pairs})
    header = "| Model | " + " | ".join(categories) + " |"
    print(header)
    print("|---" * (len(categories) + 1) + "|")
    for s in summaries:
        cells = []
        for cat in categories:
            cells.append(fmt(median_or_none(per_prompt.get(s["model"], {}).get(cat, []))))
        print("| `{}` | {} |".format(s["model"], " | ".join(cells)))

    print()
    print("### Time to first token by prompt category (seconds)")
    print()
    print(header)
    print("|---" * (len(categories) + 1) + "|")
    for s in summaries:
        cells = []
        for cat in categories:
            cells.append(fmt(median_or_none(ttft_by_cat.get(s["model"], {}).get(cat, [])), 2))
        print("| `{}` | {} |".format(s["model"], " | ".join(cells)))

    print()
    weak = [s["model"] for s in summaries if "chunks" in s["token_sources"]]
    if weak:
        print("> Token counts for {} came from streamed chunk counts, not a server usage "
              "block. Treat those rows as approximate.".format(", ".join("`{}`".format(m) for m in weak)))
    stalled = [s for s in summaries if s["warm_ok"] == 0]
    for s in stalled:
        print("> `{}` produced no usable runs. See the failures section.".format(s["model"]))
    print()
    print("_{} warm repeats per prompt, temperature {}, seed {}, {} timeout._".format(
        args.repeats, args.temperature,
        args.seed if args.seed is not None else "unset", args.timeout))


# ---------------------------------------------------------------- main

def main():
    parser = argparse.ArgumentParser(description="Benchmark an OpenAI-compatible local model server.")
    parser.add_argument("--base-url", default=DEFAULT_BASE, help="default: %(default)s")
    parser.add_argument("--models", default="all", help="comma-separated model ids, or 'all'")
    parser.add_argument("--prompts", default=DEFAULT_PROMPTS, help="path to prompts.json")
    parser.add_argument("--repeats", type=int, default=3, help="warm repeats per prompt (default: %(default)s)")
    parser.add_argument("--timeout", type=int, default=300, help="per-request seconds (default: %(default)s)")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=0, help="pass --seed -1 to omit the field entirely")
    parser.add_argument("--max-tokens", type=int, default=None, help="override every prompt's ceiling")
    parser.add_argument("--unload-between", action="store_true",
                        help="run 'lms unload --all' before each model, so cold TTFT is real")
    parser.add_argument("--out", default="results.json", help="raw results (default: %(default)s)")
    parser.add_argument("--list", action="store_true", help="list models and exit")
    args = parser.parse_args()

    if args.seed is not None and args.seed < 0:
        args.seed = None

    args.prompts_dir = os.path.dirname(os.path.abspath(args.prompts))

    if args.list:
        for model_id in get_models(args.base_url, args.timeout):
            print(model_id)
        return 0

    if args.repeats < 1:
        raise SystemExit("--repeats must be at least 1")

    try:
        with open(args.prompts, "r", encoding="utf-8") as handle:
            prompt_doc = json.load(handle)
    except (OSError, ValueError) as exc:
        raise SystemExit("Could not read prompt set {}: {}".format(args.prompts, exc))

    args.prompts_dir = os.path.dirname(os.path.abspath(args.prompts))
    prompts = prompt_doc.get("prompts") or []
    if not prompts:
        raise SystemExit("Prompt set {} contains no prompts.".format(args.prompts))
    for spec in prompts:
        if not spec.get("id") or not spec.get("prompt"):
            raise SystemExit("Every prompt needs an id and a prompt field.")

    if args.models.strip().lower() == "all":
        models = get_models(args.base_url, args.timeout)
    else:
        models = [m.strip() for m in args.models.split(",") if m.strip()]
    if not models:
        raise SystemExit("No models selected.")

    eprint("Benchmarking {} model(s) x {} prompt(s) x {} repeat(s)".format(
        len(models), len(prompts), args.repeats))

    raw = {
        "meta": {
            "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "base_url": args.base_url,
            "prompt_set": prompt_doc.get("set_name", os.path.basename(args.prompts)),
            "repeats": args.repeats,
            "temperature": args.temperature,
            "seed": args.seed,
            "timeout_s": args.timeout,
            "unload_between": args.unload_between,
        },
        "models": {},
    }

    summaries = []
    per_prompt = {}
    ttft_by_cat = {}
    failures = []

    for model in models:
        eprint("\n{}".format(model))
        unload_note = None
        if args.unload_between:
            unload_note = unload_all()
            if unload_note != "ok":
                eprint("  unload: {}".format(unload_note))

        eprint("  cold start ...")
        cold = run_once(args.base_url, model, prompts[0], args)
        if not cold["ok"]:
            eprint("  cold run failed: {}".format(sanitize_error(cold["error"], 90)))
            failures.append(cold)

        warm_runs = []
        for rep in range(args.repeats):
            for spec in prompts:
                res = run_once(args.base_url, model, spec, args)
                warm_runs.append(res)
                if res["ok"]:
                    eprint("  [{}/{}] {:<10} {} tok/s gen, ttft {}s".format(
                        rep + 1, args.repeats, spec["id"],
                        fmt(res["gen_tps"]), fmt(res["ttft_s"], 2)))
                else:
                    eprint("  [{}/{}] {:<10} FAILED: {}".format(
                        rep + 1, args.repeats, spec["id"], sanitize_error(res["error"], 90)))
                    failures.append(res)

        raw["models"][model] = {
            "unload": unload_note,
            "cold": cold,
            "warm": warm_runs,
        }

        by_category = {}
        ttft_cat = {}
        for res in warm_runs:
            if res["ok"] and res["gen_tps"] is not None:
                by_category.setdefault(res["category"], []).append(res["gen_tps"])
            if res["ok"] and res["ttft_s"] is not None:
                ttft_cat.setdefault(res["category"], []).append(res["ttft_s"])
        per_prompt[model] = by_category
        ttft_by_cat[model] = ttft_cat
        summaries.append(summarise(model, cold, warm_runs))

    try:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(raw, handle, indent=2)
        eprint("\nRaw results written to {}".format(args.out))
    except OSError as exc:
        eprint("\nCould not write {}: {}".format(args.out, exc))

    print_markdown(summaries, per_prompt, ttft_by_cat, args)

    if failures:
        print()
        print("### Failures")
        print()
        print("| Model | Reason | Prompts affected |")
        print("|---|---|---|")
        grouped = {}
        for res in failures:
            key = (res["model"], sanitize_error(res["error"]))
            grouped.setdefault(key, set()).add(res["prompt_id"])
        for (model, reason), prompt_ids in grouped.items():
            print("| `{}` | {} | {} |".format(
                model, reason, ", ".join("`{}`".format(p) for p in sorted(prompt_ids))))

    return 0


if __name__ == "__main__":
    sys.exit(main())
