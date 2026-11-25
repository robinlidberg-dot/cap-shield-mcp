# CAP-Shield MCP server

Context selection and compression for AI agents — with the recall
measured, not claimed.

One file. No dependencies. No SDK required.

## Why

More context makes agents worse. ETH Zurich found context files LOWER
task success versus giving the agent no repository context at all, while
raising inference cost by over 20 %. Around two thirds of production
agent failures trace to context problems, not to the model being
incapable.

So the question is not how much you cut. It is whether what you kept was enough — and that is measured here, on a benchmark we did not choose: LongMemEval-S, 500 questions. Recall@10 of 97.1 % against a lexical baseline of 51.9 % (measured 2026-09-28 — figures update as retrieval does; fetch `.well-known/cap-shield.json` for the current number rather than trusting this file).

Recall@10 is the strict measure: a question counts only when ALL gold
sessions were found. Finding half the answer means the agent answers
confidently on half a basis.

**Four of the fifteen tools need no account**, and `start_sandbox` lets an agent try memory for 24 hours before anyone signs up.

## Install

```bash
curl -O https://cap-shield-robin.fly.dev/cap_mcp.py
```

```json
{
  "mcpServers": {
    "cap-shield": {
      "command": "python",
      "args": ["/absolute/path/to/cap_mcp.py"]
    }
  }
}
```

Python 3.9+. Nothing else.

The optional [SKILL.md](SKILL.md) tells an agent *when* to use these
tools — and when not to.

## Install as a Claude plugin (server and skill together)

This repository is also a Claude plugin: the remote MCP server plus the
skill that tells Claude when to use each tool, and when not to.

In Claude Code:

```
/plugin install cap-shield --marketplace robinlidberg-dot/cap-shield-mcp
```

The plugin connects to `https://cap-shield-robin.fly.dev/mcp`.
`measure_traffic`, `list_packages`, `start_sandbox`, `verify_pass` and
`get_account` work without a key; the other tools need one or a
`sandbox_key` from `start_sandbox` (see below). Privacy policy:
https://cap-shield-robin.fly.dev/privacy

## Use it from Claude (Claude.ai, Claude Desktop, or Cowork) — no download

The server is also reachable directly over HTTP, so a hosted Claude
client can connect to it without installing anything locally.

In Claude: **Settings → Connectors → Add custom connector**, and enter
the server URL:

```
https://cap-shield-robin.fly.dev/mcp
```

Under **Authentication**, choose **No sign-in** — this server is
authenticated with an API key, not OAuth (OAuth support is not built
yet; see Status below). Claude will warn that anyone with the URL can
use the connector without sign-in — that warning is accurate, and is
exactly why the free tools below need no key at all, while the rest
do.

**`measure_traffic`, `list_packages`, `start_sandbox` and `verify_pass`
work immediately**, with no header and no account — nothing more to
configure. To try memory without an account, call `start_sandbox` and
pass the returned `sandbox_key` to the memory tools; everything in a
sandbox is deleted after 24 hours.

