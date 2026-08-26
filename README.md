# cap-shield MCP server

Context selection and compression for AI agents — with the recall
measured, not claimed.

The server itself imports nothing outside the standard library. Install
it as a package, or take it as a single file — both work.

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

**Two of the five tools need no account.** Measure first, decide after.

## Install

```bash
pip install cap-shield
```

```json
{
  "mcpServers": {
    "cap-shield": {
      "command": "cap-shield-mcp",
      "env": {
        "CAP_SHIELD_API_KEY": "cap_live_..."
      }
    }
  }
}
```

Python 3.9+. The `env` block is only needed for `remember` and
`assemble_context` — leave it out and the two measuring tools still work.

Also published to the official MCP registry as
`io.github.robinlidberg-dot/cap-shield`.

Prefer a single file over a package?

```bash
curl -O https://cap-shield-robin.fly.dev/cap_mcp.py
```

Then the command is `python` and the argument is the path to the file.

The optional [SKILL.md](SKILL.md) tells an agent *when* to use these
tools — and when not to.

## Tools

### `measure_traffic` · *no account*

Measure how much of your own agent traffic could be saved. NO ACCOUNT OR KEY NEEDED — use this first. Returns byte savings over the wire and, if a query is given, token savings from selective context retrieval. Nothing is stored: the text is compressed in memory and discarded. Rate limited to 20 calls per hour per IP.

### `list_packages` · *no account*

List the available dictionaries with their MEASURED compression, including the ones that perform badly. Each entry says whether it works one message at a time or only batched, and how many messages came out LARGER. No key needed.

### `remember` · *requires a key*

Store a memory entry for later retrieval. REQUIRES A KEY. This does not call any language model — it stores text in an isolated per-tenant archive. Use assemble_context to get relevant entries back.

### `assemble_context` · *requires a key*

Retrieve the memory entries that answer a question, within a token budget. REQUIRES A KEY. Send the returned 'context' to your language model INSTEAD of the whole history. This does not call a model itself — it selects what to send. The budget is a ceiling, not a target: selection stops where relevance runs out, often well below it. The response says how many entries were left behind and why.

### `get_account`

Get an account and an API key. Requires an email address. The key is returned ONCE and cannot be shown again — store it immediately. Beta quotas are low by design; they are hard stops, never overage billing.

The descriptions above are copied verbatim from the server. If they ever
differ from what `tools/list` returns, the server is right and this file
is stale.

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

Beta. Server version 0.1.0.

Docs: https://cap-shield-robin.fly.dev/docs/quickstart
Console: https://cap-shield-console.lovable.app

## Licence

MIT — see [LICENSE](LICENSE).
