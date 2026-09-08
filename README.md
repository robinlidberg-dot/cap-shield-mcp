# cap-shield MCP server

Context selection and compression for AI agents — with the recall
measured, not claimed.

One file. No dependencies. No SDK required.

## Why

More context makes agents worse. ETH Zurich found context files LOWER
task success versus giving the agent no repository context at all, while
raising inference cost by over 20 %. Around two thirds of production
agent failures trace to context problems, not to the model being
incapable.

So the question is not how much you cut. It is whether what you kept was
enough — and that is measured here, on a benchmark we did not choose:
LongMemEval-S, 500 questions. Recall@10 of 93.8 % against a lexical
baseline of 51.9 %.

Recall@10 is the strict measure: a question counts only when ALL gold
sessions were found. Finding half the answer means the agent answers
confidently on half a basis.

**Two of the six tools need no account.** Measure first, decide after.

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


## No install at all

The server is also reachable over HTTP:

```
https://cap-shield-robin.fly.dev/mcp
```

Add it as a remote MCP server in any client that supports them, or open it
in an MCP inspector. `measure_traffic` and `list_packages` work with no
account and no key — you can measure your own traffic in a browser without
installing anything.

`remember`, `assemble_context` and `issue_pass` need a key — send
`Authorization: Bearer cap_live_...` with the `/mcp` request and they
work exactly as they do over the SDK. Without a key they answer with
what to do instead, rather than a bare rejection.

## Dictionaries improve on your traffic — and only if they win

A customer's dictionary is trained on their own traffic, in their own
isolated store. A new version is adopted **only if it measures better on
held-out data neither version was trained on.** A retraining that does not
win is rejected and logged, and the old dictionary stays.

Old versions are never deleted, so packets compressed under any earlier
version still unpack.


## Tools

### `measure_traffic` · *no account*

Measure how much of your own agent traffic could be saved. NO ACCOUNT OR KEY NEEDED — use this first. Returns byte savings over the wire and, if a query is given, token savings from selective context retrieval. Nothing is stored: the text is compressed in memory and discarded. Rate limited to 20 calls per hour per IP.

### `list_packages` · *no account*

List the available dictionaries with their MEASURED compression, including the ones that perform badly. Each entry says whether it works one message at a time or only batched, and how many messages came out LARGER. No key needed.

### `remember` · *requires a key*

Store a memory entry for later retrieval. REQUIRES A KEY. This does not call any language model — it stores text in an isolated per-tenant archive. Takes an optional `ttl_days`: after that many days, `assemble_context` stops selecting the entry (it is not deleted, only no longer chosen). Use assemble_context to get relevant entries back.

### `assemble_context` · *requires a key*

Retrieve the memory entries that answer a question, within a token budget. REQUIRES A KEY. Send the returned 'context' to your language model INSTEAD of the whole history. This does not call a model itself — it selects what to send. The budget is a ceiling, not a target: selection stops where relevance runs out, often well below it. The response says how many entries were left behind and why.

### `get_account`

Get an account and an API key. Requires an email address. The key is returned ONCE and cannot be shown again — store it immediately. Beta quotas are low by design; they are hard stops, never overage billing.

### `issue_pass` · *requires a key*

Issue a short-lived (15 minute) signed credential (a JWT) stating who the caller acts for. REQUIRES A KEY. Anyone can verify it independently against `/.well-known/jwks.json` — without calling CAP-Shield again. `acts_for` and the optional `scope` are NOT validated against reality: the pass only attests that the key holder claimed this, at this time, and that the claim is recorded in the audit chain.

The descriptions above are copied verbatim from the server. If they ever
differ from what `tools/list` returns, the server is right and this file
is stale.

## Memory is versioned, and updates are stored as deltas

An entry can be updated without storing it again in full. Every fifth
version is complete; the ones between are stored as a delta against the
previous version, with a SHA-256 checked on read. Lossless, and no
version depends on more than four others.

Agent memory is mostly small edits to text that already exists. Storing
each edit in full is what makes it expensive to keep.