**To use the account tools** (`remember`, `remember_batch`,
`list_memories`, `update_memory`, `forget`, `assemble_context`,
`assemble_escalation_context`, `pack_batch`, `unpack_batch`,
`issue_pass`): get a key first
(`get_account`, or the console at
https://cap-shield-console.lovable.app), then add it under **Request
headers** in the same connector dialog:

| Header | Value |
|---|---|
| `Authorization` | `Bearer YOUR_KEY_HERE` |

The `Bearer ` prefix is required — a bare key without it is rejected
with `NYCKEL_KRAVS`. This is a standard bearer-token header, so the same
two fields should work in any MCP client that lets you add a custom
request header to a remote server, not just Claude — that is just the
one this has actually been tested against.

## Tools

### `measure_traffic` · *no account*

Measure how much of your own agent traffic could be saved. NO ACCOUNT OR KEY NEEDED — use this first. Returns byte savings over the wire and, if a query is given, token savings from selective context retrieval. Nothing is stored: the text is compressed in memory and discarded. Rate limited to 20 calls per hour per IP.

### `list_packages` · *no account*

List the available dictionaries with their MEASURED compression, including the ones that perform badly. Each entry says whether it works one message at a time or only batched, and how many messages came out LARGER. No key needed.

### `remember` · *requires a key*

Store a memory entry for later retrieval. REQUIRES A KEY (or a sandbox_key from start_sandbox). This does not call any language model — it stores text in an isolated per-tenant archive. Use assemble_context to get relevant entries back.

### `remember_batch` · *requires a key*

Store up to 100 memory entries in ONE call. REQUIRES A KEY (or a sandbox_key from start_sandbox). Counts as one call against the rate limit and one packet per entry against the monthly quota, so prefer it over many remember calls. All or nothing: duplicate ids or a blocked entry reject the whole batch before anything is stored. Does not call any language model.

### `list_memories` · *requires a key*

List what is stored, newest first, with a short preview of each entry and its item_id. REQUIRES A KEY (or a sandbox_key from start_sandbox). Omit namespace to list your namespaces instead. Use the item_id with update_memory or forget. Read-only.

### `update_memory` · *requires a key*

Replace the text of an EXISTING memory entry. REQUIRES A KEY (or a sandbox_key from start_sandbox). Fails with MEMORY_NOT_FOUND if the item_id does not exist (use remember to create). The previous text is kept in the entry's version history; created date and tags are kept.

### `forget` · *requires a key*

Permanently delete up to 100 memory entries, including their version history. REQUIRES A KEY (or a sandbox_key from start_sandbox). Cannot be undone. Unknown ids are reported in not_found, not treated as an error.

### `assemble_context` · *requires a key*

Retrieve the memory entries that answer a question, within a token budget. REQUIRES A KEY (or a sandbox_key from start_sandbox). Send the returned 'context' to your language model INSTEAD of the whole history. This does not call a model itself — it selects what to send. The budget is a ceiling, not a target: selection stops where relevance runs out, often well below it. The response says how many entries were left behind and why. If the response has a 'budget_warning', the best match did not fit: call again with its suggested_token_budget.

### `assemble_escalation_context` · *requires a key*

Retrieve a WIDE context for a question your model could not answer from assemble_context. REQUIRES A KEY (or a sandbox_key from start_sandbox). Use it when assemble_context returned escalate_recommended=true, or when the answer depends on dates, counts or several sessions. This does not call a model itself. Returns 'context' (up to token_budget, default 150 000 tokens: lower it if your model's window is smaller), where each stored entry starts with a header '--- Session YYYY/MM/DD (Ddd) HH:MM ---' giving when it was stored, and 'utelamnat_kontext': lower-ranked entries that were left out, in the same format. Read those only if the answer is still missing from 'context'. Python users can pass the whole response to cap_escalate_helper.eskalera_om_behovs_v6().

### `start_sandbox` · *no account*

Try memory WITHOUT an account. Returns a temporary sandbox_key; pass it as the sandbox_key argument to remember, remember_batch, assemble_context, list_memories, update_memory or forget. Everything is deleted after 24 hours. Limits: 200 entries, 1 MB of text. No email needed. Do not store real personal data in a sandbox.

### `get_account`

Get an account and an API key. Requires an email address. The key is returned ONCE and cannot be shown again — store it immediately. Beta quotas are low by design; they are hard stops, never overage billing.

### `issue_pass` · *requires a key*

**Agent identity / agent passport.** Issue a short-lived (15 minute) signed credential (a JWT) stating who the caller acts for. REQUIRES A KEY. Anyone can verify it independently against /.well-known/jwks.json — without calling CAP-Shield again. 'acts_for' and 'scope' are NOT validated against reality: the pass only attests that the key holder claimed this, at this time, and that the claim is recorded in the audit chain. This is identity and claimed authorization, not a payment or access-control mechanism.

### `verify_pass` · *no account*

Check a CAP-Shield pass you were given: signature against CAP-Shield's published keys, issuer, expiry, and, if you give them, audience and required scope. No key needed. Returns valid true/false with the reason and the claims. It cannot tell you whether acts_for is TRUE, only that a key holder claimed it.

### `pack_batch` · *requires a key*

Pack several messages into ONE compressed packet instead of packing them one at a time. REQUIRES A KEY. Worth it for many small/medium messages (the per-message header cost is paid once per batch, and zstd shares context across them) — for a single message this has no advantage. Returns packet_b64 (hand it to unpack_batch to get the messages back) plus the measured byte savings versus packing each message separately. SECURITY: only batch messages that already share the SAME trust boundary (same tenant/agent — nothing attacker-influenced mixed in with a secret). Batched messages share one compression context, which can leak size-based information between them (a CRIME/BREACH-style side channel). There is no padding mitigation on this endpoint today, so trust-boundary separation is the only protection — don't rely on padding.

### `unpack_batch` · *requires a key*

Unpack a batch packet made by pack_batch (or by the /api/v1/pack-batch endpoint) back into the exact original list of messages, in order. REQUIRES A KEY. Not for a packet made by the single-message pack endpoint — that is a different format and this will reject it.

The descriptions above are copied verbatim from the server. If they ever
differ from what `tools/list` returns, the server is right and this file
is stale.

## Answers from memory, with your own model

Retrieval and compression above never call a model. For questions the
narrow selection cannot answer — dates ("last Saturday", "how many days
ago"), counts and sums across sessions, a detail that ranked low —
`assemble_escalation_context` (REST: `POST /api/v1/memory/assemble-escalation`)
returns a much wider context with a date header on every session, plus the
sessions that were left out.

`cap_escalate_helper.py` (with `cap_fokuslasare.py`) answers from it with
**your own** model key, from your machine. CAP-Shield never spends your
tokens and never sees your key. Both files are in this repository and in
the `cap-shield` package on PyPI (0.6.0 and later). Standard library only;
`openai` or `anthropic` is imported when it is used.

```bash
pip install cap-shield openai     # or: anthropic
export OPENAI_API_KEY=...
```

```python
from cap_shield import CapShield
from cap_escalate_helper import eskalera_om_behovs_v6

cap = CapShield(api_key="cap_live_...")
fraga = "Which bike did I fix last weekend?"
ctx = cap.escalation_context("support", fraga)
svar = eskalera_om_behovs_v6(ctx, fraga, modell="openai",      # or "anthropic"
                             modell_namn="gpt-6-luna",
                             dagens_datum="2026/11/16")       # when the question is asked
print(svar["svar"])
```

Over MCP, call `assemble_escalation_context` and let your own model read
the result.

### How often the answer is right

Answers produced 2026-11-16 with `gpt-6-luna`; official judging run
2026-11-22. The full method, the
answer to every question type, and each answer that was reviewed by hand
are published under `memory_layer.answer_benchmark` in
https://cap-shield-robin.fly.dev/.well-known/cap-shield.json — fetch the
current figures there rather than trusting this file.

Judged exactly as in the LongMemEval paper (GPT-4o as judge, the
official judge prompts), LongMemEval-S, 500 questions, `gpt-6-luna`
answering: **481 of 500 correct (96.2 %)**. Our own automatic judging
of the same answers gives 96.6 % (previous helper version 88.0 %), and
98.6 % after manual review of ten answers, each listed in the
measurement file.

On 200 LoCoMo questions held out and never read during development,
v6.2 answered **170** correctly, against 148 for v6.1. The gain is on
questions about a person the conversation says nothing about: v6.2
checks which speaker a fact belongs to before answering.

Three caveats, which belong next to those figures wherever they are
quoted:

- **Developed against the same 500 LongMemEval questions.** The rules in
  the helper were written while studying misses on that set; the LoCoMo
  figures are from questions that were never read.
- **The answer model is our own choice**, so the judging is comparable
  with other published LongMemEval scores but the setup is not identical.
- **They depend on the answer model.**

Six of the ten reviewed answers meet the official preference rubric but
were rejected by the judge model. In four, the benchmark's gold answer
contradicts the conversation history; we keep the answer the history
supports and list the case, rather than teach the model to agree with a
wrong key.

### Energy and time

A model spends energy and time on every token it reads. Measured
2026-11-17 with the GPU's own energy counter (NVIDIA GeForce RTX 4070,
`llama3.2:1b`, idle power subtracted), 50 LongMemEval-S
questions, against the whole history (median 104 652 tokens):
**95 % less energy and 94.4 % less time** for the model to
read the context, with the selection at budget 32 000 and every
session holding the answer included in 90 % of questions.

| The model reads | Tokens (median) | Less energy | Less time | All evidence included |
|---|---:|---:|---:|---:|
| Selection, budget 32 000 | 18 248 | 95 % | 94.4 % | 90 % |
| Selection, budget 16 000 | 12 672 | 97.2 % | 96.5 % | 80 % |
| Selection, budget 8 000 | 6 158 | 98.7 % | 97.9 % | 50 % |
| Selection, budget 4 000 | 3 094 | 99.3 % | 98.5 % | 22 % |
| Selection, budget 2 000 | 1 080 | 99.7 % | 98.8 % | 14 %, 9 empty |
| Escalation context | 75 066 | 39.3 % | 37.4 % | 98 % |

Per reading of the context, on one GPU with a small model; larger models
have not been measured. A shorter history leaves less to remove. The
escalation helper reads its context at least twice per question. If the
budget is too small for the best match, the response says so in
`budget_warning` and suggests a budget that fits it.

## What the numbers mean

Compression saves **bytes over the wire**. Selection saves **tokens in
the context**. Two different mechanisms — adding them together produces
a number that means nothing.

Compressed packets are decompressed before a model sees them, so this
does **not** reduce inference cost. Saying otherwise is the easiest way
to be wrong about this project.

Every figure is published live, including what has *not* been measured
and which packages perform badly:

https://cap-shield-robin.fly.dev/.well-known/cap-shield.json

Fetch that rather than trusting this file. It goes stale; the document
does not.

## Measuring without MCP

```bash
pip install cap-shield
```

```python
from cap_shield import measure, print_measurement
print_measurement(measure(texts=[...], query="..."))
```

No account, nothing stored. The response includes the degraded share —
how many of your messages came out **larger**.

## Batching has a security condition

Batching compresses several messages in the same context, which opens a
CRIME/BREACH-style side channel: someone who can place chosen text in the
same batch as a secret, and observe the batch size, learns something
about the secret.

Only batch messages that already share a trust boundary. Optional padding
closes the leak for under two bytes a message, and it is **off by
default** — we say so rather than let you assume otherwise.

Individual packing does not have this problem at all.

## Portability

Dictionary versions are never deleted, and the guarantee does not rest on
us still being here: the archive export carries the dictionary binaries,
and a standalone unpacker runs with no gateway, no network and no other
part of the system.

https://cap-shield-robin.fly.dev/cap_unpack.py

It is served without a token, because whoever needs it most is whoever no
longer has an account.

## Status

Beta. MCP server 0.7.6, Python package 0.6.2.

Docs: https://cap-shield-robin.fly.dev/docs/quickstart
Console: https://cap-shield-console.lovable.app

## Licence

MIT — see [LICENSE](LICENSE).
