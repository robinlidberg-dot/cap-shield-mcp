---
name: cap-shield
description: Measure and reduce what an agent sends into its context. Use when an agent's context is large, when retrieval quality matters, when the user asks about token cost or context bloat, or when agent answers are wrong in ways that look like missing information rather than reasoning failure. Also use to measure compression on structured machine-to-machine traffic before sending it over the wire.
---

# CAP-Shield

Selects what goes into an agent's context, and compresses what goes over
the wire. The difference from other context tools is that the recall is
measured, not asserted.

## When this matters

Reach for this when any of these are true:

- An agent gets worse as the conversation grows, and the failures look
  like missing information rather than bad reasoning
- Context is assembled by "include everything relevant, just in case"
- Someone asks what a large context is costing
- Structured machine-to-machine traffic is being sent uncompressed

**The counter-intuitive part:** more context makes agents worse. ETH
Zurich found context files LOWER task success versus giving the agent no
repository context at all, while raising inference cost by over 20 %.
Around two thirds of production agent failures trace to context problems,
not to the model being incapable.

So cutting context is not only a cost optimisation. It is a correctness
fix, and that is the reason to do it.

## Do not use this for

- Short conversations that fit comfortably in the budget. Below roughly
  2 000 tokens there is nothing to leave out, and the saving would be
  zero for reasons that have nothing to do with how well selection works.
- Free prose where every sentence is load-bearing.
- Compressing single short messages. Below roughly 100 bytes, the packet
  header and authenticated encryption cost more than compression saves.
  Batch instead.

Say so plainly when one of these applies rather than reporting a small
number as if it were a result.

## Measure first, always

Never state what CAP-Shield will save. Measure it on the actual traffic
and report what comes back — including the parts that look bad.

```bash
pip install cap-shield
```

```python
from cap_shield import measure, print_measurement

print_measurement(measure(
    texts=[...the actual messages...],
    query="what the agent would search for",
))
```

No account, no key, nothing stored. The text is compressed in memory, the
numbers are computed, and everything is discarded.

Quotas: 200 messages, 512 kB, 20 measurements per hour per IP.

### Reading the result

The response has four parts, and **three of them can be bad news**:

- `individual.saving_pct` — one message at a time. Can be NEGATIVE.
- `individual.degraded` — how many messages came out LARGER. Report this
  number every time, including when it is zero.
- `batched.saving_pct` — the same messages packed together.
- `token_saving` — a different mechanism entirely. `measured: false`
  means there was not enough content, not that it failed.

**A real result:** 30 short JSON messages gave −10.5 % individually with
all 30 degraded, and 87.9 % batched. Reporting only the second number
would be dishonest; reporting only the first would be useless. Report
both, weak number first.

### Cumulative

```bash
python -m cap_gain
```

Shows what has been saved across all measurements, with the degraded
count. Collection is silent and local; nothing is sent anywhere.
`CAP_SHIELD_INGEN_RAKNARE=1` turns it off.

## The MCP server

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

The `env` block is only needed for the two tools that use memory.

Or take the server as a single file, if a package is unwelcome:

```bash
curl -O https://cap-shield-robin.fly.dev/cap_mcp.py
```

The server itself imports nothing outside the standard library.

Five tools:

| Tool | Purpose | Account |
|---|---|---|
| `measure_traffic` | Measure saving on your own traffic | No |
| `list_packages` | Domain packages with measured figures | No |
| `remember` | Store a memory entry | Yes |
| `assemble_context` | Retrieve the relevant entries, not the whole history | Yes |
| `get_account` | Obtain a key | No |

`assemble_context` calls no model. It selects and returns; the caller
decides what to do with the result.

## Choosing a package

A package is a dictionary trained on a corpus, not a name. Seven exist.
Do not guess which fits — `list_packages` returns the measured figures,
and `measure_traffic` settles it against the actual traffic.

Two things that decide the outcome more than package choice:

**Message size.** The packet header is 5 bytes and authenticated
encryption adds 25. On a 62-byte message that is half the packet.
Batched, it is spread across the whole batch.

**Whether batching is possible.** Some packages only work batched, and
that is stated in the catalogue rather than hidden. If the agent cannot
batch, use the individual figure and say so.

## Batching has a security condition

Batching compresses several messages in the same context, which opens a
CRIME/BREACH-style side channel: someone who can place chosen text in the
same batch as a secret, and observe the batch size, learns something
about the secret.

**Only batch messages that already share a trust boundary.** One tenant's
own traffic is safe. Traffic where a second party controls part of the
content is not.

Optional padding (`padding=PADDING_STANDARD`) rounds to a 64-byte step
and closes it, for under two bytes a message. **It is off by default** —
say so rather than let anyone assume it is on.

Individual packing does not have this problem at all.

## Reporting results

Follow the same rules the service follows about itself:

- **Never state a figure without saying what it was measured on.** The
  published numbers come from open corpora and do not predict anyone
  else's outcome.
- **Always report the degraded count**, including zero. A field that
  appears only with bad news teaches the reader that its absence means
  something.
- **Keep bytes and tokens apart.** Compression saves bytes over the wire.
  Selection saves tokens in the context. They are different mechanisms
  and adding them together produces a number that means nothing.
- **Compressed packets are decompressed before a model sees them.**
  Compression does not reduce inference cost. Saying otherwise is the
  single easiest way to be wrong about this product.
- **Say when something has not been measured.** `measured: false` is an
  answer, not a failure.

## Memory is versioned, and updates are stored as deltas

An entry can be updated without storing it again in full. Every fifth
version is complete; the ones between are stored as a delta against the
previous version. A SHA-256 of the original is kept per version and
checked on read, so the chain is lossless, and no version depends on
more than four others.

This matters because agent memory is mostly small edits to text that
already exists. Storing each edit in full is what makes memory expensive
to keep.

Each entry also picks its own compression strategy by size — and if
compression does not pay off, the entry is stored RAW and the response
says so. Same rule as the degraded share on the wire: report it rather
than hide it.

## What the response tells you — use it

A saving you cannot audit is a saving the customer has to take on trust.
The response says more than the total, and the extra fields are what make
the number checkable:

- `method` on every hit — vector or lexical, so you can see WHICH
  mechanism found that entry
- `baseline_tokens` — what the whole history would have cost, in the same
  format. Without it the saving cannot be computed, only claimed
- `candidates_before_autocut` and `autocut_removed` — what relevance
  scoring dropped
- `deduplicated` — near-identical entries collapsed rather than sent twice
- `skipped_too_big` and `item_ids`

**When reporting a saving, quote `baseline_tokens` alongside it.** A
percentage without its baseline is not a measurement.

## Everything else

`https://cap-shield-robin.fly.dev/.well-known/cap-shield.json` carries
the live figures, the known limitations, what has NOT been measured, and
the roadmap of what is planned but not built. Fetch it rather than
relying on anything written here — this file goes stale, that document
does not.