Entries also pick their own compression strategy by size — and if
compression does not pay off, the entry is stored **raw** and the
response says so.

## Memories can expire — without being deleted

`remember` takes an optional `ttl_days`. After that many days,
`assemble_context` stops selecting the entry — the entry itself is never
removed, it simply stops being a candidate. Omit the field and an entry
is eligible forever, exactly as before this existed. Use it for anything
whose truth decays with time, so a stale claim does not sit in context
competing with current information indefinitely.

## Multi-agent setups: one namespace per role

`remember` and `assemble_context` already take a `namespace` argument.
A manager agent coordinating sub-agents can give each role its own
namespace (`coder`, `finance`, `support`, ...) — the isolation a
multi-agent handoff needs, with no new tool. The manager writes into the
namespace that belongs to the recipient; each sub-agent only ever calls
`assemble_context` against its own. Same isolation mechanism already
used between tenants, one level down.

## The response is auditable

A saving you cannot check is a saving you have to take on trust. Every
hit carries `method` — vector or lexical — so you can see which mechanism
found it. Every assembly reports `baseline_tokens` (what the whole
history would have cost, in the same format), `candidates_before_autocut`,
`autocut_removed`, `deduplicated` and `skipped_too_big`.

Measuring the baseline in a different format once produced a 39-point
error. The formats are identical for that reason.

## What the numbers mean

Compression saves **bytes over the wire**. Selection saves **tokens in
the context**. Two different mechanisms — adding them together produces
a number that means nothing.

Compressed packets are decompressed before a model sees them, so this
does **not** reduce inference cost. Saying otherwise is the easiest way
to be wrong about this project.

If `individual.degraded` is high and batching is possible, batch — do
not report the weak number and stop there.

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
default** — we say so rather than let you assume otherwise. If you batch
across a trust boundary, turning padding on is not optional — it is the
difference between the name Shield meaning something here and not.

Individual packing does not have this problem at all.

## A pass someone else can verify without an account

`issue_pass` over MCP, or `POST /api/v1/pass` over REST, issues a
short-lived (15 minute) signed credential that a third party can check
independently against `/.well-known/jwks.json` — no CAP-Shield account
needed on their end. Same Bearer token as everything else here, no new
onboarding.

```bash
curl -X POST https://cap-shield-robin.fly.dev/api/v1/pass \
  -H "Authorization: Bearer cap_live_..." \
  -H "Content-Type: application/json" \
  --data '{"acts_for": "who the agent is acting for", "scope": {"can_read": "invoice_json", "max_budget_usd": 500}}'
```

It does **not** validate `acts_for` or `scope` against reality — it
attests only that the holder of the key claimed it, at that moment, with
a record in the hash-chained audit log. `scope` is optional and
freeform; omit it and the pass looks exactly as it did before the field
existed. No blockchain, no NFT, no wallet, no revocation list: a pass
without one has to be short-lived instead, since a revocation list is
one more service that would need to stay up for the pass to be checkable
at all.

**Request the pass right before the hand-off, not at the start of a
workflow that includes a wait.** A pass issued before a human-approval
gate can expire before it is ever shown to the recipient — there is no
refresh, only requesting a new one, which works at any time with the
same key.

Full detail, including what is deliberately not built yet, is under
`portable_pass` at:

https://cap-shield-robin.fly.dev/.well-known/cap-shield.json

## Portability

Dictionary versions are never deleted, and the guarantee does not rest on
us still being here: the archive export carries the dictionary binaries,
and a standalone unpacker runs with no gateway, no network and no other
part of the system.

https://cap-shield-robin.fly.dev/cap_unpack.py

It is served without a token, because whoever needs it most is whoever no
longer has an account.

What does **not** come with it: the memory store, vector selection,
autocut, package maturity, or the measurement apparatus. Those are the
service you subscribe to, not a file you export once and stop paying for.

## Status

Beta. Server version 0.1.0.

Docs: https://cap-shield-robin.fly.dev/docs/quickstart
Console: https://cap-shield-console.lovable.app

## Licence

MIT — see [LICENSE](LICENSE).