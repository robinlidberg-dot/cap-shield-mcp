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

## Dictionaries improve on the customer's own traffic

The shared dictionaries are trained on open corpora. A customer's own
dictionary is trained on their traffic, in their own isolated store, and
is never shared or merged into the curated ones.

**The part worth knowing:** a new version is adopted only if it measures
better on held-out data that neither version was trained on. A
retraining that does not win is rejected, the old dictionary stays, and
the rejection is logged with both figures.

That gate matters because a dictionary trained on too little or too
skewed traffic measures WORSE than none — the payload falls back to raw
and the header is still added.

Old versions are never deleted, so packets compressed under any earlier
version still unpack.

Retraining is manual by default (`POST /api/v1/catalog/mature`).
Automatic retraining exists but is off unless the customer has enabled
both `training` and `auto_mature`, and it consumes quota.

**Do not promise a figure for this.** What maturity gains depends on the
customer's traffic. The response reports `old_saving_pct`,
`new_saving_pct` and `improvement_pp` — quote those, not an estimate.

## Everything else

`https://cap-shield-robin.fly.dev/.well-known/cap-shield.json` carries
the live figures, the known limitations, what has NOT been measured, and
the roadmap of what is planned but not built. Fetch it rather than
relying on anything written here — this file goes stale, that document
does not.
