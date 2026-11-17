#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cap_fokuslasare.py -- fokuserad läsning för cap_escalate_helper.py (v6)

Fyra vägar som krymper kontexten till de sessioner som hör till frågan
och ställer en kort, riktad fråga till modellen. De används av
`eskalera_om_behovs_v6()` i cap_escalate_helper.py och gör inga egna
nätverksanrop: anroparen skickar in en funktion `anropa(prompttext) ->
svarstext`.

  forsok_preferens   frågan ber om råd eller förslag
  forsok_tidsankare  frågan gäller en händelse vid en angiven tidpunkt
                     ("last Saturday", "the past weekend", "two weeks
                     ago"); modellen listar händelserna, Python väljer
  forsok_ordning     kronologisk ordning; en händelse utan exakt datum
                     sorteras på sin sessions tidpunkt
  forsok_avstaende   omläsning när det första svaret var "Not available"
  las_om             samma omläsning, använd som andra bedömning när ett
                     svar som INTE är ett avstående bär ett varningstecken
                     (se varningstecken()); returnerar även ett avstående

Varje funktion returnerar {"svar": ..., "ra": ...} eller None. None
betyder "kom inte fram till något": anroparen ska då behålla det svar
den annars skulle ha gett. Ingen väg gissar.

Kontexten ska vara uppdelad med rubriker på formen
"--- Session YYYY/MM/DD (Day) HH:MM ---". Saknas sådana rubriker
returnerar alla vägar None.

URSPRUNG: logiken och prompterna är ordagrant de som kördes och mättes i
steg90_fokuserad_lasare.py (2026-11-12 -- 2026-11-13): tidsankare
version 1, preferens version 1 (version 2 mättes och var sämre),
avstaende version 2, ordning version 1. Se
CAP-Shield_Steg90_Slutlage_479av500_2026-11-13.md för mätningarna.
Ändra inte en prompt här utan att mäta om den vägen på alla frågor den
träffar.

TILLÄGG 2026-11-13 (steg 92): intervallregeln i valj_handelse(), en andra
och bredare läsning i forsok_tidsankare() när den första inte hittar
någon händelse, varningstecken() och las_om(), samt rakna_om() för
räknefrågor. prompt_avstaende() är oförändrad, tecken för tecken.

TILLÄGG 2026-11-14 (steg 94): prompt_rakning() för räknevägen, med en
regel om att det användaren äger räknas som införskaffat. Steg 99:
las_med_utelamnat(), kompletterande läsning vid avstående. Steg 95:
"how many times have I" räknas som räknefråga, med en regel om att en
löpande summa bara kan växa.
"""
from __future__ import annotations

import calendar
import json
import math
import re
from collections import Counter
from datetime import date, timedelta
from typing import Callable

Anropa = Callable[[str], str]


# ---------------------------------------------------------------------------
# 1. Sessioner och BM25-rankning (ren Python)
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 1. Sessioner och BM25-rankning (ren Python, inga anrop)
# ---------------------------------------------------------------------------
_RUBRIK = re.compile(
    r"--- Session (\d{4})/(\d{2})/(\d{2}) \(([A-Za-z]{3})\) (\d{2}:\d{2}) ---")

_STOPPORD = set("""a an the is are was were be been being to of in on at by
for with from as it its that this these those and or but so do does did yes
no not my your i you we they he she him her them our their has have had
will would can could if than then there here which who what when where why
how me mine am im ive about some any into over up down out just also very
much many more most other such only own same too don now tell remind
previous conversation looking back wondering going go get got please""".split())

def _stam(w: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[:-len(suf)]
    return w

def _ord(s: str) -> list[str]:
    return [_stam(w) for w in re.findall(r"[a-z0-9]+", s.lower())
            if w not in _STOPPORD and len(w) > 1]

def dela_sessioner(kontext: str) -> list[dict]:
    traffar = list(_RUBRIK.finditer(kontext))
    ut = []
    for i, m in enumerate(traffar):
        slut = traffar[i + 1].start() if i + 1 < len(traffar) else len(kontext)
        ut.append({
            "idx": i,
            "datum": date(int(m.group(1)), int(m.group(2)), int(m.group(3))),
            "datumstr": f"{m.group(1)}/{m.group(2)}/{m.group(3)}",
            "tid": m.group(5),
            "block": kontext[m.start():slut].strip(),
        })
    return ut

def bm25_ranka(sessioner: list[dict], fraga: str,
               k1: float = 1.5, b: float = 0.75) -> list[tuple[float, dict]]:
    """Rankar hela sessioner mot frågans innehållsord. Högst poäng först."""
    dok = [_ord(s["block"]) for s in sessioner]
    n = len(dok)
    if n == 0:
        return []
    snitt = sum(len(d) for d in dok) / n or 1.0
    df = Counter()
    for d in dok:
        for w in set(d):
            df[w] += 1
    q = list(dict.fromkeys(_ord(fraga)))
    ut = []
    for s, d in zip(sessioner, dok):
        tf = Counter(d)
        poang = 0.0
        for w in q:
            if tf[w] == 0:
                continue
            idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
            poang += idf * tf[w] * (k1 + 1) / (
                tf[w] + k1 * (1 - b + b * len(d) / snitt))
        ut.append((poang, s))
    ut.sort(key=lambda x: (-x[0], x[1]["idx"]))
    return ut

_VECKODAGAR_KORT = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def sessionsrubrik(created_utc, item_id: str = "") -> str:
    """"--- Session YYYY/MM/DD (Ddd) HH:MM ---" ur ett datum i
    LongMemEval-form (används som det är) eller ISO-form ("2026-11-15T
    10:00:00Z"). Saknas datum används item_id. Samma regel som
    cap_memory.MemoryStore.sessionsrubrik()."""
    d = str(created_utc or "").strip()
    if not d:
        return f"--- Session {item_id} ---"
    if re.match(r"^\d{4}/\d{2}/\d{2} \([A-Za-z]{3}\) \d{2}:\d{2}$", d):
        return f"--- Session {d} ---"
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?", d)
    if not m:
        return f"--- Session {d} ---"
    try:
        dag = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return f"--- Session {d} ---"
    return (f"--- Session {dag.strftime('%Y/%m/%d')} "
            f"({_VECKODAGAR_KORT[dag.weekday()]}) "
            f"{m.group(4) or '00'}:{m.group(5) or '00'} ---")


def rubricerad_kontext(selected: list) -> str:
    """Bygger en kontext med sessionsrubriker ur assemble_context()s
    "selected" (varje post har "item_id", "text" och "created_utc").
    assemble_context()s egen "context" är rubrikfri för att spara tokens;
    v6:s fokuserade läsning behöver datumen (steg 100)."""
    poster = [p for p in (selected or [])
              if isinstance(p, dict) and p.get("text")]
    poster.sort(key=lambda p: str(p.get("item_id", "")))
    return "\n\n".join(
        f"{sessionsrubrik(p.get('created_utc'), str(p.get('item_id', '')))}"
        f"\n{p['text']}" for p in poster)


def fokuskontext(kontext: str, fraga: str, k: int) -> tuple[str, list[dict]]:
    """De k högst rankade sessionerna, återgivna i kronologisk ordning."""
    rankade = bm25_ranka(dela_sessioner(kontext), fraga)
    valda = [s for _, s in rankade[:k]]
    valda.sort(key=lambda s: (s["datum"], s["tid"]))
    return "\n\n".join(s["block"] for s in valda), valda

def preferenskontext(kontext: str, fraga: str, k_hela: int = 4,
                     oppning: int = 1200) -> str:
    """Rådfrågor är vaga ("any tips?"), så ordöverlapp räcker inte alltid
    för att hitta sessionen där användaren berättat det relevanta om sig
    själv. Därför: de k_hela högst rankade sessionerna i sin helhet, plus
    BÖRJAN av varje annan session -- där står användarens eget ärende,
    som oftast är just den personliga uppgiften."""
    rankade = [s for _, s in bm25_ranka(dela_sessioner(kontext), fraga)]
    hela = sorted(rankade[:k_hela], key=lambda s: (s["datum"], s["tid"]))
    ovriga = sorted(rankade[k_hela:], key=lambda s: (s["datum"], s["tid"]))
    delar = ["=== SESSIONS SHOWN IN FULL ==="]
    delar += [s["block"] for s in hela]
    delar.append("=== BEGINNING OF EVERY OTHER SESSION (cut off after the "
                 "first part) ===")
    for s in ovriga:
        b = s["block"]
        delar.append(b if len(b) <= oppning else b[:oppning] + " [...]")
    return "\n\n".join(delar)



# ---------------------------------------------------------------------------
# 2. Vilken väg en fråga hör till (frågans form, aldrig en enskild fråga)
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 2. Klassificerare (frågans form, aldrig frågans nummer)
# ---------------------------------------------------------------------------
_RADFRAGA = re.compile(
    r"^\s*can you (suggest|recommend)\b"
    r"|\bany (helpful )?(tips|advice|suggestions|recommendations|ideas)\b"
    r"|\bdo you have any (ideas|suggestions|tips|recommendations|advice)\b"
    r"|\bwhat do you think\b|\bdo you think (it|that|i)\b"
    r"|^\s*what should i\b|\bcould there be a reason\b"
    r"|\b\w+ recommendations\?\s*$", re.IGNORECASE)
_AVSTAENDE_SVAR = re.compile(
    r"not available|not enough|insufficient|cannot be determined"
    r"|no information", re.IGNORECASE)
_VECKODAGAR = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
               "Saturday", "Sunday"]
_SISTA_VECKODAG = re.compile(
    r"\blast\s+(" + "|".join(_VECKODAGAR) + r")\b", re.IGNORECASE)
_SISTA_HELG = re.compile(
    r"\b(?:the\s+)?(?:past|last|this\s+past)\s+weekend\b", re.IGNORECASE)
_ORDTAL = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4,
           "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
_NSTEG = re.compile(
    r"\b(\d+|" + "|".join(_ORDTAL) + r")\s+(day|week|month)s?\s+ago\b",
    re.IGNORECASE)
_VECKODAG_BLANDAD = re.compile(
    r"\b(" + "|".join(_VECKODAGAR) + r")\b.{0,20}\bago\b", re.IGNORECASE)
_SEDAN_ANKARE = re.compile(r"\bsince\b[^?.]*\bago\b", re.IGNORECASE)
_HUR_LANGE = re.compile(r"^\s*how (many|long)\b", re.IGNORECASE)


def _datum_ur(fragans_datum) -> date:
    """Frågans datum. Tar "YYYY/MM/DD (Day) HH:MM", "YYYY-MM-DD", ett
    date-objekt eller None (= i dag)."""
    if isinstance(fragans_datum, date):
        return fragans_datum
    m = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", str(fragans_datum or ""))
    if not m:
        return date.today()
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def tidsankare(fraga: str, fragans_datum: str) -> dict | None:
    """Returnerar målfönstret om frågan gäller EN händelse vid en angiven
    tidpunkt, annars None.

    Tre former. Veckodag och helg är EXAKTA ankare (snäv tolerans);
    "N enheter sedan" är ungefärligt (toleransen växer med enheten).
    Utesluts: "since ... N weeks ago" (ankaret är då en startpunkt för
    en räkning, inte tidpunkten för händelsen), "how many/long ... ago"
    (tidsskillnadsfrågor, egen väg i steg70/71) och "the Wednesday two
    months ago" (blandform)."""
    bas = _datum_ur(fragans_datum)
    m = _SISTA_VECKODAG.search(fraga)
    if m:
        mal = _VECKODAGAR.index(m.group(1).capitalize())
        diff = (bas.weekday() - mal) % 7 or 7
        d = bas - timedelta(days=diff)
        return {"typ": "veckodag", "lo": d, "hi": d, "tolerans": 1,
                "text": f"\"{m.group(0)}\" = {d.isoformat()} "
                        f"({_VECKODAGAR[d.weekday()]})"}
    m = _SISTA_HELG.search(fraga)
    if m:
        diff = (bas.weekday() - 5) % 7 or 7
        lor = bas - timedelta(days=diff)
        son = lor + timedelta(days=1)
        return {"typ": "helg", "lo": lor, "hi": son, "tolerans": 1,
                "text": f"\"{m.group(0)}\" = the weekend of "
                        f"{lor.isoformat()} (Saturday) to {son.isoformat()} "
                        f"(Sunday)"}
    if (_VECKODAG_BLANDAD.search(fraga) or _SEDAN_ANKARE.search(fraga)
            or _HUR_LANGE.search(fraga)):
        return None
    m = _NSTEG.search(fraga)
    if not m:
        return None
    ratt = m.group(1).lower()
    n = int(ratt) if ratt.isdigit() else _ORDTAL[ratt]
    enhet = m.group(2).lower()
    if enhet == "day":
        d, tol = bas - timedelta(days=n), 3
    elif enhet == "week":
        d, tol = bas - timedelta(weeks=n), 6
    else:
        mo, y = bas.month - n, bas.year
        while mo <= 0:
            mo += 12
            y -= 1
        d = date(y, mo, min(bas.day, calendar.monthrange(y, mo)[1]))
        tol = 16
    return {"typ": "nsteg", "lo": d, "hi": d, "tolerans": tol,
            "text": f"\"{m.group(0)}\" = around {d.isoformat()} "
                    f"({_VECKODAGAR[d.weekday()]})"}

def _avstand(d: date, ankare: dict) -> int:
    if d < ankare["lo"]:
        return (ankare["lo"] - d).days
    if d > ankare["hi"]:
        return (d - ankare["hi"]).days
    return 0

def tidsankare_kandidater(kontext: str, fraga: str, ankare: dict,
                          k_datum: int = 3, max_tecken: int = 160_000
                          ) -> list[dict]:
    """Alla sessioner på de k_datum närmaste DISTINKTA datumen (samma
    princip som steg85 efter dess rättelse). Om de tillsammans blir
    större än max_tecken behålls, datum för datum med närmaste först, de
    sessioner som BM25 rankar högst mot frågan."""
    sessioner = dela_sessioner(kontext)
    if not sessioner:
        return []
    rang = {s["idx"]: i for i, (_, s) in enumerate(bm25_ranka(sessioner, fraga))}
    datum = sorted({s["datum"] for s in sessioner},
                   key=lambda d: (_avstand(d, ankare), d))[:k_datum]
    valda, tecken = [], 0
    for d in datum:
        dagens = sorted((s for s in sessioner if s["datum"] == d),
                        key=lambda s: rang[s["idx"]])
        for s in dagens:
            if valda and tecken + len(s["block"]) > max_tecken:
                continue
            valda.append(s)
            tecken += len(s["block"])
    valda.sort(key=lambda s: (s["datum"], s["tid"]))
    return valda

# Samma mönster som _V5_ORDNINGSFRAGA i cap_escalate_helper.py.
_ORDNINGSFRAGA = re.compile(
    r"\b(order of|earliest to latest|latest to earliest|chronological "
    r"order|in what order|which order)\b", re.IGNORECASE)

_ORDNING_FALLANDE = re.compile(
    r"\b(latest to earliest|most recent first|reverse chronological)\b",
    re.IGNORECASE)


def ar_radfraga(fraga: str) -> bool:
    return bool(_RADFRAGA.search(fraga or ""))


def ar_ordningsfraga(fraga: str) -> bool:
    return bool(_ORDNINGSFRAGA.search(fraga or ""))


def ar_avstaende(svar) -> bool:
    return bool(_AVSTAENDE_SVAR.search(str(svar or "")))


# ---------------------------------------------------------------------------
# 3. Prompter (engelska; all mätning är gjord med exakt dessa texter)
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 3. Prompter (engelska: all data är engelsk, och det undviker de
#    språkbyten i svaret som de svenska prompterna tidigare gett)
# ---------------------------------------------------------------------------
def prompt_tidsankare(fraga: str, fragans_datum: str, ankare: dict,
                      kandidater: list[dict]) -> str:
    bas = _datum_ur(fragans_datum)
    text = "\n\n".join(s["block"] for s in kandidater)
    return (
        "You are helping to answer a question about a user's past "
        "conversations with an AI assistant.\n"
        f"The question was asked on {bas.isoformat()} "
        f"({_VECKODAGAR[bas.weekday()]}). It refers to something that "
        f"happened at a specific time: {ankare['text']}.\n\n"
        "Below are the conversation sessions closest in time to that "
        "date. Each session starts with a header \"--- Session YYYY/MM/DD "
        "(Day) HH:MM ---\" that tells when that conversation took place. "
        "Within a session the user's messages and the assistant's replies "
        "alternate.\n\n"
        "TASK. List every event the USER reports in these sessions that "
        "could be the event the question is about, i.e. the same kind of "
        "event or activity that the question describes. Include an event "
        "even if one detail differs slightly from the wording of the "
        "question. For each event, work out WHEN IT ACTUALLY HAPPENED:\n"
        "- described as happening \"today\", \"just now\", \"this "
        "morning\", \"I just got/bought/finished ...\": the date of that "
        "session;\n"
        "- \"yesterday\": the session date minus one day; \"two days "
        "ago\", \"last Saturday\", \"last weekend\" and similar: count "
        "from the session date;\n"
        "- only vaguely dated (\"recently\", \"this month\", \"a while "
        "ago\"): give your best estimate and set \"datum_sakert\" to "
        "false;\n"
        "- something the user only plans, considers or has not done yet "
        "is not an event: leave it out.\n\n"
        "For each event also give the answer to the question under the "
        "assumption that this event is the one meant. Take the answer "
        "only from that session's text. If the text gives a description "
        "instead of a name, answer with that description. For a yes/no "
        "question the answer is just \"Yes\" or \"No\"; if the session "
        "describing the event does not mention the thing asked about, "
        "the answer is \"No\".\n\n"
        "Reply with ONLY a JSON list and nothing else:\n"
        "[{\"session\": \"YYYY/MM/DD\", \"handelse\": \"<short "
        "description>\", \"handelsedatum\": \"YYYY-MM-DD\", "
        "\"datum_sakert\": true, \"svar\": \"<short answer in "
        "English>\"}]\n"
        "If no such event is reported at all, reply [].\n\n"
        f"QUESTION: {fraga}\n\nSESSIONS:\n{text}\n"
    )

_TIDSANKARE_SMAL = (
    "TASK. List every event the USER reports in these sessions that "
    "could be the event the question is about, i.e. the same kind of "
    "event or activity that the question describes. Include an event "
    "even if one detail differs slightly from the wording of the "
    "question. For each event, work out WHEN IT ACTUALLY HAPPENED:\n")
_TIDSANKARE_BRED = (
    "TASK. A first, strict reading found no matching event, so read "
    "more broadly this time. List every event or activity the USER "
    "reports in these sessions that could be what the question is "
    "about. Read the question's description loosely: an activity of a "
    "closely related kind, involving the same sort of thing, counts "
    "even when the user used another verb or a more specific word than "
    "the question does. For each event, work out WHEN IT ACTUALLY "
    "HAPPENED:\n")
_TIDSANKARE_PLAN_SMAL = (
    "- something the user only plans, considers or has not done yet "
    "is not an event: leave it out.\n\n")
_TIDSANKARE_PLAN_BRED = (
    "- something the user says they are doing or are about to do that "
    "same day (\"I will ... today\", \"tonight\", \"later today\", "
    "\"I'm about to ...\"): the date of that session. The question is "
    "asked later, so by then it has taken place;\n"
    "- something the user only considers, or plans for some other, "
    "later time, is not an event: leave it out.\n\n")


def prompt_tidsankare_bred(fraga: str, fragans_datum: str, ankare: dict,
                           kandidater: list[dict]) -> str:
    """Andra läsningen. Samma text som prompt_tidsankare() med två
    stycken utbytta: uppgiften läses bredare, och det användaren säger
    sig göra samma dag räknas som inträffat den dagen. Börjar med en
    egen första mening så att de två läsningarna går att skilja åt."""
    smal = prompt_tidsankare(fraga, fragans_datum, ankare, kandidater)
    if _TIDSANKARE_SMAL not in smal or _TIDSANKARE_PLAN_SMAL not in smal:
        raise ValueError("prompt_tidsankare() har ändrats")
    bred = smal.replace(_TIDSANKARE_SMAL, _TIDSANKARE_BRED, 1)
    bred = bred.replace(_TIDSANKARE_PLAN_SMAL, _TIDSANKARE_PLAN_BRED, 1)
    return "SECOND READING. " + bred


def prompt_avstaende(fraga: str, fragans_datum: str, text: str,
                     antal: int) -> str:
    """Version 2 (2026-11-12). Version 1 bad modellen jämföra "namn och
    detaljer bokstavligt". Den hittade då rätt mening i n=40, 61, 176 och
    495 men avstod ändå, eftersom frågan beskrev saken lite annorlunda än
    användaren en gång gjorde -- samtidigt som den svarade på n=231 (en
    ANNAN poster än den efterfrågade) och n=233 (assistentens egen
    prisuppgift i stället för användarens). Version 2 skiljer därför på
    tre saker: vems uppgift det är (regel A), om det är SAMMA sak som
    bara beskrivs löst (B1) eller en ANNAN sak (B2), och om en del av en
    flerdelad fråga saknas (B3)."""
    bas = _datum_ur(fragans_datum)
    return (
        "You answer a question about what a user told an AI assistant in "
        "earlier conversations.\n"
        f"Below are the {antal} past conversation sessions most relevant "
        "to the question, in chronological order. Each starts with a "
        "header \"--- Session YYYY/MM/DD (Day) HH:MM ---\" that tells "
        "when that conversation took place. Within a session the user's "
        "messages and the assistant's replies alternate, and the user "
        "always speaks first.\n"
        f"The question was asked on {bas.isoformat()} "
        f"({_VECKODAGAR[bas.weekday()]}).\n\n"
        "A first reading of the whole history gave no answer. Read these "
        "sessions carefully and decide what the right response is.\n\n"
        "RULE A - whose information counts. Facts about the user (what "
        "they did, own, paid, were told, plan) come from the USER's own "
        "messages. General information, typical prices, ranges or "
        "estimates that the ASSISTANT offered are not facts about the "
        "user. Only when the question asks what the assistant said or "
        "produced earlier do you take the answer from the assistant's "
        "reply, and then you quote it exactly.\n\n"
        "RULE B - find the thing the question is about (the person, "
        "place, object, brand, activity, role, project) and decide which "
        "case applies.\n"
        "B1. That very thing is in the sessions, and there is one stated "
        "fact about it that the question can reasonably be pointing at. "
        "People often word a question loosely, or slightly differently "
        "from what they said at the time: they may ask about a thing "
        "when the figure was stated for something that belongs to it, "
        "ask for one kind of label when they gave another, or use a "
        "technical term loosely. In this case the stated fact IS the "
        "answer. Give it, and add in square brackets what it literally "
        "referred to if that differs from the question's wording.\n"
        "B2. That very thing is NOT in the sessions; only something "
        "similar but different is (another pet, another city, another "
        "instrument, another device, another relative, another job "
        "title, another sport, another project or occasion, an item of "
        "a different size or model). Then the information is not "
        "available. Never answer with the similar thing.\n"
        "B3. The question needs two or more pieces of information (X "
        "and Y; from A until B; the difference between A and B) and the "
        "user never gave one of them. Then the information is not "
        "available. Do not answer with only the part you found, and do "
        "not fill the gap with the assistant's figures (rule A).\n\n"
        "RULE C - combining and dating. You may combine the user's "
        "facts from different sessions (add, subtract, compare, count "
        "the days between two dates). When the user reports having done "
        "something and gives no other date for it, the date of that "
        "session counts as the date it happened. Time expressions in "
        "the question (\"last Friday\", \"two weeks ago\") are counted "
        "from the question date.\n\n"
        "Write a short reasoning (2-5 lines) that names the case (B1, "
        "B2 or B3), and finish with exactly one last line, either\n"
        "SVAR: <the short, concrete answer in English> [<what it "
        "literally referred to, only if needed>]\n"
        "or, in case B2 or B3,\n"
        "SVAR: Not available in the provided selection.\n\n"
        f"QUESTION: {fraga}\n\nSESSIONS:\n{text}\n"
    )

def prompt_preferens(fraga: str, fragans_datum: str, text: str) -> str:
    if PREFERENS_PROMPT_VERSION == 2:
        return prompt_preferens_v2(fraga, fragans_datum, text)
    bas = _datum_ur(fragans_datum)
    return (
        "A user asks an AI assistant for a suggestion or for advice. The "
        "assistant has talked with this user before. Below are past "
        "conversation sessions with this user. Each starts with a header "
        "\"--- Session YYYY/MM/DD (Day) HH:MM ---\"; within a session the "
        "user's messages and the assistant's replies alternate, and the "
        "user always speaks first. A few sessions are shown in full; for "
        "the others only the beginning is shown, which is where the user "
        f"states what they are doing. Today is {bas.isoformat()}.\n\n"
        "This is NOT a fact lookup. The sessions will normally not "
        "contain a ready-made answer to the request. Give the answer a "
        "good personal assistant would give: one that visibly remembers "
        "this user.\n\n"
        "1. Find what the USER has said about themselves that is relevant "
        "to the request: things they own or use (brands, models), things "
        "they did or made and how it went, places they have been and "
        "what they enjoyed there, stated likes and dislikes, their field "
        "of work or study, their plans. Use only what the user said "
        "about themselves, not general advice the assistant gave.\n"
        "2. Give a recommendation that explicitly builds on those "
        "personal details and names them. If the user stated preferences "
        "in a comparable situation (another city, another occasion), "
        "apply the same preferences here.\n"
        "3. Do not give generic advice, do not ask for more information "
        "and do not say that information is missing. If you find nothing "
        "personal that is relevant, give your best suggestion anyway.\n\n"
        "First note in one or two lines which personal details you use. "
        "Then write the answer itself as 2-4 sentences in English on one "
        "final line that starts with \"SVAR: \".\n\n"
        f"REQUEST: {fraga}\n\nSESSIONS:\n{text}\n"
    )

# Version 2 (steg 104, 2026-11-16). Sex av de nio preferenssvar som
# domaren underkände godkändes vid manuell granskning (141, 146, 156,
# 139, 161, 143). Felen var av tre slag: allmänna råd blandade med de
# personliga (141, 146), bara en av flera relevanta uppgifter använd
# (143: örterna men inte tomaterna), och förslag som går emot
# användarens situation (139: en app före sänggåendet trots
# sömnproblem; 161: läsa under pendlingen). Version 2 ber därför om
# (a) varje del byggd på användarens egna uppgifter, (b) alla relevanta
# uppgifter, (c) inget som krockar med situationen. Egen inledning, så
# att svaren inte förväxlas med version 1:s i uppspelningen.
#
# MÄTT 2026-11-16 på alla 30, AVSTÄNGD (version 1 gäller). Domaren
# godkände 22 i stället för 21, men det var fem vunna (137, 143, 146,
# 156, 161) och fyra tappade (138, 142, 157, 158). Villkoret var att
# inget av de 21 skulle tappas. Läst mot rubriken är bara 138 sämre
# (true crime före stand-up); 142, 157 och 158 är lika bra som förut men
# underkändes. Efter manuell granskning blir summan densamma med båda
# versionerna: domaren svänger på preferenssvar, och en ny formulering
# flyttar mest vilka svar den underkänner.
PREFERENS_PROMPT_VERSION = 1


def prompt_preferens_v2(fraga: str, fragans_datum: str, text: str) -> str:
    bas = _datum_ur(fragans_datum)
    return (
        "PERSONAL ADVICE. A user asks an AI assistant for a suggestion or "
        "for advice. The assistant has talked with this user before. "
        "Below are past conversation sessions with this user. Each starts "
        "with a header \"--- Session YYYY/MM/DD (Day) HH:MM ---\"; within "
        "a session the user's messages and the assistant's replies "
        "alternate, and the user always speaks first. A few sessions are "
        "shown in full; for the others only the beginning is shown, which "
        "is where the user states what they are doing. Today is "
        f"{bas.isoformat()}.\n\n"
        "This is NOT a fact lookup. The sessions will normally not "
        "contain a ready-made answer to the request. Give the answer a "
        "good personal assistant would give: one that visibly remembers "
        "this user and is about nothing else.\n\n"
        "1. Find EVERYTHING the USER has said about themselves that is "
        "relevant to the request: things they own, use, grow or make "
        "(with brands and models), things they did and how it went, "
        "places they enjoyed, stated likes and dislikes, problems they "
        "mentioned, their field of work or study, their plans. Use only "
        "what the user said about themselves, not general advice the "
        "assistant gave.\n"
        "2. Build every part of the answer on those details and name "
        "them. Use all of the relevant ones, not just the first you "
        "find. If the user stated preferences in a comparable situation "
        "(another city, another occasion), apply them here. Leave out "
        "generic tips that are not tied to something the user said.\n"
        "3. Check each suggestion against the user's situation and what "
        "they said. Leave out anything that conflicts with it: something "
        "they said they want to avoid, reduce or move away from, "
        "something that has caused them a problem they mentioned, or "
        "something the situation itself rules out.\n"
        "4. Do not ask for more information and do not say that "
        "information is missing. If you find nothing personal that is "
        "relevant, give your best suggestion anyway.\n\n"
        "First note in one or two lines which personal details you use "
        "and what you leave out because of rule 3. Then write the answer "
        "itself as 2-4 sentences in English on one final line that "
        "starts with \"SVAR: \".\n\n"
        f"REQUEST: {fraga}\n\nSESSIONS:\n{text}\n"
    )


def prompt_preferens_kontroll(fraga: str, fragans_datum: str, text: str,
                              utkast: str) -> str:
    """Andra steget i preferensvägen (steg 93). Utkastet från
    prompt_preferens() granskas mot samma sessioner och rättas bara om
    det bygger på fel sak, går emot något användaren sagt eller lämnar
    en uppgift oanvänd som hör till frågan."""
    bas = _datum_ur(fragans_datum)
    return (
        "CHECK OF A DRAFT. A user asked an AI assistant for a suggestion "
        "or for advice, and the assistant wrote the draft answer below. "
        "The assistant has talked with this user before. The past "
        "conversation sessions follow after the draft. Each starts with a "
        "header \"--- Session YYYY/MM/DD (Day) HH:MM ---\"; within a "
        "session the user's messages and the assistant's replies "
        "alternate, and the user always speaks first. A few sessions are "
        "shown in full; for the others only the beginning is shown. "
        f"Today is {bas.isoformat()}.\n\n"
        "Check the draft against what the USER has said about "
        "themselves, and correct it only where one of these three "
        "problems is present:\n\n"
        "1. WRONG BASIS. Look for what the user has said that is about "
        "the very topic of this request. If such statements exist and "
        "the draft is instead built on some other interest, project or "
        "plan of the user, rewrite the answer around the statements that "
        "are about this topic.\n"
        "2. AGAINST WHAT THE USER SAID. The draft suggests something the "
        "user has said they avoid, want less of, cannot do, or that has "
        "been causing them a problem; or something that does not fit the "
        "situation named in the request. Replace that part with "
        "something that fits.\n"
        "3. LEFT OUT. The user named concrete things that belong to this "
        "request (things they have or made, ingredients, tools, titles, "
        "a goal, a limit such as a time of day) and the draft leaves one "
        "of them unused although it clearly fits. Work it in.\n\n"
        "Keep everything in the draft that is already built on the "
        "user's own details. Do not add general advice and do not make "
        "the answer longer than 2-4 sentences. If none of the three "
        "problems is present, return the draft unchanged, word for "
        "word.\n\n"
        "First write one or two lines saying which of 1-3 you found, or "
        "\"none\". Then give the final answer in English on one last "
        "line that starts with \"SVAR: \".\n\n"
        f"REQUEST: {fraga}\n\nDRAFT: {utkast}\n\nSESSIONS:\n{text}\n"
    )


def prompt_ordning(fraga: str, fragans_datum: str, text: str) -> str:
    bas = _datum_ur(fragans_datum)
    return (
        "You are helping to answer a question about the ORDER in which "
        "things happened in a user's life, based on the user's past "
        "conversations with an AI assistant.\n"
        f"The question was asked on {bas.isoformat()} "
        f"({_VECKODAGAR[bas.weekday()]}).\n\n"
        "Below are the past conversation sessions most relevant to the "
        "question, in chronological order. Each starts with a header "
        "\"--- Session YYYY/MM/DD (Day) HH:MM ---\" that tells when that "
        "conversation took place. Within a session the user's messages "
        "and the assistant's replies alternate, and the user always "
        "speaks first.\n\n"
        "TASK. List every event the USER reports having experienced that "
        "the question asks to put in order (the right kind of event, "
        "inside the period the question names). List each event once, "
        "even if the user mentions it in several sessions. Leave out "
        "things the user only plans, and things only the assistant "
        "mentions. Do NOT sort them yourself; the sorting is done "
        "afterwards by a program.\n"
        "For each event work out WHEN IT HAPPENED:\n"
        "- \"today\", \"just\", \"this morning\": the date of that "
        "session;\n"
        "- \"yesterday\", \"two days ago\", \"last weekend\", \"last "
        "Saturday\": count from that session's date;\n"
        "- an explicit date in the text: that date;\n"
        "- only vaguely dated: your best estimate.\n"
        "Name each event with a short noun phrase in the user's own "
        "words for the kind of event and the place or occasion (for "
        "example \"book fair at the town library\"). No scores, no "
        "names of participants, no dates and no brackets in the name.\n\n"
        "Reply with ONLY a JSON list and nothing else:\n"
        "[{\"session\": \"YYYY/MM/DD\", \"namn\": \"<short noun "
        "phrase>\", \"handelsedatum\": \"YYYY-MM-DD\"}]\n"
        "If you find fewer than two such events, reply [].\n\n"
        f"QUESTION: {fraga}\n\nSESSIONS:\n{text}\n"
    )



# ---------------------------------------------------------------------------
# 4. Tolkning av modellsvar
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 5. Tolkning av modellsvar
# ---------------------------------------------------------------------------
def svarsrad(raw: str) -> str | None:
    rader = [r.strip() for r in (raw or "").splitlines() if r.strip()]
    for r in reversed(rader):
        m = re.match(r"^\**\s*SVAR\s*:\**\s*(.*)$", r, re.IGNORECASE)
        if m:
            return m.group(1).strip().strip("*").strip() or None
    return None

_FORBEHALL = re.compile(r"\s*\[([^\]]*)\]\s*\.?\s*$")

def utan_forbehall(svar: str | None) -> str | None:
    """avstaende-vägen (version 2) låter modellen lägga ett förbehåll
    inom hakparentes efter svaret ("500 [signed poster copies]").
    Förbehållet är värdefullt för användaren men hör inte till själva
    svaret som bedöms; domaren läste det som att modellen tog tillbaka
    svaret. Här skiljs de åt: svaret bedöms, förbehållet sparas i
    råtexten."""
    if not svar:
        return svar
    return _FORBEHALL.sub("", svar).strip() or svar

_HUR_MANGA_SAK = re.compile(r"^\s*how many (\w+)", re.IGNORECASE)

def summera_delar(fraga: str, svar: str | None) -> str | None:
    """Om frågan gäller "how many <sak>" och svaret räknar upp två eller
    flera antal av just den saken ("5 tomato plants and 3 cucumber
    plants"), lägg ihop dem. Ren Python. Delar med annan enhet än
    frågans ("3 weeks and 1 day") rörs inte."""
    if not svar:
        return svar
    m = _HUR_MANGA_SAK.match(fraga or "")
    if not m:
        return svar
    sak = m.group(1).lower()
    stam = sak[:-1] if sak.endswith("s") and len(sak) > 3 else sak
    delar = [d.strip() for d in re.split(r"\s*,\s*(?:and\s+)?|\s+and\s+",
                                         svar.strip().rstrip("."))]
    if len(delar) < 2:
        return svar
    tal = []
    for d in delar:
        dm = re.match(r"^(\d+)\s+(?:[\w'-]+\s+){0,3}?(\w+)$", d)
        if not dm or not dm.group(2).lower().startswith(stam):
            return svar
        tal.append(int(dm.group(1)))
    return f"{sum(tal)} {sak} ({svar.strip().rstrip('.')})"

def json_lista(raw: str) -> list | None:
    text = re.sub(r"^```(?:json)?\s*|\s*```\s*$", "", (raw or "").strip(),
                  flags=re.IGNORECASE)
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        m = re.search(r"\[.*\]", text, re.DOTALL)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except (json.JSONDecodeError, ValueError):
            return None
    return data if isinstance(data, list) else None

def _till_datum(s) -> date | None:
    m = re.search(r"(\d{4})[-/](\d{2})[-/](\d{2})", str(s))
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None

def valj_handelse(handelser: list, ankare: dict, kandidatdatum: set[str],
                  fraga: str | None = None) -> tuple[dict | None, str]:
    """Python väljer -- inte modellen. Giltig = sessionen fanns bland de
    skickade, datumet går att tolka, och händelsen ligger inom ankarets
    tolerans. Närmast målfönstret vinner; vid lika avstånd går ett
    säkert datum före ett uppskattat. Två olika svar på exakt samma
    avstånd och samma säkerhet = tvetydigt = ingen ändring.

    Skickas `fraga` med (bara i den andra läsningen) får ordlikheten
    avgöra ett sådant lika läge: den händelse vars beskrivning delar
    flest ord med frågan väljs, om det är exakt en."""
    giltiga = []
    for h in handelser:
        if not isinstance(h, dict):
            continue
        svar = str(h.get("svar") or "").strip()
        d = _till_datum(h.get("handelsedatum"))
        sess = _till_datum(h.get("session"))
        if (not svar or d is None or sess is None
                or sess.strftime("%Y/%m/%d") not in kandidatdatum):
            continue
        saker = 0 if h.get("datum_sakert", True) else 1
        avst = _avstand(d, ankare)
        if avst > ankare["tolerans"]:
            if not saker:
                continue
            # Ett UPPSKATTAT datum ("recently", "a while ago") säger bara
            # att händelsen ligger någonstans mellan uppskattningen och
            # dagen den nämndes. Ligger målfönstret i det spannet räknas
            # avståndet som noll (plus tillägget för osäkerhet nedan) i
            # stället för att händelsen kastas (n=296: "I recently
            # walked down the aisle ..." sagt exakt en vecka före frågan,
            # modellen gissade ytterligare en vecka bakåt).
            tidigast, senast = sorted((d, sess))
            if senast < ankare["lo"]:
                avst = (ankare["lo"] - senast).days
            elif tidigast > ankare["hi"]:
                avst = (tidigast - ankare["hi"]).days
            else:
                avst = 0
            if avst + 2 > ankare["tolerans"]:
                continue
        # Ett uppskattat datum är svagare stöd än ett säkert: det räknas
        # som två dagar längre bort (n=300 i första körningen: två
        # händelser med gissat datum mitt på målet slog ut den rätta,
        # säkert daterade händelsen en dag bredvid).
        giltiga.append((avst + 2 * saker, saker, svar, h))
    if not giltiga:
        return None, "ingen händelse inom toleransen"
    giltiga.sort(key=lambda x: (x[0], x[1]))
    basta = giltiga[0]
    lika = [g for g in giltiga if g[0] == basta[0] and g[1] == basta[1]]
    if len({g[2].lower().rstrip(".") for g in lika}) > 1:
        if fraga:
            fragord = set(_ord(fraga))
            poang = {}
            for g in lika:
                text = f"{g[3].get('handelse') or ''} {g[2]}"
                nyckel = g[2].lower().rstrip(".")
                p = len(fragord & set(_ord(text)))
                if p > poang.get(nyckel, (-1, None))[0]:
                    poang[nyckel] = (p, g)
            topp = max(p for p, _ in poang.values())
            basta_svar = [g for p, g in poang.values() if p == topp]
            if len(basta_svar) == 1 and topp > 0:
                return basta_svar[0][3], (f"vald: viktat avstånd "
                                          f"{basta[0]} dagar (ordlikhet)")
        return None, "flera olika svar på samma avstånd"
    return basta[3], f"vald: viktat avstånd {basta[0]} dagar"



# ---------------------------------------------------------------------------
# 5. Vägarna
# ---------------------------------------------------------------------------
def forsok_tidsankare(kontext: str, fraga: str, fragans_datum,
                      anropa: Anropa, logg: dict | None = None
                      ) -> dict | None:
    """Sessionerna närmast måldatumet skickas. Modellen listar varje
    tänkbar händelse med när den faktiskt inträffade och vad svaret då
    vore; valj_handelse() tar den som ligger närmast.

    `logg` (steg 102): fylls med ankaret och alla händelser som
    läsningarna listade, så att dagslasning_behovs() kan se om svaret som
    till slut ges är en händelse vid fel datum."""
    ankare = tidsankare(fraga, fragans_datum)
    if ankare is None:
        return None
    kand = tidsankare_kandidater(kontext, fraga, ankare)
    if not kand:
        return None
    kandidatdatum = {s["datumstr"] for s in kand}
    raw = anropa(prompt_tidsankare(fraga, fragans_datum, ankare, kand))
    handelser = json_lista(raw)
    if handelser is None:
        return None
    vald, notering = valj_handelse(handelser, ankare, kandidatdatum)
    if logg is not None:
        logg.update({"ankare": ankare, "handelser": list(handelser),
                     "kandidatdatum": kandidatdatum})
    # En andra, bredare läsning av samma sessioner i två lägen:
    #  (a) den första hittade ingen händelse i rätt tid (inte samma sak
    #      som två lika goda: då är frågan tvetydig och lämnas till v5);
    #  (b) den första valde en säkert daterad händelse som inte ligger
    #      PÅ måldagen. Då kan en händelse den inte räknade som samma
    #      slag ligga lika nära eller närmare.
    # Händelserna från båda läsningarna vägs ihop. Ger den andra inget
    # bättre gäller den första läsningens val.
    ingen = not vald and notering == "ingen händelse inom toleransen"
    m = re.search(r"viktat avstånd (\d+) dagar", notering or "")
    bredvid = (bool(vald) and m is not None and int(m.group(1)) > 0
               and bool(vald.get("datum_sakert", True)))
    if (ingen and TIDSANKARE_ANDRA_LASNING) or \
            (bredvid and TIDSANKARE_BRED_VID_AVSTAND):
        try:
            raw2 = anropa(prompt_tidsankare_bred(fraga, fragans_datum,
                                                 ankare, kand))
        except Exception:
            # Den andra läsningen gick inte att göra. (a): vägen ger
            # inget, v5 tar över som förut. (b): första valet gäller.
            raw2 = None
        handelser2 = json_lista(raw2) if raw2 is not None else None
        if handelser2 is not None and logg is not None:
            logg["handelser"] = list(handelser) + list(handelser2)
        if handelser2 is not None:
            vald2, _ = valj_handelse(handelser + handelser2, ankare,
                                     kandidatdatum, fraga=fraga)
            if vald2:
                vald = vald2
                raw = f"{raw}\n--- andra läsningen ---\n{raw2}"
    if not vald:
        return None
    return {"svar": str(vald["svar"]).strip(), "ra": raw}


def forsok_ordning(kontext: str, fraga: str, fragans_datum,
                   anropa: Anropa, k: int = 12) -> dict | None:
    """Modellen listar händelserna med datum; Python sorterar. Vid samma
    händelsedatum avgör sessionens egen tidpunkt. Saknar någon händelse
    tolkbart datum, eller finns färre än två: None."""
    text, valda = fokuskontext(kontext, fraga, k)
    if not valda:
        return None
    raw = anropa(prompt_ordning(fraga, fragans_datum, text))
    lista = json_lista(raw)
    if lista is None:
        return None
    sessionstid = {s["datumstr"]: (s["datum"], s["tid"]) for s in valda}
    poster = []
    for h in lista:
        if not isinstance(h, dict):
            continue
        namn = str(h.get("namn") or "").strip()
        d = _till_datum(h.get("handelsedatum"))
        sess = _till_datum(h.get("session"))
        if not namn or d is None:
            return None
        nyckel = sessionstid.get(sess.strftime("%Y/%m/%d")) if sess else None
        poster.append((d, nyckel or (d, "99:99"), namn))
    if len(poster) < 2:
        return None
    poster.sort(key=lambda x: (x[0], x[1]),
                reverse=bool(_ORDNING_FALLANDE.search(fraga)))
    return {"svar": ", ".join(p[2] for p in poster), "ra": raw}


def forsok_avstaende(kontext: str, fraga: str, fragans_datum,
                     anropa: Anropa, k: int = 5) -> dict | None:
    """Läser om de k mest relevanta sessionerna när det första svaret
    var ett avstående. None om modellen fortfarande avstår."""
    text, valda = fokuskontext(kontext, fraga, k)
    if not valda:
        return None
    raw = anropa(prompt_avstaende(fraga, fragans_datum, text, len(valda)))
    svar = svarsrad(raw)
    if svar is None or _AVSTAENDE_SVAR.search(svar):
        return None
    return {"svar": summera_delar(fraga, utan_forbehall(svar)), "ra": raw}


# ---------------------------------------------------------------------------
# 6. Varningstecken: när ett svar som INTE är ett avstående ändå ska få
#    en andra bedömning av den fokuserade läsaren (steg 92)
# ---------------------------------------------------------------------------
# Vilka delar av steg 92 som är påslagna. Varje del går att stänga av
# för sig utan att röra något annat.
TIDSANKARE_ANDRA_LASNING = True       # läge (a) i forsok_tidsankare()
# Läge (b) mättes 2026-11-13 på de tre frågor det träffar (290, 294,
# 300): inget svar ändrades. Avstängt, eftersom det kostar ett anrop
# utan att ge något.
TIDSANKARE_BRED_VID_AVSTAND = False   # läge (b)
# Räknefrågor: läsaren räknar om, och gäller när den hittar FLER.
RAKNA_OM = True
# ... plus en läsning med regel D för köp-/skaffa-/ägafrågor (steg 94).
RAKNA_AGANDE = True
# ... och "how many times have I": den högsta summan är den senaste (steg 95).
RAKNA_VAXER = True
# ... och ett par räknas som ett föremål när v3 räknat det som två (steg 98).
RAKNA_PAR_SOM_ETT = True
# Avstående: läs också de sessioner CAP-Shield lämnade utanför kontexten,
# när anroparen skickar med dem (cap_svar["utelamnat_kontext"]; steg 99).
KOMPLETTERING = True
# Preferensvägen: utkastet granskas en gång mot samma sessioner.
# AVSTÄNGD. Mätt 2026-11-14 på alla 30 preferensfrågor: kontrollen
# ändrade elva svar, inget underkänt svar blev godkänt och två godkända
# (n=140, n=157) blev underkända (domaren: 21 godkända före, 19 efter).
# Den hittade inte felen den var till för (n=139, 143: "none") och
# lade mest till detaljer som tunnade ut svaret.
PREFERENS_KONTROLL = False
VARNINGSTECKEN = ("namn_saknas", "en_del_av_tva", "intervall")
# Steg 102 (2026-11-15), riktade mot enskilda frågor; se avsnitt 9.
# Räknefrågor om vad användaren har NU: regel F, "gammal" är inte borta.
RAKNA_KVAR = True
# Frågan namnger något på minst tre ord som inte finns i historiken, men
# en del av det gör: kontrollera premissen.
PREMISSKONTROLL = True
# Tidsankaret (helg/veckodag) hittade bara en händelse vid ett annat
# datum, och svaret är den händelsen: läs sessionerna från rätt dagar.
TIDSANKARE_DAGSLASNING = True

# "X nämns inte", "nämner Y, inte X", "no mention of X" ...
_INTE_NAMNT = re.compile(
    r"nämns inte|nämns ej|inte nämn\w*|nämns aldrig|aldrig nämn\w*"
    r"|omnämns inte|\binget? [^.;\n]{0,60}nämns\b"
    r"|\bing(?:en|a) [^.;\n]{0,60}nämns\b"
    r"|\bnämner [^.;\n]{0,80}\binte\b|förekommer inte|finns inte med"
    r"|not mentioned|no mention|never mention\w*|isn't mentioned"
    r"|(?:does|did|do)(?:n't| not) mention"
    r"|\bmention\w* [^.;\n]{0,80}\bnot\b", re.IGNORECASE)
_EGENNAMN = re.compile(r"\b[A-Z][A-Za-z]+(?:[-'’][A-Za-z]+)*\b")
_MENINGSSLUT = re.compile(r"(?<=[.;!?])\s+|\n+")
# Frågor om skillnaden mellan två belopp/tal.
_SKILLNADSFRAGA = re.compile(
    r"\binstead of\b|\bcompared (?:to|with)\b|\bdifference\b|\bsave\b"
    r"|\bhow (?:much|many) (?:more|less|fewer|cheaper|faster|longer"
    r"|older|younger|earlier|later)\b", re.IGNORECASE)
# "$30–$40", "10-12 hours"; inte "70-200mm" (en modellbeteckning).
_TALINTERVALL = re.compile(
    r"\d\s*[–—-]\s*[$¥€£]?\s*\d[\d,.]*(?![\d,.]*[A-Za-z])")
_SUMMAVAGAR = ("v5-summa-programmatisk", "v6-summa-programmatisk")
# Frågan gäller en avgränsad period ("last week", "in April"). Då är en
# del som inte förekom under perioden noll, inte okänd (n=95: "jogging
# and yoga ... last week", facit räknar bara joggingen). Utan period
# förutsätter frågan att båda delarna finns (n=131, n=229).
_PERIOD_I_FRAGAN = re.compile(
    r"\b(?:last|past|this|previous|next)\s+(?:\w+\s+)?(?:day|week|weekend"
    r"|month|year)s?\b|\bin (?:january|february|march|april|may|june|july"
    r"|august|september|october|november|december)\b|\byesterday\b"
    r"|\btoday\b|\bsince\b|\bso far\b", re.IGNORECASE)


# Steg 103 (2026-11-16): namnet måste stå nära själva negationen, inte
# bara någonstans i samma mening. LoCoMo: "I april nämner James att han
# blev förälskad ... men att han inte tog kontakt med henne" matchade
# "nämner ... inte" fast inget namn sades saknas, och omläsningen gjorde
# ett rätt "No." till ett avstående. På LongMemEval ger regeln samma
# träffar som förut (361: "inget köp från Peter nämns", 440: "nämner
# Harajuku, inte Shinjuku").
_NEGATION = re.compile(
    r"\b(?:inte|ej|aldrig|ingen|inget|inga|not|no|never)\b|n't\b",
    re.IGNORECASE)
_NAMN_NEGATION_AVSTAND = 30


def _namn_nara_negation(mening: str, namn: set[str]) -> bool:
    for t in _INTE_NAMNT.finditer(mening):
        neg = [(g.start() + t.start(), g.end() + t.start())
               for g in _NEGATION.finditer(t.group(0))] or [(t.start(), t.end())]
        for n in namn:
            for x in re.finditer(r"\b" + re.escape(n) + r"\b", mening):
                if any(max(a - x.end(), x.start() - b, 0)
                       <= _NAMN_NEGATION_AVSTAND for a, b in neg):
                    return True
    return False


def _egennamn_i_fragan(fraga: str) -> set[str]:
    """Ord med stor bokstav som inte står först i en mening: namn på
    platser, personer, företag, produkter."""
    namn = set()
    for mening in re.split(r"(?<=[.?!])\s+", (fraga or "").strip()):
        ord_ = _EGENNAMN.findall(mening)
        forsta = re.match(r"\W*([A-Za-z]+)", mening)
        for i, w in enumerate(ord_):
            if i == 0 and forsta and forsta.group(1) == w:
                continue
            if w in ("I", "I'm", "I've", "I'd", "I'll"):
                continue
            namn.add(w)
    return namn


def varningstecken(fraga: str, resultat: dict) -> str | None:
    """Tre tecken på att ett svar byggts på något användaren aldrig sagt.
    Returnerar tecknets namn eller None. Ren Python.

    namn_saknas    modellens EGEN motivering säger att ett namn som
                   frågan nämner inte finns i materialet ("Kandidaterna
                   nämner Harajuku, inte Shinjuku") men svarar ändå.
    en_del_av_tva  summavägen hittade ett enda delbelopp fast frågan
                   binder ihop två saker med "and" (och inte gäller en
                   avgränsad period, se _PERIOD_I_FRAGAN).
    intervall      frågan gäller skillnaden mellan två belopp, men
                   svaret är ett intervall ("About $30–$40"): användarens
                   egna uppgifter är enstaka tal, intervall kommer från
                   assistentens allmänna prisuppgifter.

    Tecknet avgör ingenting själv. Det skickar frågan till las_om(),
    som läser de mest relevanta sessionerna och antingen svarar eller
    avstår."""
    svar = str((resultat or {}).get("svar") or "")
    vag = str((resultat or {}).get("vag") or "")
    ra = str((resultat or {}).get("svar_ra") or "")
    if not svar or ar_avstaende(svar):
        return None
    if "en_del_av_tva" in VARNINGSTECKEN and vag in _SUMMAVAGAR \
            and re.search(r"\band\b", fraga or "", re.IGNORECASE) \
            and not _PERIOD_I_FRAGAN.search(fraga or ""):
        poster = json_lista(ra) or []
        tal = [p for p in poster if isinstance(p, dict)
               and isinstance(p.get("belopp"), (int, float))]
        if len(tal) == 1:
            return "en_del_av_tva"
    if "namn_saknas" in VARNINGSTECKEN and vag.startswith(("v3", "v6-tidigare")):
        namn = _egennamn_i_fragan(fraga)
        if namn:
            for mening in _MENINGSSLUT.split(ra):
                if _namn_nara_negation(mening, namn):
                    return "namn_saknas"
    if "intervall" in VARNINGSTECKEN and _SKILLNADSFRAGA.search(fraga or "") \
            and _TALINTERVALL.search(svar):
        return "intervall"
    return None


AVSTAENDE_TEXT = "Not available in the provided selection."


def las_om(kontext: str, fraga: str, fragans_datum, anropa: Anropa,
           k: int = 5) -> dict | None:
    """Samma omläsning som forsok_avstaende() (samma prompt, samma k),
    men returnerar även ett avstående:
    {"svar": ..., "ra": ..., "avstar": bool}. None om det inte finns
    sessioner att läsa eller om svaret saknar SVAR-rad."""
    text, valda = fokuskontext(kontext, fraga, k)
    if not valda:
        return None
    raw = anropa(prompt_avstaende(fraga, fragans_datum, text, len(valda)))
    svar = svarsrad(raw)
    if svar is None:
        return None
    if _AVSTAENDE_SVAR.search(svar):
        return {"svar": AVSTAENDE_TEXT, "ra": raw, "avstar": True}
    return {"svar": summera_delar(fraga, utan_forbehall(svar)), "ra": raw,
            "avstar": False}


# ---------------------------------------------------------------------------
# 7. Räknefrågor: läsaren räknar om (steg 92, mätt 2026-11-13)
# ---------------------------------------------------------------------------
# Samma klassificerare som mättes i steg76 och i mätningen 2026-11-13.
# Anroparen kontrollerar dessutom att frågan inte redan hör till en av
# v5:s egna vägar (summa, ordning, räkning, jämförelse).
# "how many times" hör inte hit. Det prövades 2026-11-14 på de fem
# frågor det skulle lägga till (90, 115, 392, 410, 433): läsaren hittade
# inte fler i någon av dem, så det hade bara kostat ett anrop per fråga.
_RAKNA_BRED = re.compile(
    r"\bhow many\b(?!\s+(hours?|minutes?|days?|weeks?|months?|years?"
    r"|dollars?|times?|\$)).{0,60}\b(?:did|have|has|do) i\b", re.IGNORECASE)
_RAKNA_UTESLUT = re.compile(
    r"\b(left|remaining)\b|\bneed(?:s|ed)? to\b.{0,40}\b(?:redeem|reach"
    r"|unlock)\b|\b(?:just started|just began|when i started|when i began)\b",
    re.IGNORECASE)
_TALORD = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
           "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
           "eleven": 11, "twelve": 12}


# "How many times have I ...": en löpande summa, som bara kan växa
# (steg 95). Inte "how many times did I ... last week", som gäller en
# period och kan vara mindre än förut.
_GANGER_HITTILLS = re.compile(r"\bhow many times have i\b", re.IGNORECASE)


def ar_rakningsfraga(fraga: str) -> bool:
    if _GANGER_HITTILLS.search(fraga or ""):
        return True
    return (bool(_RAKNA_BRED.search(fraga or ""))
            and not _RAKNA_UTESLUT.search(fraga or ""))


def forsta_tal(text) -> int | None:
    m = re.search(r"\b(\d+)\b|\b(" + "|".join(_TALORD) + r")\b",
                  str(text or "").lower())
    if not m:
        return None
    return int(m.group(1)) if m.group(1) else _TALORD[m.group(2)]


# Ägande räknas som införskaffande (steg 94). I n=123 räknade både v3
# och läsaren bort "I got my Tame Impala vinyl signed ... I'm looking to
# add to my collection", eftersom köpet aldrig nämns. Något användaren
# äger och kallar sitt har hon skaffat. Regeln läggs bara i räknevägens
# prompt; prompt_avstaende() är oförändrad för omläsningen.
_RAKNA_AGANDE_REGEL = (
    "RULE D - counting things the user has. When the question asks how "
    "many things the user bought, purchased, acquired, downloaded, got "
    "or owns, an item the user refers to as their own (\"my vinyl\", "
    "\"in my collection\", \"I got my X signed\") counts as acquired "
    "even if the purchase itself is never mentioned: if they own it, "
    "they acquired it at some point. Leave such an item out only when "
    "the user says it came to them in a way the question excludes (for "
    "example a gift, when the question asks what they bought), or that "
    "they do not have it yet. Each distinct item counts once.\n\n")
_RAKNA_VAXER_REGEL = (
    "RULE E - totals that only grow. The question asks how many times "
    "the user has done something so far. Such a total can only grow. "
    "If the user states different totals in different places, the "
    "highest one is the most recent, whatever order the session "
    "headers suggest; answer with it.\n\n")
_RAKNA_MARKOR = "Write a short reasoning (2-5 lines)"
# Regel D gäller bara frågor om att köpa, skaffa, ladda ner eller äga.
# Mätt 2026-11-14 på alla 53: på övriga frågor gav prompten bara andra
# tal (n=93 fem visningar i stället för fyra, n=103 två hörapparater som
# två enheter), aldrig ett bättre svar.
_KOP_FRAGA = re.compile(
    r"\b(purchas\w*|bought|buy|acquir\w*|download\w*|own|owned)\b",
    re.IGNORECASE)

# Regel F (steg 102): det användaren kallar "gammalt" har hon kvar tills
# hon säger att det är borta. n=84: "My old tank was a 5-gallon one ...
# I've since set up a new 20-gallon community tank", och i samma session
# "I have a 5-gallon tank" och "use some of the beneficial bacteria from
# my old tank to seed the new one". Både v3 och läsaren räknade bort det
# gamla akvariet. Gäller bara frågor om vad användaren har eller äger NU
# ("How many X do I currently have/own"); inte följare, som är ett tal.
_RAKNA_KVAR_REGEL = (
    "RULE F - things the user still has. The question asks what the "
    "user has now. Something the user calls their \"old\", "
    "\"previous\" or \"first\" one is still theirs unless they say it "
    "is gone: sold, given away, thrown out, returned, cancelled, broken "
    "beyond use, or (for an animal or plant) that it died. Getting a new "
    "one, or calling the earlier one \"old\", does not by itself mean "
    "the earlier one is gone. Each distinct item counts once.\n\n")
_INNEHAV_NU = re.compile(
    r"\bhow many\b(?:(?!\bfollowers?\b)[^?])*?\bdo i\b[^?]*\b(?:have|own)\b",
    re.IGNORECASE)
_NU_ORD = re.compile(r"\b(?:currently|still|now|at the moment)\b",
                     re.IGNORECASE)


def ar_innehavsfraga(fraga: str) -> bool:
    """"How many X do I currently have/own" (inte följare)."""
    return bool(_INNEHAV_NU.search(fraga or "")
                and _NU_ORD.search(fraga or ""))


def prompt_rakning(fraga: str, fragans_datum: str, text: str, antal: int,
                   regler: str, prefix: str = "COUNTING. ") -> str:
    """Läsarens prompt med en eller flera regler (D, E) tillagda före
    svarsinstruktionen. Börjar med en egen första mening så att den går
    att skilja från omläsningens prompt."""
    bas = prompt_avstaende(fraga, fragans_datum, text, antal)
    if _RAKNA_MARKOR not in bas:
        raise ValueError("prompt_avstaende() har ändrats")
    return prefix + bas.replace(_RAKNA_MARKOR, regler + _RAKNA_MARKOR, 1)


# Ett par räknas som ett föremål (steg 98): ett par örhängen är ett
# smycke, ett par stövlar ett plagg. Facit räknar så (n=103 hörapparater,
# n=107 örhängen), och så räknar man i vardagligt tal. Känns igen på att
# det första svarets EGEN motivering säger att ett par räknats som två
# ("örhängena är ett par, alltså två smycken").
_PAR_SOM_TVA = re.compile(
    r"\bpar(?:et)?\b[^.\n]{0,25}\b(?:alltså|dvs\.?|räknas som|blir|=)\s*"
    r"(?:två|2)\b"
    r"|\bpairs?\b[^.\n]{0,25}\b(?:so|i\.e\.|counts? as|count(?:ed|ing)? as"
    r"|=|makes?)\s*(?:two|2)\b", re.IGNORECASE)


def rakna_om(kontext: str, fraga: str, fragans_datum, anropa: Anropa,
             forsta_svar, k: int = 8, forsta_ra: str | None = None
             ) -> dict | None:
    """Läsaren får samma räknefråga med de k mest relevanta sessionerna.
    Dess svar gäller bara när den hittar FLER än det första svaret: den
    ser färre sessioner än den första läsningen, så räknar den ändå
    fler har den första uteslutit något som hör dit (n=167: v3 strök
    tre arvegods för att de kallades "vintage" och inte "antique").
    Räknar den färre har den oftast bara sett mindre.

    Läsningar:
      * "how many times have I": en läsning med regel D och E (summan
        kan bara växa, den högsta är den senaste);
      * övriga: en läsning med omläsningens prompt, och för frågor om
        att köpa, skaffa, ladda ner eller äga en läsning till med
        regel D (det användaren äger har hon skaffat). En enda läsning
        är brusig på räknefrågor (n=167 gav "Five" i den ena och
        "2 antique items" i den andra på samma material), så det
        högsta talet från läsningarna jämförs med det första svaret.

    Undantag (steg 98): säger det första svarets motivering att ett par
    räknats som två, gäller läsarens svar också när det är exakt ett
    lägre -- det paret räknat som ett föremål.

    Mätt 2026-11-14 på de 56 räknefrågor som v3 besvarar: byter fyra svar
    (n=107, n=123, n=167, n=392, alla till rätt) och rör inget annat. Returnerar
    {"svar", "ra"} eller None."""
    text, valda = fokuskontext(kontext, fraga, k)
    if not valda:
        return None
    if RAKNA_VAXER and _GANGER_HITTILLS.search(fraga or ""):
        # Regel D följer med; det var med den prompten 392/410/433
        # mättes 2026-11-14 (D gör ingen skillnad för den frågeformen).
        prompter = [prompt_rakning(fraga, fragans_datum, text, len(valda),
                                   _RAKNA_AGANDE_REGEL + _RAKNA_VAXER_REGEL)]
    else:
        prompter = [prompt_avstaende(fraga, fragans_datum, text, len(valda))]
        if RAKNA_AGANDE and _KOP_FRAGA.search(fraga or ""):
            prompter.append(prompt_rakning(fraga, fragans_datum, text,
                                           len(valda), _RAKNA_AGANDE_REGEL))
        if RAKNA_KVAR and ar_innehavsfraga(fraga):
            prompter.append(prompt_rakning(fraga, fragans_datum, text,
                                           len(valda), _RAKNA_KVAR_REGEL,
                                           prefix="COUNTING, STILL HELD. "))
    gammalt = forsta_tal(forsta_svar)
    if gammalt is None:
        return None
    par_som_tva = RAKNA_PAR_SOM_ETT and bool(_PAR_SOM_TVA.search(forsta_ra or ""))
    basta = None
    par_svar = None
    for prompt in prompter:
        try:
            raw = anropa(prompt)
        except Exception:
            continue
        svar = svarsrad(raw)
        if svar is None or _AVSTAENDE_SVAR.search(svar):
            continue
        svar = summera_delar(fraga, utan_forbehall(svar))
        nytt = forsta_tal(svar)
        if nytt is not None and nytt > gammalt and \
                (basta is None or nytt > basta[0]):
            basta = (nytt, svar, raw)
        if par_som_tva and nytt == gammalt - 1 and par_svar is None:
            par_svar = (nytt, svar, raw)
    if basta is None:
        basta = par_svar
    if basta is None:
        return None
    return {"svar": basta[1], "ra": basta[2]}


# ---------------------------------------------------------------------------
# 8. Kompletterande läsning (steg 99)
# ---------------------------------------------------------------------------
# CAP-Shield tar med de ~30 sessioner dess sökning rankar högst (av ~48).
# En bevissession som rankas lägre når aldrig modellen (n=213: "do you
# think 32 is considered young or old?" rankas 46 av 47, och utan den går
# mormoderns ålder inte att jämföra). När svaret ändå blir ett avstående
# läses därför de utelämnade sessionerna, tillsammans med de mest
# relevanta i kontexten (svaret kan kräva uppgifter från båda).
# Version 2 (2026-11-14). Version 1 lät läsaren se sessionen med "do you
# think 32 is considered young or old?" i n=213, men den tog uppgiften för
# assistentens, eftersom kontexten saknar talarangivelse (regel A räknar
# bara användarens egna uppgifter). De utelämnade sessionerna skickas
# därför med talarangivelse (USER: / ASSISTANT:), och inledningen säger det.
_KOMPLETTERING_INLEDNING = (
    "SUPPLEMENTED READING. The sessions below also include past "
    "conversations that were left out of the first reading. In those, "
    "every message starts with USER: or ASSISTANT:, so you can see who "
    "said what; a number or fact in a USER: message is the user's own "
    "information.\n\n")


def prompt_komplettering(fraga: str, fragans_datum: str, text: str,
                         antal: int) -> str:
    """Läsarens prompt (prompt_avstaende, oförändrad) med en inledande
    mening som säger att utelämnade sessioner är med."""
    return _KOMPLETTERING_INLEDNING + prompt_avstaende(
        fraga, fragans_datum, text, antal)


def utelamnat_block(datum: str, turer: list) -> str:
    """En utelämnad session i det format las_med_utelamnat() väntar sig:
    rubriken som i kontexten, sedan varje tur på egen rad med
    talarangivelse. turer = [{"role": "user"|"assistant", "content": ...}].
    Så ska CAP-Shield bygga cap_svar["utelamnat_kontext"] (sessionerna
    åtskilda av en tom rad)."""
    rader = []
    for t in turer:
        roll = "USER" if str(t.get("role", "")).lower() == "user" else "ASSISTANT"
        rader.append(f"{roll}: {t.get('content', '')}")
    return f"--- Session {datum} ---\n" + "\n".join(rader)


def las_med_utelamnat(kontext: str, utelamnat: str, fraga: str,
                      fragans_datum, anropa: Anropa, k: int = 5,
                      max_tecken: int = 240_000) -> dict | None:
    """De k mest relevanta sessionerna i kontexten plus de utelämnade,
    i tidsordning. Blir texten längre än max_tecken tas de utelämnade
    med i BM25-ordning tills taket nås. Returnerar {"svar", "ra"}, eller
    None om det inte finns något utelämnat eller läsaren fortfarande
    avstår."""
    _, valda = fokuskontext(kontext, fraga, k)
    ute = dela_sessioner(utelamnat or "")
    if not ute:
        return None
    tecken = sum(len(s["block"]) for s in valda)
    med = list(valda)
    for _, sess in bm25_ranka(ute, fraga):
        if tecken + len(sess["block"]) > max_tecken:
            continue
        med.append(sess)
        tecken += len(sess["block"])
    if len(med) == len(valda):
        return None
    med.sort(key=lambda x: (x["datum"], x["tid"]))
    raw = anropa(prompt_komplettering(
        fraga, fragans_datum, "\n\n".join(x["block"] for x in med), len(med)))
    svar = svarsrad(raw)
    if svar is None or _AVSTAENDE_SVAR.search(svar):
        return None
    return {"svar": summera_delar(fraga, utan_forbehall(svar)), "ra": raw}


def forsok_preferens(kontext: str, fraga: str, fragans_datum,
                     anropa: Anropa) -> dict | None:
    """Ett råd som bygger på vad användaren berättat om sig själv."""
    if not dela_sessioner(kontext):
        return None
    text = preferenskontext(kontext, fraga)
    raw = anropa(prompt_preferens(fraga, fragans_datum, text))
    svar = svarsrad(raw)
    if svar is None:
        return None
    if PREFERENS_KONTROLL:
        # Utkastet granskas mot samma sessioner. Går kontrollen inte att
        # göra, eller saknar dess svar SVAR-rad, gäller utkastet.
        try:
            raw2 = anropa(prompt_preferens_kontroll(fraga, fragans_datum,
                                                    text, svar))
        except Exception:
            raw2 = None
        svar2 = svarsrad(raw2) if raw2 else None
        if svar2:
            return {"svar": svar2, "ra": f"{raw}\n--- kontroll ---\n{raw2}"}
    return {"svar": svar, "ra": raw}



# ---------------------------------------------------------------------------
# 9. Steg 102 (2026-11-15): premisskontroll och dagsläsning
# ---------------------------------------------------------------------------
# BRASKLAPP. Båda är skrivna för en enda fråga var (n=438 respektive
# n=295). På de 500 träffar premisskontrollen bara n=438 och
# dagsläsningen bara n=64 och n=295. De säger alltså inget om hur
# reglerna beter sig på andra frågor; det får provet på ojusterade
# frågor (steg 4) visa.

_FRAS_STOPP = {"I", "How", "What", "Which", "When", "Where", "Who", "Why",
               "Did", "Do", "Does", "Can", "Could", "Would", "Should", "Is",
               "Was", "Were", "Are", "Am", "My", "The", "A", "An", "In",
               "On", "For", "Have", "Has", "Had", "If", "After", "Before",
               "Since"}
_FOGORD = {"of", "the", "de", "and"}


def versala_fraser(fraga: str) -> list[list[str]]:
    """Följder om minst tre ord med versal (eller siffra efter ett sådant
    ord) i frågan: "Software Engineer Manager", "Canon EOS 80D". Ord som
    "of" och "the" får ingå inne i en följd."""
    ut = []
    for mening in re.split(r"(?<=[.?!])\s+|[()\[\]\"“”,;:]", fraga or ""):
        cur: list[str] = []
        for w in re.findall(r"[A-Za-z0-9][\w&-]*", mening) + ["x"]:
            if (w[:1].isupper() and w not in _FRAS_STOPP) or (
                    cur and w[:1].isdigit()):
                cur.append(w)
            elif w.lower() in ("of", "the", "de") and cur:
                cur.append(w)
            else:
                while cur and cur[-1].lower() in _FOGORD:
                    cur.pop()
                if len(cur) >= 3:
                    ut.append(cur)
                cur = []
    return ut


def fras_variant(fraga: str, text: str) -> tuple[str, str] | None:
    """(frasen i frågan, närmaste formulering i texten) när en fras på
    minst tre ord inte finns i texten men en del av den, minst två ord i
    följd, gör det. n=438: "Software Engineer Manager" finns inte, men
    "as Senior Software Engineer" gör. Ren Python. Mätt 2026-11-15 på de
    500 frysta kontexterna: träffar bara n=438."""
    t = (text or "").lower()
    for ord_ in versala_fraser(fraga):
        fras = " ".join(ord_)
        if fras.lower() in t:
            continue
        for langd in range(len(ord_) - 1, 1, -1):
            for i in range(len(ord_) - langd + 1):
                del_ = " ".join(ord_[i:i + langd]).lower()
                m = re.search(r"(?:\b[\w-]+\s+){0,2}" + re.escape(del_)
                              + r"(?:\s+[\w-]+){0,2}", t)
                if m:
                    return fras, m.group(0)
    return None


def prompt_premiss(fraga: str, fragans_datum: str, text: str, antal: int,
                   fras: str, variant: str) -> str:
    bas = _datum_ur(fragans_datum)
    return (
        "PREMISE CHECK. You answer a question about what a user told an "
        "AI assistant in earlier conversations.\n"
        f"Below are the {antal} past conversation sessions most relevant "
        "to the question, in chronological order. Each starts with a "
        "header \"--- Session YYYY/MM/DD (Day) HH:MM ---\" that tells "
        "when that conversation took place. Within a session the user's "
        "messages and the assistant's replies alternate, and the user "
        "always speaks first.\n"
        f"The question was asked on {bas.isoformat()} "
        f"({_VECKODAGAR[bas.weekday()]}).\n\n"
        f"The question refers to \"{fras}\". Those words never occur "
        "together anywhere in the conversation history. The closest "
        f"wording in the history is: \"... {variant} ...\".\n\n"
        f"First decide whether \"{fras}\" and what the user actually "
        "talked about are the same thing. They are the same only if the "
        "difference is a spelling variant, an abbreviation or an obvious "
        "synonym. A different title, role, model, product, place or name "
        "that merely shares some of the words is NOT the same thing: then "
        "the question rests on something the user never said, and the "
        "right response is that the information is not available.\n"
        "If they are the same thing, answer the question from the user's "
        "own messages.\n\n"
        "Write a short reasoning (2-4 lines), then a final line that "
        "starts with \"SVAR:\" followed by the answer, or by \"Not "
        "available in the provided selection.\"\n\n"
        f"QUESTION: {fraga}\n\nSESSIONS:\n{text}\n")


def premisskontroll(kontext: str, fraga: str, fragans_datum,
                    anropa: Anropa, fras: str, variant: str,
                    k: int = 5) -> dict | None:
    """{"svar": avstående, "ra"} när modellen bedömer att frågan bygger
    på något användaren aldrig sagt; None annars (då gäller det första
    svaret)."""
    text, valda = fokuskontext(kontext, fraga, k)
    if not valda:
        return None
    raw = anropa(prompt_premiss(fraga, fragans_datum, text, len(valda),
                                fras, variant))
    svar = svarsrad(raw)
    if svar is None or not _AVSTAENDE_SVAR.search(svar):
        return None
    return {"svar": AVSTAENDE_TEXT, "ra": raw}


def _normsvar(s) -> str:
    s = re.sub(r"[^\w\s]", " ", str(s or "").lower())
    s = re.sub(r"\b(?:the|a|an|my|your)\b", " ", s)
    return " ".join(s.split())


def dagslasning_behovs(logg: dict, svar) -> dict | None:
    """Den händelse vid fel datum som svaret bygger på, eller None.

    Villkor: ankaret är exakt (helg eller veckodag); ingen listad
    händelse ligger inom toleransen; svaret är detsamma som en listad
    händelses svar, och den händelsen har ett säkert datum utanför
    målfönstret. Då vet vi att svaret gäller en annan dag än frågan.
    n=295: "the past weekend" = 18-19 mars, men mountainbiken lagades
    onsdagen den 15:e."""
    ankare = (logg or {}).get("ankare")
    handelser = (logg or {}).get("handelser") or []
    if not ankare or ankare.get("typ") not in ("helg", "veckodag"):
        return None
    vald, notering = valj_handelse(handelser, ankare,
                                   logg.get("kandidatdatum") or set())
    if vald is not None or notering != "ingen händelse inom toleransen":
        return None
    s = _normsvar(svar)
    if not s:
        return None
    for h in handelser:
        if not isinstance(h, dict) or not h.get("datum_sakert", True):
            continue
        d = _till_datum(h.get("handelsedatum"))
        hs = _normsvar(h.get("svar"))
        if d is None or not hs:
            continue
        if _avstand(d, ankare) > ankare["tolerans"] and (hs in s or s in hs):
            return h
    return None


def prompt_dagslasning(fraga: str, fragans_datum: str, ankare: dict,
                       handelse: dict, text: str) -> str:
    bas = _datum_ur(fragans_datum)
    return (
        "DAY READING. You answer a question about what a user told an AI "
        "assistant in earlier conversations.\n"
        f"The question was asked on {bas.isoformat()} "
        f"({_VECKODAGAR[bas.weekday()]}). It refers to something that "
        f"happened at a specific time: {ankare['text']}.\n"
        "An earlier reading found only one matching event, and it "
        f"happened on another date: \"{handelse.get('handelse')}\" on "
        f"{handelse.get('handelsedatum')}. That is outside the time the "
        "question asks about, so it is probably not the event meant.\n\n"
        "Below are ALL the conversation sessions from the days the "
        "question asks about. Each starts with a header \"--- Session "
        "YYYY/MM/DD (Day) HH:MM ---\" that tells when that conversation "
        "took place. Within a session the user's messages and the "
        "assistant's replies alternate, and the user always speaks "
        "first.\n\n"
        "TASK. Find what the USER reports doing on those days that the "
        "question asks about. Read the question's description loosely: "
        "an activity of a closely related kind, involving the same sort "
        "of thing, counts even when the user used another verb or a more "
        "specific word than the question does. Something the user says "
        "they did or decided to do \"today\" happened on the date of "
        "that session. Something the user only plans for a later day "
        "does not count. If nothing the user did on those days fits the "
        "question, say so.\n\n"
        "Write a short reasoning (2-4 lines), then a final line that "
        "starts with \"SVAR:\" followed by a short answer, or by \"Not "
        "available in the provided selection.\"\n\n"
        f"QUESTION: {fraga}\n\nSESSIONS:\n{text}\n")


def las_dagarna(kontext: str, fraga: str, fragans_datum, anropa: Anropa,
                logg: dict, handelse: dict,
                max_tecken: int = 160_000) -> dict | None:
    """Läser sessionerna från målfönstrets dagar. {"svar", "ra"}, eller
    None om det inte finns några sådana sessioner eller modellen avstår
    (då gäller det första svaret)."""
    ankare = logg["ankare"]
    sessioner = [s for s in dela_sessioner(kontext)
                 if ankare["lo"] <= s["datum"] <= ankare["hi"]]
    if not sessioner:
        return None
    rang = {s["idx"]: i for i, (_, s) in
            enumerate(bm25_ranka(sessioner, fraga))}
    valda, tecken = [], 0
    for s in sorted(sessioner, key=lambda s: rang[s["idx"]]):
        if valda and tecken + len(s["block"]) > max_tecken:
            continue
        valda.append(s)
        tecken += len(s["block"])
    valda.sort(key=lambda s: (s["datum"], s["tid"]))
    raw = anropa(prompt_dagslasning(fraga, fragans_datum, ankare, handelse,
                                    "\n\n".join(s["block"] for s in valda)))
    svar = svarsrad(raw)
    if svar is None or _AVSTAENDE_SVAR.search(svar):
        return None
    return {"svar": utan_forbehall(svar), "ra": raw}
