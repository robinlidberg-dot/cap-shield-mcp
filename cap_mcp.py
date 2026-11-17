"""
CAP-Shield — MCP-server
========================
Gör tjänsten upptäckbar för AI-agenter.

VARFÖR DENNA FINNS:
  /.well-known/cap-shield.json beskriver hela ytan maskinläsbart, men
  hjälper bara någon som REDAN känner till domänen. Ingen agent letar
  där spontant.

  Fyra register avgör synligheten i praktiken — mcp.so, smithery.ai,
  glama.ai och awesome-mcp-servers — och de listar MCP-servrar. Ett
  REST-API syns inte där, hur välbeskrivet det än är.

  Det här är alltså inte ett nytt API. Det är samma API med ett omslag
  som gör att en agent kan hitta det.

VARFÖR INGET MCP-SDK:
  Protokollet är JSON-RPC 2.0 över stdio. Ett SDK sparar femtio rader
  och lägger till ett beroende som måste hållas synkat med
  protokollversionen. För en server med fem verktyg är det fel affär.

KÖR:
    python cap_mcp.py

KONFIGURATION i en agents mcp-inställningar:
    {
      "mcpServers": {
        "cap-shield": {
          "command": "python",
          "args": ["/sökväg/till/cap_mcp.py"],
          "env": {"CAP_SHIELD_API_KEY": "cap_live_..."}
        }
      }
    }

Utan nyckel fungerar bara measure — och det är avsiktligt. En agent ska
kunna MÄTA innan någon registrerar sig.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

BAS = os.environ.get("CAP_SHIELD_URL", "https://cap-shield-robin.fly.dev")
PROTOKOLL = "2024-11-05"
VERSION = "0.7.0"  # 2026-11-15: + assemble_escalation_context (steg 101)


# ----------------------------------------------------------------------
# Verktygen
# ----------------------------------------------------------------------
# BESKRIVNINGARNA ÄR RIKTADE TILL EN MODELL, inte till en människa.
# En agent väljer verktyg på beskrivningen ensam — den ser ingen
# dokumentation, inget exempel och ingen landningssida. Därför står det
# rakt ut vad varje verktyg INTE gör, så att den inte väljer fel.
VERKTYG = [
    {
        "name": "measure_traffic",
        "description": (
            "Measure how much of your own agent traffic could be saved. "
            "NO ACCOUNT OR KEY NEEDED — use this first. Returns byte "
            "savings over the wire and, if a query is given, token savings "
            "from selective context retrieval. Nothing is stored: the text "
            "is compressed in memory and discarded. Rate limited to 20 "
            "calls per hour per IP."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "texts": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Your actual messages. 200 max.",
                },
                "query": {
                    "type": "string",
                    "description": (
                        "Optional. What your agent would search its memory "
                        "for. Given this, token savings are measured too."),
                },
                "dict_id": {
                    "type": "string", "default": "finance",
                    "description": (
                        "Which trained dictionary to measure against. Call "
                        "list_packages to see the options and their measured "
                        "figures."),
                },
            },
            "required": ["texts"],
        },
    },
    {
        "name": "list_packages",
        "description": (
            "List the available dictionaries with their MEASURED "
            "compression, including the ones that perform badly. Each entry "
            "says whether it works one message at a time or only batched, "
            "and how many messages came out LARGER. No key needed."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "remember",
        "description": (
            "Store a memory entry for later retrieval. REQUIRES A KEY. "
            "This does not call any language model — it stores text in an "
            "isolated per-tenant archive. Use assemble_context to get "
            "relevant entries back."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "namespace": {"type": "string",
                              "description": "Groups related memories."},
                "text": {"type": "string"},
                "item_id": {
                    "type": "string",
                    "description": (
                        "Optional. Same id overwrites the entry. Omit for "
                        "a generated one."),
                },
                "ttl_days": {
                    "type": "integer",
                    "description": (
                        "Optional. After this many days, assemble_context "
                        "stops selecting this entry. It is not deleted, "
                        "just no longer chosen. Omit to keep it eligible "
                        "indefinitely, as before this field existed."),
                },
            },
            "required": ["namespace", "text"],
        },
    },
    {
        "name": "assemble_context",
        "description": (
            "Retrieve the memory entries that answer a question, within a "
            "token budget. REQUIRES A KEY. Send the returned 'context' to "
            "your language model INSTEAD of the whole history. "
            "This does not call a model itself — it selects what to send. "
            "The budget is a ceiling, not a target: selection stops where "
            "relevance runs out, often well below it. The response says "
            "how many entries were left behind and why."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "namespace": {"type": "string"},
                "query": {"type": "string",
                          "description": "What you need context about."},
                "token_budget": {"type": "integer", "default": 2000},
                "reduce": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "Opt-in (FAS L): shorten the assembled context "
                        "with a small, local, task-agnostic model before "
                        "it is returned, to lower your own model's token "
                        "cost. Requires tenant consent for "
                        "context_reduction (set via /api/v1/gdpr/"
                        "consent) — otherwise the call is rejected with "
                        "SAMTYCKE_KRAVS instead of silently ignoring the "
                        "request. NOT query-aware: selection is driven "
                        "by what is least informative in general, not "
                        "by this query."
                    ),
                },
                "target_tokens": {
                    "type": "integer",
                    "description": (
                        "Only relevant together with reduce=true. How "
                        "many tokens the assembled context should be "
                        "shortened to. Omit for a default halving of "
                        "what was actually retrieved."
                    ),
                },
            },
            "required": ["namespace", "query"],
        },
    },
    {
        "name": "assemble_escalation_context",
        "description": (
            "Retrieve a WIDE context for a question your model could not "
            "answer from assemble_context. REQUIRES A KEY. Use it when "
            "assemble_context returned escalate_recommended=true, or when "
            "the answer depends on dates, counts or several sessions. "
            "This does not call a model itself. Returns 'context' (up to "
            "token_budget, default 150 000 tokens: lower it if your "
            "model's window is smaller), where each stored entry starts "
            "with a header '--- Session YYYY/MM/DD (Ddd) HH:MM ---' giving "
            "when it was stored, and 'utelamnat_kontext': lower-ranked "
            "entries that were left out, in the same format. Read those "
            "only if the answer is still missing from 'context'. Python "
            "users can pass the whole response to "
            "cap_escalate_helper.eskalera_om_behovs_v6()."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "namespace": {"type": "string"},
                "query": {"type": "string",
                          "description": "The question to answer."},
                "token_budget": {
                    "type": "integer", "default": 150000,
                    "description": (
                        "Ceiling for 'context'. The default is what the "
                        "method was measured with."),
                },
                "utelamnat_tokens": {
                    "type": "integer", "default": 60000,
                    "description": (
                        "Ceiling for 'utelamnat_kontext'. 0 = none."),
                },
            },
            "required": ["namespace", "query"],
        },
    },
    {
        "name": "get_account",
        "description": (
            "Get an account and an API key. Requires an email address. "
            "The key is returned ONCE and cannot be shown again — store it "
            "immediately. Beta quotas are low by design; they are hard "
            "stops, never overage billing."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "email": {"type": "string"},
                "traffic": {
                    "type": "string",
                    "description": "Optional. What your agent sends.",
                },
            },
            "required": ["email"],
        },
    },
    {
        "name": "issue_pass",
        "description": (
            "Issue a short-lived (15 minute) signed credential (a JWT) "
            "stating who the caller acts for. REQUIRES A KEY. Anyone can "
            "verify it independently against /.well-known/jwks.json — "
            "without calling CAP-Shield again. 'acts_for' and 'scope' are "
            "NOT validated against reality: the pass only attests that the "
            "key holder claimed this, at this time, and that the claim is "
            "recorded in the audit chain. This is identity and claimed "
            "authorization, not a payment or access-control mechanism."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "acts_for": {
                    "type": "string",
                    "description": "Who the agent claims to act for, e.g. 'acme-corp/procurement'.",
                },
                "audience": {
                    "type": "string",
                    "description": "Optional. Who the pass is shown to.",
                },
                "scope": {
                    "type": "object",
                    "description": (
                        "Optional, freeform, NOT validated. Example: "
                        '{"can_read": "invoice_json", "max_budget_usd": 500}.'),
                },
            },
            "required": ["acts_for"],
        },
    },
    {
        "name": "pack_batch",
        "description": (
            "Pack several messages into ONE compressed packet instead of "
            "packing them one at a time. REQUIRES A KEY. Worth it for many "
            "small/medium messages (the per-message header cost is paid "
            "once per batch, and zstd shares context across them) — for a "
            "single message this has no advantage. Returns packet_b64 "
            "(hand it to unpack_batch to get the messages back) plus the "
            "measured byte savings versus packing each message separately. "
            "SECURITY: only batch messages that already share the SAME "
            "trust boundary (same tenant/agent — nothing attacker-"
            "influenced mixed in with a secret). Batched messages share one "
            "compression context, which can leak size-based information "
            "between them (a CRIME/BREACH-style side channel). There is no "
            "padding mitigation on this endpoint today, so trust-boundary "
            "separation is the only protection — don't rely on padding."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "texts": {
                    "type": "array", "items": {"type": "string"},
                    "description": (
                        "The messages to batch together, in order. Two or "
                        "more — a single message gets no benefit."),
                },
                "dict_id": {
                    "type": "string", "default": "finance",
                    "description": (
                        "Which trained dictionary to compress against. Call "
                        "list_packages to see the options."),
                },
                "agent_id": {
                    "type": "string",
                    "description": "Optional. A label for audit/metrics.",
                },
            },
            "required": ["texts"],
        },
    },
    {
        "name": "unpack_batch",
        "description": (
            "Unpack a batch packet made by pack_batch (or by the "
            "/api/v1/pack-batch endpoint) back into the exact original list "
            "of messages, in order. REQUIRES A KEY. Not for a packet made "
            "by the single-message pack endpoint — that is a different "
            "format and this will reject it."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "packet_b64": {
                    "type": "string",
                    "description": "The packet_b64 returned by pack_batch.",
                },
                "agent_id": {
                    "type": "string",
                    "description": "Optional. A label for audit/metrics.",
                },
            },
            "required": ["packet_b64"],
        },
    },
]


def _nyckel() -> str:
    return os.environ.get("CAP_SHIELD_API_KEY", "").strip()


# ----------------------------------------------------------------------
# Utbytbar transport
#
# Servern kan köras på två sätt:
#
#   1. Fristående, på användarens dator. Då gör den HTTP mot BAS, precis
#      som förut. Detta är standardläget och ändras inte.
#
#   2. Inne i gatewayen, bakom POST /mcp. Då vore ett HTTP-anrop ett
#      anrop till den EGNA processen — det fungerar, men en tidsgräns
#      mot sig själv är svår att felsöka.
#
# Alternativet hade varit en andra dispatch som anropar core direkt. Då
# finns två kodvägar som gör samma sak och kan glida isär. DELPAKET låg
# i tre kopior av precis det skälet (åtgärdat i cap_package_ids.py),
# och det upptäcktes av en slump.
#
# Med kroken: en dispatch, en verktygstabell, två backends.
# ----------------------------------------------------------------------
_UTFORARE = None


_NYCKEL_FOR_ANROP = None


def satt_nyckel_for_anrop(nyckel: str | None) -> None:
    """Nyckel för det pågående anropet, i stället för miljövariabeln.

    Sätts av gatewayen när servern körs bakom POST /mcp. I stdio-läget
    rörs den aldrig, och _nyckel() läser miljön som förut.
    """
    global _NYCKEL_FOR_ANROP
    _NYCKEL_FOR_ANROP = nyckel


def satt_utforare(fn) -> None:
    """Byt ut transporten.

    fn(vag, kropp, metod, nyckel) -> dict

    Sätts av gatewayen vid uppstart. Rörs aldrig i stdio-läget — sätts
    ingen utförare går allt via urllib som förut.
    """
    global _UTFORARE
    _UTFORARE = fn


def _anrop(vag: str, kropp: dict | None = None, metod: str = "POST",
           kraver_nyckel: bool = True, nyckel: str | None = None) -> dict:
    """Anrop mot gatewayen.

    Går via _UTFORARE om en satts, annars HTTP med urllib — inget extra
    beroende.

    `nyckel` åsidosätter miljövariabeln. Behövs när servern körs bakom
    POST /mcp och nyckeln kommer ur Authorization-huvudet på just den
    förfrågan i stället för ur processens miljö. Utelämnas den läses
    miljön, som förut.
    """
    n = (nyckel if nyckel is not None
         else _NYCKEL_FOR_ANROP or _nyckel())

    if kraver_nyckel and not n:
        return {"error": (
            "No API key. Set CAP_SHIELD_API_KEY in the server's env, "
            "or call get_account to obtain one. The measure_traffic "
            "and list_packages tools work without a key.")}

    if _UTFORARE is not None:
        try:
            return _UTFORARE(vag, kropp, metod, n)
        except Exception as exc:
            # Utföraren får aldrig fälla servern. Ett fel här ska se ut
            # som ett fel från API:t, inte som en krasch i transporten.
            return {"error": f"Internal call failed: {exc}"}

    import urllib.error
    import urllib.request

    huvuden = {"Content-Type": "application/json",
               "User-Agent": f"cap-shield-mcp/{VERSION}"}
    if kraver_nyckel:
        huvuden["Authorization"] = f"Bearer {n}"

    data = json.dumps(kropp).encode("utf-8") if kropp is not None else None
    req = urllib.request.Request(f"{BAS}{vag}", data=data,
                                 headers=huvuden, method=metod)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return {"error": json.loads(exc.read().decode("utf-8"))}
        except Exception:
            return {"error": f"HTTP {exc.code}"}
    except Exception as exc:
        return {"error": f"Could not reach {BAS}: {exc}"}


def kor_verktyg(namn: str, arg: dict) -> dict:
    if namn == "measure_traffic":
        kropp = {"texts": arg.get("texts", []),
                 "dict_id": arg.get("dict_id", "finance")}
        if arg.get("query"):
            kropp["query"] = arg["query"]
        return _anrop("/api/v1/try", kropp, kraver_nyckel=False)

    if namn == "list_packages":
        return _anrop("/api/v1/catalog/status", metod="GET",
                      kraver_nyckel=False)

    if namn == "remember":
        import uuid
        kropp = {
            "namespace": arg["namespace"],
            "item_id": arg.get("item_id") or uuid.uuid4().hex[:16],
            "text": arg["text"]}
        if arg.get("ttl_days"):
            kropp["ttl_days"] = arg["ttl_days"]
        return _anrop("/api/v1/memory/put", kropp)

    if namn == "assemble_context":
        kropp = {
            "namespace": arg["namespace"], "query": arg["query"],
            "token_budget": arg.get("token_budget", 2000)}
        # FAS L: utan detta skulle reduce/target_tokens tystna HÄR —
        # _mcp_utforare()s SAMTYCKE_KRAVS-kontroll och själva
        # reduktionen i memory_assemble() skulle aldrig nås från ett
        # RIKTIGT MCP-anrop, bara från ett direkt Python-anrop till
        # _mcp_utforare.
        if arg.get("reduce"):
            kropp["reduce"] = True
        if arg.get("target_tokens"):
            kropp["target_tokens"] = arg["target_tokens"]
        return _anrop("/api/v1/memory/assemble", kropp)

    if namn == "assemble_escalation_context":
        kropp = {"namespace": arg["namespace"], "query": arg["query"]}
        if arg.get("token_budget"):
            kropp["token_budget"] = arg["token_budget"]
        if arg.get("utelamnat_tokens") is not None:
            kropp["utelamnat_tokens"] = arg["utelamnat_tokens"]
        return _anrop("/api/v1/memory/assemble-escalation", kropp)

    if namn == "get_account":
        kropp = {"email": arg["email"]}
        if arg.get("traffic"):
            kropp["traffic"] = arg["traffic"]
        return _anrop("/api/v1/beta-signup", kropp, kraver_nyckel=False)

    if namn == "issue_pass":
        kropp = {"acts_for": arg["acts_for"]}
        if arg.get("audience"):
            kropp["audience"] = arg["audience"]
        if arg.get("scope"):
            kropp["scope"] = arg["scope"]
        return _anrop("/api/v1/pass", kropp)

    if namn == "pack_batch":
        kropp = {"texts": arg.get("texts", []),
                 "dict_id": arg.get("dict_id", "finance")}
        if arg.get("agent_id"):
            kropp["agent_id"] = arg["agent_id"]
        return _anrop("/api/v1/pack-batch", kropp)

    if namn == "unpack_batch":
        kropp = {"packet_b64": arg["packet_b64"]}
        if arg.get("agent_id"):
            kropp["agent_id"] = arg["agent_id"]
        return _anrop("/api/v1/unpack-batch", kropp)

    return {"error": f"Unknown tool: {namn}"}


# ----------------------------------------------------------------------
# JSON-RPC över stdio
# ----------------------------------------------------------------------
def hantera(begaran: dict) -> dict | None:
    """Ett meddelande in, ett svar ut. None för notifieringar."""
    metod = begaran.get("method", "")
    rid = begaran.get("id")

    if metod == "initialize":
        return _svar(rid, {
            "protocolVersion": PROTOKOLL,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "cap-shield", "version": VERSION},
        })

    if metod == "notifications/initialized":
        return None          # notifiering, inget svar

    if metod == "tools/list":
        return _svar(rid, {"tools": VERKTYG})

    if metod == "tools/call":
        p = begaran.get("params", {})
        try:
            resultat = kor_verktyg(p.get("name", ""), p.get("arguments", {}))
        except KeyError as exc:
            resultat = {"error": f"Missing required argument: {exc}"}
        except Exception as exc:
            resultat = {"error": f"{type(exc).__name__}: {exc}"}
        return _svar(rid, {"content": [
            {"type": "text",
             "text": json.dumps(resultat, ensure_ascii=False, indent=2)}]})

    if rid is None:
        return None          # okänd notifiering — tig
    return {"jsonrpc": "2.0", "id": rid,
            "error": {"code": -32601, "message": f"Unknown method: {metod}"}}


def _svar(rid: Any, resultat: dict) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "result": resultat}


def main() -> None:
    """Läs rad för rad från stdin, svara på stdout.

    ALL LOGGNING TILL STDERR. Stdout är protokollkanalen — en enda
    print() där bryter kommunikationen, och felet ser ut som att servern
    hängt sig.
    """
    print(f"cap-shield MCP server, {len(VERKTYG)} tools, target {BAS}",
          file=sys.stderr)

    try:
        for rad in sys.stdin:
            rad = rad.strip()
            if not rad:
                continue
            try:
                begaran = json.loads(rad)
            except json.JSONDecodeError:
                continue
            svar = hantera(begaran)
            if svar is not None:
                sys.stdout.write(json.dumps(svar, ensure_ascii=False) + "\n")
                sys.stdout.flush()
    except (KeyboardInterrupt, BrokenPipeError):
        # En agent som stänger servern ska inte se ett stackspår i sin
        # logg. Avslut är inte ett fel — det är hur en MCP-server dör.
        pass


if __name__ == "__main__":
    main()
