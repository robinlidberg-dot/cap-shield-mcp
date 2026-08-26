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
VERSION = "0.1.0"


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
]


def _nyckel() -> str:
    return os.environ.get("CAP_SHIELD_API_KEY", "").strip()


def _anrop(vag: str, kropp: dict | None = None, metod: str = "POST",
           kraver_nyckel: bool = True) -> dict:
    """HTTP mot gatewayen. Använder urllib — inget extra beroende."""
    import urllib.error
    import urllib.request

    huvuden = {"Content-Type": "application/json",
               "User-Agent": f"cap-shield-mcp/{VERSION}"}
    if kraver_nyckel:
        n = _nyckel()
        if not n:
            return {"error": (
                "No API key. Set CAP_SHIELD_API_KEY in the server's env, "
                "or call get_account to obtain one. The measure_traffic "
                "and list_packages tools work without a key.")}
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
        return _anrop("/api/v1/memory/put", {
            "namespace": arg["namespace"],
            "item_id": arg.get("item_id") or uuid.uuid4().hex[:16],
            "text": arg["text"]})

    if namn == "assemble_context":
        return _anrop("/api/v1/memory/assemble", {
            "namespace": arg["namespace"], "query": arg["query"],
            "token_budget": arg.get("token_budget", 2000)})

    if namn == "get_account":
        kropp = {"email": arg["email"]}
        if arg.get("traffic"):
            kropp["traffic"] = arg["traffic"]
        return _anrop("/api/v1/beta-signup", kropp, kraver_nyckel=False)

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
