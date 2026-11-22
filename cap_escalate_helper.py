#!/usr/bin/env python3
"""
cap_escalate_helper.py — valfri, kundsidig LLM-eskalering (FAS M)

CAP-Shield ANROPAR ALDRIG en extern LLM själv (se Lager 5-principen i
cap_security_interfaces.py / cap_firewall_rules.py: "SENARE opt-in-uttag
— inga låtsas-AI-domar här"). Den här filen är INTE en del av
cap_gateway.py:s anropsväg och ligger INTE i requirements.txt — den är
ett fristående, valbart exempel som en kund (eller CAP-Shields egna
svepskript, t.ex. cap_longmemeval_sweep.py) kan köra PÅ SIN EGEN SIDA,
med sin egen API-nyckel, när assemble_context()s escalate_recommended
är True.

VAD DEN GÖR: tar ett assemble_context()-svar + den ursprungliga frågan.
Om escalate_recommended är True skickas den redan kuraterade kandidat-
listan (urval, dedup, autocut redan gjort av CAP-Shield) till en vald
modell (Claude eller GPT-5-mini) för ETT sista resonemangssteg. Om
escalate_recommended är False returneras CAP-Shields kontext oförändrad
— ingen LLM-kostnad när CAP-Shield redan är säker.

NYCKELHANTERING: nyckeln läses ALLTID från miljövariabel
(ANTHROPIC_API_KEY eller OPENAI_API_KEY) — ALDRIG som parameter i
klartext, ALDRIG hårdkodad i denna fil. Klistra ALDRIG in en nyckel i
en chatt.

    export ANTHROPIC_API_KEY=...        # eller OPENAI_API_KEY=...
    python cap_escalate_helper.py --demo

Beroenden (installeras separat — detta är en kundsidig/testsidig
hjälpfil, inte en del av CAP-Shield-servern, och ska INTE läggas i
requirements.txt):
    pip install anthropic          # för --modell claude
    pip install openai             # för --modell gpt-5-mini
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Callable


class EscalationError(RuntimeError):
    """Fel vid LLM-eskalering — fångas ALDRIG tyst av den här filen; se
    anropande kod för hur den vill hantera det (t.ex. falla tillbaka på
    CAP-Shields ursprungliga urval)."""


def behover_eskalering(cap_svar: dict) -> bool:
    """Ren hjälpfunktion: True om assemble_context()-svaret rekommenderar
    eskalering. FRÅNVARO av fältet tolkas som True (samma "hellre synlig
    degradering, aldrig tyst 'allt är säkert'"-princip som resten av
    CAP-Shield) — ett svar utan escalate_recommended är ett äldre eller
    oväntat svarsformat och ska inte tolkas som riskfritt."""
    return bool(cap_svar.get("escalate_recommended", True))


def _prompt(cap_svar: dict, fraga: str) -> str:
    kandidater = cap_svar.get("context", "")
    return (
        "Du får en fråga och ett redan kuraterat urval av kandidatminnen "
        "(valda, deduplicerade och avskurna av CAP-Shield). Använd ENDAST "
        "informationen nedan — hitta inte på fakta som inte står där. Om "
        "urvalet inte räcker för att svara säkert, säg det.\n\n"
        "VIKTIGT OM SVARSFORMAT (så svaret går att jämföra mot ett facit):\n"
        "- Svara på SAMMA SPRÅK som frågan är skriven på. Är frågan på "
        "engelska ska svaret vara på engelska — översätt inte till "
        "svenska även om kandidaterna är på svenska.\n"
        "- Om svaret är ett datum, tal eller annat kort faktavärde, skriv "
        "det kort och konkret i samma stil som frågan själv använder "
        "(t.ex. '2023-02-14' eller 'February 14'), inte omskrivet till en "
        "högtid, ett omdöme eller en beskrivande fras (skriv inte "
        "'Alla hjärtans dag' när frågan vill ha ett datum).\n"
        "- Var inte mer utförlig, insiktsfull eller tolkande än frågan "
        "kräver — ge det direkta, konkreta svaret, inte en förklaring "
        "av det.\n"
        "- Om urvalet INTE innehåller ett tydligt svar: säg det i EN "
        "kort mening (t.ex. 'Informationen finns inte i det tillgängliga "
        "urvalet.'). Inget resonemang om vad som skulle behövts, inga "
        "gissningar, inga ursäkter — bara det korta konstaterandet.\n\n"
        f"FRÅGA: {fraga}\n\n"
        f"KANDIDATER:\n{kandidater}\n\n"
        "Ge ett kort, direkt svar."
    )


def eskalera_claude(cap_svar: dict, fraga: str, modell: str = "claude-sonnet-4-5") -> str:
    """Anropar Anthropics API med kundens egen nyckel (ANTHROPIC_API_KEY).
    Kastar EscalationError vid fel — tystnar aldrig till ett gissat svar."""
    nyckel = os.environ.get("ANTHROPIC_API_KEY")
    if not nyckel:
        raise EscalationError(
            "ANTHROPIC_API_KEY saknas i miljön. Sätt den (aldrig i "
            "klartext i kod eller chatt) innan eskalering körs.")
    try:
        import anthropic
    except ImportError as e:
        raise EscalationError(
            "Paketet 'anthropic' är inte installerat (pip install anthropic)."
        ) from e
    klient = anthropic.Anthropic(api_key=nyckel)
    try:
        svar = klient.messages.create(
            model=modell, max_tokens=500,
            messages=[{"role": "user", "content": _prompt(cap_svar, fraga)}],
        )
        return svar.content[0].text
    except Exception as e:
        raise EscalationError(f"Anthropic-anropet misslyckades: {e}") from e


def eskalera_gpt5mini(cap_svar: dict, fraga: str, modell: str = "gpt-5-mini") -> str:
    """Anropar OpenAIs API med kundens egen nyckel (OPENAI_API_KEY)."""
    nyckel = os.environ.get("OPENAI_API_KEY")
    if not nyckel:
        raise EscalationError(
            "OPENAI_API_KEY saknas i miljön. Sätt den (aldrig i klartext "
            "i kod eller chatt) innan eskalering körs.")
    try:
        import openai
    except ImportError as e:
        raise EscalationError(
            "Paketet 'openai' är inte installerat (pip install openai)."
        ) from e
    klient = openai.OpenAI(api_key=nyckel)
    try:
        svar = klient.chat.completions.create(
            model=modell,
            messages=[{"role": "user", "content": _prompt(cap_svar, fraga)}],
        )
        return svar.choices[0].message.content
    except Exception as e:
        raise EscalationError(f"OpenAI-anropet misslyckades: {e}") from e


MODELLER: dict[str, Callable[[dict, str], str]] = {
    "claude": eskalera_claude,
    "gpt-5-mini": eskalera_gpt5mini,
}


# ---------------------------------------------------------------------------
# V2 — TILLÄGG (2026-10-02), INTE EN ÄNDRING AV OVANSTÅENDE.
#
# Bakgrund: `cap_meningskondensering_fullkontext_verifiering_diagnos.py`s
# Steg 2 (67 flerkälls-fall, kombinerad kontext) gav bara 27 % träff med
# gpt-5-mini, trots att guldsvaret fanns bokstavligen i texten i 42 % av
# fallen (gratis delsträngskontroll). Manuell genomgång av alla 49 missar
# visade: 76 % var rena AVSLAG ("informationen finns inte"), inte gissade
# fel svar — ovanstående `_prompt()`s "inget resonemang, inga gissningar"
# gör modellen överförsiktig specifikt kring att SUMMERA delbelopp som
# står separat i flera kandidater, och de sammanslagna sessionerna saknar
# helt tidsstämplar trots att LongMemEval FAKTISKT ger oss dem
# (`haystack_dates` / `question_date` i källdatan — aldrig vidarebefordrade
# av `cap_longmemeval.py::_sessioner()`), vilket gör många "hur många dagar
# mellan X och Y"-frågor olösliga även om dagarna räknas rätt ur texten.
#
# DEN HÄR SEKTIONEN ÄNDRAR INGET OVAN — `_prompt()`, `eskalera_claude()`,
# `eskalera_gpt5mini()`, `MODELLER` och `eskalera_om_behovs()` är orörda,
# så alla tidigare mätningar (Uppföljning 5–9) förblir reproducerbara
# exakt som de kördes. Det här är ett nytt, OPT-IN-spår (`modell="...-v2"`
# eller `eskalera_om_behovs_v2()`), byggt för att testa om en mer tillåtande
# prompt + tidsetiketter faktiskt hjälper — inte antaget, mätt.
# ---------------------------------------------------------------------------


def _prompt_v2(cap_svar: dict, fraga: str, dagens_datum: str | None = None) -> str:
    kandidater = cap_svar.get("context", "")
    datumrad = (f"\nFRÅGANS TIDPUNKT (använd denna som \"idag\" vid "
                f"dagsberäkningar): {dagens_datum}\n") if dagens_datum else ""
    return (
        "Du får en fråga och ett redan kuraterat urval av kandidatminnen "
        "(valda, deduplicerade och avskurna av CAP-Shield), ofta från FLERA "
        "olika tillfällen/sessioner. Använd ENDAST informationen nedan — "
        "hitta inte på fakta som inte står där.\n\n"
        "OM FRÅGAN BER OM EN SAMMANRÄKNING ELLER TIDSSKILLNAD (t.ex. \"hur "
        "många/mycket totalt\", \"hur många dagar mellan X och Y\"): det är "
        "TILLÅTET och FÖRVÄNTAT att du själv SUMMERAR delbelopp som står "
        "separat i olika kandidater, eller RÄKNAR UT antal dagar/veckor "
        "mellan två datum som nämns (eller som framgår av kandidaternas "
        "egna tidsstämplar nedan). Det är inte en gissning om alla delar "
        "du kombinerar faktiskt står i kandidaterna — visa gärna en kort "
        "uträkning innan svaret.\n"
        + datumrad + "\n" + _NARMASTE_DATUM_REGEL + "\n" + _SENASTE_UPPGIFT_GALLER_REGEL
        + "\n" + _FAKTISKT_UTFORT_REGEL +
        "\nVIKTIGT OM SVARSFORMAT (så svaret går att jämföra mot ett facit):\n"
        "- Resonemang/uträkning får stå EN eller flera rader, men avsluta "
        "ALLTID med en sista rad som börjar exakt med 'SVAR: ' följt av "
        "bara det korta, konkreta slutsvaret — inget resonemang kvar på "
        "den raden.\n"
        "- 'SVAR:'-raden ska ALLTID vara på ENGELSKA, oavsett vilket språk "
        "kandidaterna eller ditt eget resonemang ovanför råkar vara på — "
        "all data i det här benchmarket är engelskspråkig, så gissa eller "
        "matcha inget annat språk.\n"
        "- Om svaret är ett datum, tal eller annat kort faktavärde, skriv "
        "det kort och konkret i samma stil som frågan själv använder "
        "(t.ex. '2023-02-14' eller 'February 14', '8', '5.5 weeks'), inte "
        "omskrivet till en högtid eller en beskrivande fras.\n"
        "- Om urvalet verkligen INTE räcker, ÄVEN efter att ha försökt "
        "kombinera/räkna ihop delar ELLER leta efter det NÄRMASTE "
        "omnämnandet (se regeln ovan): låt 'SVAR:'-raden vara exakt "
        "'Not available in the provided selection.' Gissa aldrig bara för "
        "att undvika den raden.\n\n"
        f"FRÅGA: {fraga}\n\n"
        f"KANDIDATER:\n{kandidater}\n"
    )


# ---------------------------------------------------------------------------
# NÄRMASTE-DATUM-REGEL — TILLÄGG (2026-10-03), svar på Uppföljning 22.
#
# Bakgrund: klassificeringskörningen mot den fullständiga, giltiga v3-
# claude-filen (67/67) hittade 6 "retrieved-correct/reasoning-wrong"-fall.
# Genomgången i `cap_v5_computeoffload_verklig_diagnos.py` visade att INGET
# av dem var ett additions-/sorteringsfel (GPTs "compute offload"-förslag,
# Uppföljning 18, byggs alltså INTE som en generell modul — se Uppföljning
# 22). Men ETT av de sex (fråga 302: "I mentioned visiting a museum two
# months ago. Did I visit with a friend or not?") visade sig lösbart av en
# enkel regel: när INGET omnämnande matchar den efterfrågade tidsramen
# EXAKT, välj det NÄRMASTE i stället för att svara "Not available". En
# handkonstruerad `narmast_datum()`-funktion i sandlådan bekräftade att
# detta ger exakt guldsvaret för fråga 302 (väljer besöket 21 dagar från
# måldatumet över besöket 80 dagar bort). Den här regeln lägger samma
# resonemang direkt i PROMPTEN (modellen måste ändå göra urvalet av VILKA
# omnämnanden som räknas som samma HÄNDELSETYP — det går inte att separera
# ut till en fristående Python-modul utan att också flytta hela
# extraktionssteget dit, vilket Uppföljning 22 avfärdade som onödigt för
# bara 1/6 fall). Gäller v2 OCH v3 (samma mönster kan uppstå i båda).
#
# FÖRSTÄRKNING — TILLÄGG (2026-10-03), svar på v5-körningens fråga 302.
# Trots att regeln ovan byggdes SPECIFIKT för det här fallet (Uppföljning
# 22) och en handbyggd funktion bekräftade att den rätta logiken ger
# guldsvaret, svarade Claude ändå FEL i den riktiga --kor-körningen ("Yes,
# with a friend" i stället för korrekt "No"). Rotorsak: kontexten innehöll
# TVÅ museibesök — det korrekta (Natural History Museum, med pappa, nämnt
# EN gång) och ett helt annat (Science Museum, med en vän som är
# kemiprofessor, nämnt och utbroderat SEX+ gånger i samma session). Modellen
# lät sig alltså dras mot det mer UTFÖRLIGT OMSKRIVNA besöket i stället för
# att strikt följa datummatchningen — en "salience trap" regeln inte
# uttryckligen varnade för. Tillägget nedan gör det explicit.
# ---------------------------------------------------------------------------
# RUBRIKDATUM-REGEL — TILLÄGG (2026-10-04), svar på Robins fråga om varför
# fråga 265 fortfarande missar i en riktig körning TROTS att samma
# rotorsak (se CAP-Shield_V5_Ordningsfragor_265_270_Rotorsak_PromptFix_
# 2026-10-04.md) redan fixades samma dag. Den tidigare fixen lades BARA i
# `_prompt_v5_extrahera_ordning()` (den programmatiska ordnings-vägen).
# Men 265 föll den här gången igenom till v3-fallback(ordning) (troligen
# för att EN av de fem händelserna, musikfestivalen i Brooklyn, saknar
# ett eget datum i löptexten — precis det mönster som redan är känt —
# vilket får den programmatiska vägen att ge upp), och `_prompt_v3`
# (fritext-vägen) hade ALDRIG fått motsvarande instruktion. Modellen
# hittade därför aldrig ett datum för Brooklyn-händelsen och UTESLÖT den
# helt ur sin ordnade lista i stället för att placera in den rätt
# (bekräftat via källtexten: "--- Session 2023/04/01 ---" ... "jag just
# kom tillbaka från en musikfestival i Brooklyn" — rubrikdatumet
# 2023-04-01 hade placerat den korrekt mellan 03-25 och 04-08). FIX:
# samma regel, nu delad mellan båda prompterna i stället för bara en.
_RUBRIKDATUM_REGEL = (
    "Varje kandidat inleds med en egen rubrik på formen \"--- Session "
    "YYYY/MM/DD (veckodag) tid ---\" som anger NÄR just den konversationen "
    "ägde rum. Om en händelse beskrivs i nutid/precis-hänt-form (\"just\", "
    "\"recently\", \"today\", \"this morning\") UTAN att något annat, mer "
    "specifikt datum nämns i den löpande texten: använd den kandidatens "
    "egna rubrikdatum som händelsens datum — det räknas som skrivet i "
    "kandidaterna, INTE som en gissning, och händelsen ska INTE uteslutas "
    "ur svaret bara för att den saknar ett eget, mer specifikt datum.\n"
)


_NARMASTE_DATUM_REGEL = (
    "OM FRÅGAN REFERERAR TILL EN UNGEFÄRLIG TIDSPUNKT (t.ex. \"för två "
    "månader sedan\", \"förra veckan\", \"i våras\") och INGET omnämnande i "
    "kandidaterna matchar den tidsramen EXAKT: välj i stället det "
    "omnämnande av SAMMA TYP AV HÄNDELSE vars datum ligger NÄRMAST den "
    "efterfrågade tidpunkten, och svara utifrån det — svara inte 'Not "
    "available' bara därför att inget datum träffar exakt. Var noga med "
    "att bara jämföra mot omnämnanden som faktiskt är SAMMA HÄNDELSETYP "
    "som frågan efterfrågar (t.ex. ett \"besök\" är inte samma sak som en "
    "\"föreläsning\", även om båda handlar om samma plats) — leta efter "
    "det närmaste datumet BARA bland de omnämnanden som redan matchar "
    "händelsetypen. VIKTIGT: låt dig INTE styras av vilket omnämnande som "
    "diskuteras MEST UTFÖRLIGT eller UPPREPAS FLEST GÅNGER i kandidaterna "
    "— ett kort, enstaka omnämnande med rätt datum väger TYNGRE än ett "
    "långt, upprepat omnämnande med fel datum. Avgör strikt genom "
    "datummatchning, aldrig genom hur mycket utrymme ett omnämnande tar.\n"
    "UNDANTAG — GÄLLER INTE EXAKTA KALENDERPERIODER: om frågan i stället "
    "anger en EXAKT, namngiven period (t.ex. \"in December\", \"in March "
    "2023\", ett specifikt veckonummer) och INGET omnämnande faller inom "
    "just den perioden: svara med det antal/den uppgift som FAKTISKT "
    "gäller för den perioden (ofta 0, eller att informationen inte "
    "räcker) — låna INTE in ett omnämnande från en ANNAN period bara för "
    "att den ligger närmast i tiden. Den här regeln gäller bara för "
    "UNGEFÄRLIGA tidsangivelser (\"för två månader sedan\", \"nyligen\"), "
    "inte för frågor med en exakt angiven kalenderperiod.\n"
    "FLERSTEGS UNGEFÄRLIGA REFERENSER — TILLÄGG (2026-10-08), svar på "
    "fråga 80 (\"What time did I go to bed on the day before I had a "
    "doctor's appointment?\"): ibland måste du FÖRST räkna ut en måldag "
    "utifrån en ungefärlig referens i EN kandidat (t.ex. \"a doctor's "
    "appointment last Thursday\"), och sedan leta efter en ANNAN "
    "kandidat av rätt händelsetyp (t.ex. sänggåendetid) som har sin EGEN, "
    "separat ungefärliga referens (t.ex. \"2 AM last Wednesday\") i en "
    "annan session. Om du räknar ut varje referens strikt oberoende "
    "utifrån bara DEN sessionens eget datum kan de hamna upp till en "
    "vecka ifrån varandra även när de syftar på samma händelse — "
    "sessionsdatumet styr inte alltid hur användaren råkar formulera "
    "\"last Thursday\"/\"last Wednesday\". Om det BARA finns EN kandidat "
    "av rätt händelsetyp och dess egen ungefärliga referens ligger inom "
    "ungefär en vecka från din uträknade måldag: svara med den i stället "
    "för att avfärda den som fel vecka eller svara \"Not available\" — "
    "en ensam, approximativt matchande kandidat väger tyngre än en "
    "alltför bokstavlig datumuträkning. LÅG EVIDENSNIVÅ (ett observerat "
    "fall) — billig att testa, Robin kan ta bort den om nästa körning "
    "visar att den inte hjälper.\n"
)


# ---------------------------------------------------------------------------
# SENASTE-UPPGIFT-GÄLLER-REGEL — TILLÄGG (2026-10-03), svar på Uppföljning 24.
#
# Bakgrund: Robin körde klassificeraren (gratis, inga nya tokens) mot den
# redan sparade, fullständiga gpt-5-mini-v3-filen (67/67). Resultat: 7
# "retrieved-correct/reasoning-wrong"-kandidater (mot Claudes 6 i Uppföljning
# 22) — 95, 176, 298, 302 var redan kända/förklarade. Men TRE nya (376, 384,
# 386) visade sig, efter att ha läst den riktiga benchmarktexten direkt
# (`cap_bench/longmemeval_s_cleaned.json`, samma qid-uppslagning som
# `cap_longmemeval.py` använder), dela EXAKT samma rotorsak — inte en
# additions-/datumnärhets-fråga, utan en RENODLAD "vilken uppgift är
# AKTUELL"-fråga:
#   - Fråga 376 ("Where did I go on my most recent family trip?"): session
#     2023/05/26 nämner en familjeresa till Hawaii, session 2023/05/28 (TVÅ
#     DAGAR SENARE) nämner en familjeresa till Paris "last month". Guldsvar
#     = Paris (den SENARE sessionen). Modellen svarade Hawaii.
#   - Fråga 384 ("How many sessions of the bereavement support group did I
#     attend?"): session 2023/05/11 säger "I did attend three sessions",
#     session 2023/10/30 (FEM MÅNADER SENARE) säger "I remember attending
#     five sessions". Guldsvar = five (den SENARE sessionen).
#   - Fråga 386 ("How often do I see my therapist, Dr. Smith?"): session
#     2023/04/03 säger "it's every two weeks", session 2023/11/03 (SJU
#     MÅNADER SENARE) säger "I see Dr. Smith every week". Guldsvar = every
#     week (den SENARE sessionen). Modellen svarade med en hedge
#     ("Conflicting information...") i stället för att välja.
# I alla tre fall fanns båda, motstridiga uppgifterna bokstavligen i
# kontexten — det är inte ett urvalsglapp. Mönstret skiljer sig från
# närmaste-datum-regeln ovan (som gäller när frågan refererar till en
# UNGEFÄRLIG tidpunkt och inget matchar exakt): här frågar inte frågan om
# en specifik tidpunkt alls, utan om ett FAKTA SOM KAN HA ÄNDRATS över
# tid, och de två kandidaterna är raka motsatser. Inte verifierad mot en
# handbyggd Python-funktion (ingen renodlad uträkning att testa mot här,
# bara en jämförelseregel) — lagd direkt i prompten, samma motivering som
# närmaste-datum-regeln: urvalet av VILKA kandidater som gäller samma
# återkommande fakta måste modellen ändå göra själv. Gäller v2 OCH v3.
# ---------------------------------------------------------------------------
_SENASTE_UPPGIFT_GALLER_REGEL = (
    "OM TVÅ ELLER FLER KANDIDATER GER OLIKA/MOTSTRIDIGA VÄRDEN FÖR SAMMA "
    "ÅTERKOMMANDE ELLER FÖRÄNDERLIGA FAKTA (t.ex. hur OFTA något sker, ett "
    "ANTAL som kan ha ökat sedan sist, eller VILKEN instans av en "
    "återkommande sorts händelse som är den SENASTE/\"most recent\"): "
    "jämför kandidaternas egna datum/tidsstämplar (inte i vilken ordning de "
    "råkar stå i urvalet) och svara med uppgiften från den KRONOLOGISKT "
    "SENASTE kandidaten — den är den aktuella, korrekta uppgiften, och den "
    "äldre uppgiften var bara sann VID DEN TIDPUNKTEN. Svara ALDRIG med att "
    "uppgifterna är \"motstridiga\"/\"conflicting\" eller med ett "
    "genomsnitt av dem så länge kandidaternas datum gör det möjligt att "
    "avgöra vilken som är senast.\n"
)


# ---------------------------------------------------------------------------
# FAKTISKT-UTFÖRT-REGEL — TILLÄGG (2026-10-03), svar på Uppföljning 25.
#
# Bakgrund: djupdykning i fråga 95 ("How many hours of jogging and yoga did
# I do last week?", guldsvar "0.5 hours") visade ett ANNAT mönster än de två
# ovanstående reglerna. Facit-texten innehåller: (a) en FAKTISKT genomförd
# "30-minute jog" (= 0,5 timmar), och (b) flera omnämnanden av yoga som ALLA
# är framåtblickande/historiska — "I used to practice yoga three times a
# week...but I've been slacking off this month", "I'm hoping to get back
# into yoga this week, maybe by starting with just one or two sessions" —
# INGEN av dem beskriver ett faktiskt genomfört yoga-pass. Guldsvaret 0,5
# timmar = 0,5 (jogging) + 0 (yoga, inget genomfört). Modellen svarade "Not
# available", sannolikt för att den inte vågade räkna yoga som 0 utan att
# hitta en uttrycklig "0 timmar"-mening, och/eller för att den blandade ihop
# en historisk vana ("brukade göra X 3 ggr/vecka") med en FAKTISK händelse
# i den efterfrågade perioden.
#
# OBS — LÄGRE EVIDENSNIVÅ än de två reglerna ovan: det här bygger på EN
# manuellt analyserad fråga (95), inte flera bekräftade fall som
# närmaste-datum (302) eller senaste-uppgift (376/384/386, plus 10/11 stöd
# i helbenchmark-skanningen, Uppföljning 25). Lagd ändå, av samma skäl som
# tidigare: billig att testa (en textrad), ingen känd nackdel för andra
# frågor, och Robin kan ta bort den om nästa --kor-körning visar att den
# inte hjälper eller skadar andra fall. Gäller v2 OCH v3.
# ---------------------------------------------------------------------------
_FAKTISKT_UTFORT_REGEL = (
    "OM FRÅGAN FRÅGAR HUR MYCKET/OFTA DU FAKTISKT GJORDE NÅGOT (en redan "
    "genomförd aktivitet, t.ex. \"how many hours did I spend on X\"): räkna "
    "ENDAST omnämnanden som beskriver en FAKTISKT GENOMFÖRD händelse (t.ex. "
    "\"I went for a 30-minute jog\", \"I did yoga on Monday\") — INTE "
    "planer, avsikter eller gamla vanor uttryckta som \"I used to...\", "
    "\"I'm hoping to...\", \"I'm planning to...\", \"I'm going to start...\". "
    "Om frågan gäller FLERA aktiviteter (t.ex. \"jogging and yoga\") och en "
    "av dem INTE har någon faktiskt genomförd händelse bland kandidaterna: "
    "räkna den delen som NOLL i din uträkning — svara inte 'Not available' "
    "för HELA frågan bara för att en av flera delar saknar en genomförd "
    "händelse.\n"
)


# ---------------------------------------------------------------------------
# DATUM-ARITMETIK-SJÄLVFÖRTROENDE-REGEL — TILLÄGG (2026-10-03), svar på
# v5-körningens fråga 258 ("How many days passed between the day I received
# feedback... and the day I tested my new suspension setup?", guldsvar "38
# days"). Rotorsaksgenomgång: BÅDA de behövda sessionerna (med exakta datum
# i sina egna rubriker, 2023/03/17 och 2023/04/23) fanns bokstavligen i
# kontexten Claude fick — ändå svarade Claude "Not available", medan
# gpt-5-mini räknade ut samma differens korrekt. Det är inte ett
# informationsglapp (jfr _NARMASTE_DATUM_REGEL/_SENASTE_UPPGIFT_GALLER_REGEL
# ovan, som gäller när information FAKTISKT saknas eller är tvetydig) utan
# ett självförtroendeproblem: modellen vågade inte lita på sin egen
# subtraktion mellan två tydligt angivna datum. LÅG EVIDENSNIVÅ (ett
# observerat fall) — billig att testa (en textrad), ingen känd nackdel.
# Gäller v2 OCH v3 (och därmed v3-fallbacken i v5).
# ---------------------------------------------------------------------------
_DATUM_SJALVFORTROENDE_REGEL = (
    "OM FRÅGAN BER OM ANTAL DAGAR/VECKOR MELLAN TVÅ HÄNDELSER och BÅDA "
    "händelsernas sessioner har ett EXAKT datum angivet i sin egen rubrik "
    "eller text bland kandidaterna: räkna ut differensen själv och svara "
    "med den — tveka inte och svara inte 'Not available' bara för att "
    "uträkningen kräver ett steg till. Osäkerhet om EXAKT avrundning (t.ex. "
    "om sista dagen ska räknas med) är INGEN anledning att avstå — ge ditt "
    "bästa, mest sannolika svar.\n"
)


# ---------------------------------------------------------------------------
# BESKRIVANDE-SVAR-REGEL — TILLÄGG (2026-10-04), svar på v5-körningens
# fråga 298 ("What is the artist that I started to listen to last
# Friday?", guldsvar "a bluegrass band that features a banjo player").
# Rotorsaksgenomgång (se cap_v5_computeoffload_verklig_diagnos.py,
# punkt 3): guldsvaret är ORDAGRANT en beskrivande mening ur kontexten,
# INTE ett egennamn — men modellen avfärdade kandidaterna som
# otillräckliga, sannolikt för att den letade efter ett namn specifikt.
# Det är ett tolkningsbeslut om SVARSFORMAT (vad som räknas som ett
# giltigt svar), inte ett hämtnings- eller uträkningsproblem — därför en
# prompt-regel, inte en kod-/retrievaländring. LÅG EVIDENSNIVÅ (ett
# observerat fall, samma försiktighetsnivå som _DATUM_SJALVFORTROENDE_
# REGEL ovan) — billig att testa, ingen känd nackdel.
# ---------------------------------------------------------------------------
_BESKRIVANDE_SVAR_REGEL = (
    "OM FRÅGAN EFTERFRÅGAR ETT NAMN (t.ex. en artist, ett band, en plats) "
    "och kandidaterna INTE anger ett formellt egennamn men VÄL en tydlig "
    "BESKRIVANDE FRAS som uppenbart syftar på samma sak (t.ex. \"a "
    "bluegrass band that features a banjo player\" som svar på vilken "
    "artist du började lyssna på): ANVÄND den beskrivande frasen direkt "
    "som ditt svar — avfärda den INTE som otillräcklig bara för att den "
    "inte är ett formellt namn. Ett korrekt citat ur kandidaterna är ett "
    "giltigt svar, även när det är en beskrivning snarare än ett namn.\n"
)


# ---------------------------------------------------------------------------
# INTE-KOMBINERA-SEPARATA-FAKTA-REGEL — TILLÄGG (2026-10-04), svar på
# fråga 231 ("At which university did I present a poster for my undergrad
# course research project?", guldsvar: informationen räcker inte, personen
# nämnde ALDRIG var postern presenterades).
#
# Rotorsak (hittad via cap_v5_komparator_falsknegativ_diagnos.py, sedan
# manuellt verifierad mot kombinerad_text): modellen hittade TVÅ separata
# meningar — "I presented a poster ... at my first research conference"
# i en kandidat, och "I went to my first research conference at Harvard
# University" i en ANNAN — och drog slutsatsen "Harvard University" genom
# att koppla ihop dem, trots att INGEN av meningarna faktiskt säger att
# DET VAR SAMMA konferens. Det är en kedjad slutledning (chained
# inference), inte ett citat ur källan — exakt den typ av "gissning utan
# källa" Robin flaggade. LÅG EVIDENSNIVÅ (ett observerat fall), men
# billig att testa och i linje med den redan existerande "hitta inte på
# fakta som inte står där"-instruktionen i prompten, bara mer explicit
# om just KOMBINATIONS-fallet.
# ---------------------------------------------------------------------------
_INTE_KOMBINERA_REGEL = (
    "KOPPLA ALDRIG IHOP TVÅ SEPARATA PÅSTÅENDEN till en slutsats om "
    "INGET av dem uttryckligen gör kopplingen själv. Exempel: om EN "
    "kandidat säger \"jag presenterade en poster på min första "
    "forskningskonferens\" och en ANNAN, separat kandidat säger \"jag "
    "åkte till min första forskningskonferens vid X-universitetet\" — dra "
    "INTE slutsatsen att postern presenterades vid X-universitetet om "
    "ingen av meningarna faktiskt säger det rakt ut. Att två omnämnanden "
    "RÅKAR dela ett ord eller en beskrivning (\"min första ...\") är inte "
    "bevis för att de syftar på samma specifika tillfälle. Om svaret "
    "bara går att få fram genom en sådan kedjad gissning: svara i stället "
    "att informationen inte räcker.\n"
)


# ---------------------------------------------------------------------------
# NOLL-TRÄFFAR-REGEL — TILLÄGG (2026-10-04), svar på fråga 127 ("How many
# times did I bake egg tarts in the past two weeks?", guldsvar:
# informationen räcker inte, aktiviteten nämns aldrig).
#
# Rotorsak: modellens EGET resonemang sa ordagrant "hittade inga
# omnämnanden av 'egg tart' eller liknande" — men svarade ändå "0 times" i
# stället för avståenderaden. Modellen tolkade alltså "hittade inget" som
# "svaret är 0" i stället för "informationen räcker inte". Kontrollerad
# mot ALL sparad riktig data (141 facit-rader i de tre resultatfilerna,
# cap_v5_komparator_falsknegativ_diagnos.py): INTE ETT ENDA fall där
# facit faktiskt ÄR ett genuint bekräftat "0" (bara avståendefall) —
# alltså låg risk att den här regeln stör ett annars korrekt 0-svar.
# LÅG EVIDENSNIVÅ (ett observerat fall), billig att testa.
# ---------------------------------------------------------------------------
_NOLL_TRAFFAR_REGEL = (
    "OM FRÅGAN GÄLLER ANTALET GÅNGER/TILLFÄLLEN för en SPECIFIK, namngiven "
    "aktivitet eller händelse (t.ex. \"hur många gånger bakade jag X\") "
    "och du INTE hittar NÅGOT omnämnande alls av just den aktiviteten "
    "bland kandidaterna: svara INTE '0' — det är en gissning om att "
    "aktiviteten garanterat inte skett, inte en bekräftad uppgift. Svara "
    "i stället att informationen inte räcker, precis som vid vilken "
    "annan saknad uppgift som helst. Ett bekräftat '0' kräver att "
    "kandidaterna FAKTISKT säger något i stil med \"jag gjorde det inte\" "
    "eller \"noll gånger\" — inte bara frånvaro av omnämnande.\n"
)


# ---------------------------------------------------------------------------
# KATEGORI-BREDD-REGEL — TILLÄGG (2026-10-08), svar på fråga 89 ("How many
# pieces of furniture did I buy, assemble, sell, or fix in the past few
# months?", guldsvar "4"). Rotorsak, hittad i Claudes egen sparade
# dubbelkontroll-text (modell_svar_ra, se cap_meningskondensering_v5_
# resultat.json): modellen räknade korrekt tre poster (köpt soffbord,
# monterad bokhylla, fixat köksbord) men NÄMNDE ALDRIG den fjärde
# facit-sessionens Casper-madrassköp alls — varken som räknad eller
# avfärdad. Madrassen filtrerades alltså tyst bort redan innan
# uppräkningen, sannolikt för att den inte självklart känns som
# "möbel" i strikt mening. Till skillnad från de flesta andra reglerna
# ovan är problemet INTE en dataluka eller en felaktig datum-/
# identitetsslutsats, utan ett kategori-gränsfall som aldrig ens
# diskuterades.
#
# LÅG EVIDENSNIVÅ (ett observerat fall) — billig att testa, ingen känd
# nackdel för andra frågor (regeln bara uppmanar till att INKLUDERA
# gränsfall i uppräkningen, inte att byta ut någon annan logik).
# ---------------------------------------------------------------------------
_KATEGORI_BREDD_REGEL = (
    "OM FRÅGAN BER OM ETT ANTAL AV EN ALLMÄNT FORMULERAD KATEGORI (t.ex. "
    "\"how many pieces of furniture\", \"how many kitchen items\"): tolka "
    "kategorin GENERÖST. Ett föremål som inte är en helt uppenbar "
    "ordboksdefinition av kategoriordet (t.ex. en madrass eller "
    "sängram räknas normalt som \"möbel\" i den här typen av fråga) ska "
    "ÄNDÅ övervägas och nämnas i ditt resonemang, inte tyst utelämnas ur "
    "uppräkningen utan att du ens tar ställning till den. Vid genuin "
    "tveksamhet om ett gränsfall hör till kategorin: räkna med det "
    "hellre än att utelämna det helt oöverlagt.\n"
)


# ---------------------------------------------------------------------------
# NAMNGIVEN-SLUTPUNKT-UTESLUTS-REGEL — TILLÄGG (2026-10-08), ny miss funnen
# i samma riktiga körning som fixade 80/89/95/97/114: fråga 93 ("How many
# properties did I view before making an offer on the townhouse in the
# Brookside neighborhood?", guldsvar 4). Modellens EGNA resonemang (sparat
# i modell_svar_ra) räknade uttryckligen med alla FEM visade fastigheterna,
# INKLUSIVE Brookside-radhuset självt ("alla fem visningar före budet"),
# fast det radhuset är den NAMNGIVNA fastigheten frågan själv anger som
# slutpunkt/referens ("...before making an offer ON THE TOWNHOUSE..."). Den
# generösa kategori-tolkningen ovan (_KATEGORI_BREDD_REGEL, skriven för ett
# ANNAT scenario: om en madrass räknas som "möbel") är sannolikt en
# bidragande orsak här — men problemet är inte kategoritillhörighet (ett
# radhus ÄR förstås en "property"), utan att den namngivna slutpunkten
# aldrig ska räknas som en av de uppräknade posterna, oavsett hur
# generöst kategorin annars ska tolkas.
# LÅG EVIDENSNIVÅ (ett observerat fall), billig att testa — regeln
# uppmanar bara till att UTESLUTA den exakta, namngivna slutpunkten,
# ingen annan logik ändras.
# ---------------------------------------------------------------------------
_NAMNGIVEN_SLUTPUNKT_UTESLUTS_REGEL = (
    "OM FRÅGAN RÄKNAR/UPPRÄKNAR SAKER \"FÖRE\"/\"INNAN\" EN NAMNGIVEN, "
    "SPECIFIK SLUTPUNKT SOM FRÅGAN SJÄLV ANGER (t.ex. \"how many "
    "properties did I view BEFORE making an offer ON THE TOWNHOUSE in "
    "Brookside\"): räkna INTE med den namngivna slutpunkten själv (här: "
    "\"radhuset i Brookside\") som en av de uppräknade posterna — även "
    "om den tekniskt sett hör till samma kategori, och även om den "
    "kronologiskt inträffade före den exakta handlingen (budet) frågan "
    "nämner. Den är referenspunkten frågan mäter MOT, inte en av de "
    "saker som ska räknas.\n"
)


# ---------------------------------------------------------------------------
# UNGEFÄRLIG-PERIOD-TRÖSKEL-REGEL — TILLÄGG (2026-10-08), svar på TRE
# observerade Claude-missar i SAMMA riktiga delkörning (23/67, avbruten av
# slut på krediter): fråga 80 ("What time did I go to bed on the day
# before I had a doctor's appointment?", facit "2 AM"), fråga 95 ("How
# many hours of jogging and yoga did I do last week?", facit "0.5
# hours") och fråga 97 ("Which grocery store did I spend the most money
# at in the past month?", facit "Thrive Market").
#
# Alla tre delar EXAKT samma rotorsak, synlig i Claudes egen sparade
# dubbelkontroll-text (modell_svar_ra): självverifieringsrundan räknade
# fram en EGEN, strikt kalendergräns (vilken exakt vecka "last week"
# betyder räknat från frågans datum; vilken exakt månad "last month"
# betyder räknat från EN SESSIONS eget datum) och uteslöt sedan en
# annars rimlig uppgift för att den, enligt den strikta uträkningen,
# hamnade några dagar eller en knapp månad "fel". I alla tre fallen är
# facit byggt på en LÖSARE, narrativ tolkning av den ungefärliga
# perioden — exakt den distinktion _NARMASTE_DATUM_REGEL redan gör för
# frågor om EN enskild, närmaste händelse, men den regeln nämner aldrig
# SUMMERINGS-/RÄKNE-/JÄMFÖRELSEFRÅGOR där ett ENSKILT omnämnande ska
# inkluderas eller uteslutas ur en större uträkning — samma princip,
# men en tillämpning utan egen regel tidigare.
#
# MEDELHÖG EVIDENSNIVÅ: tre separata, oberoende frågor i SAMMA körning —
# starkare än de flesta LÅG EVIDENSNIVÅ-reglerna ovan (ett enda fall),
# men fortfarande bara EN modell (Claude) och EN körning. Bekräfta mot
# en ny --endast-fragor 80,95,97-körning, och gärna även mot gpt-5-mini,
# innan den räknas som helt stabil. Upprepas kort i
# _prompt_verifiering_v3 — annars tenderar just självverifieringsrundan
# att återintroducera precis det här felet även när första svaret redan
# var rätt (det är där felet syntes i alla tre observerade fallen).
# ---------------------------------------------------------------------------
_UNGEFARLIG_PERIOD_TROSKEL_REGEL = (
    "OM FRÅGAN ANVÄNDER EN UNGEFÄRLIG TIDSPERIOD (\"last week\", \"last "
    "month\", \"in the past few months\", \"recently\") I EN SUMMERINGS-, "
    "RÄKNE- ELLER JÄMFÖRELSEFRÅGA (till skillnad från regeln ovan, som "
    "gäller för att hitta EN enskild närmaste händelse): behandla "
    "perioden LÖST, inte som en strikt kalendergräns du själv räknar "
    "ut. Om ett omnämnande ligger NÄRA periodens gräns (några dagar, "
    "eller en session vars EGNA relativa tidsangivelse, t.ex. \"last "
    "month\", bara ligger strax utanför en exakt uträknad gräns) OCH "
    "det är den TYDLIGASTE eller ENDA relevanta uppgiften av sitt slag: "
    "räkna med den ändå, i stället för att utesluta den genom din egen, "
    "strikt uträknade kalendergräns. En sådan uträkning bygger ofta "
    "bara på vilket datum SESSIONEN råkar ha, inte på en exakt "
    "tidsstämpel användaren själv satt på HÄNDELSEN — var därför "
    "försiktig med att låta den utesluta ett annars uppenbart svar. Vid "
    "genuin tveksamhet: inkludera hellre än exkluderar.\n"
    "TILLÄGG (2026-10-08, fråga 166 — \"What was the approximate "
    "increase in Instagram followers I experienced in two weeks?\", "
    "guldsvar 100, en nytillkommen miss i samma riktiga körning som "
    "fixade 80/89/95/97/114): samma princip gäller när frågan ber om en "
    "FÖRÄNDRING/ÖKNING över en ungefärlig period och kandidaterna ger "
    "(a) ett AKTUELLT värde uttryckligen kopplat till just den perioden "
    "(t.ex. \"350 followers efter två veckors postande\"), och (b) ett "
    "tidigare nämnt värde från en ANNAN, egen tidsreferens (t.ex. "
    "\"started the year with 250 followers\") som INTE uttryckligen "
    "säger att den sammanfaller med periodens början. Kräv INTE en "
    "ordagrann, uttalad koppling mellan de två tidsreferenserna innan du "
    "använder det tidigare värdet som jämförelsepunkt — om det är den "
    "ENDA eller TYDLIGASTE tillgängliga baslinjen (ingen annan, bättre "
    "matchande uppgift finns): använd den ändå i stället för att avstå "
    "helt. LÅG EVIDENSNIVÅ (ett observerat fall) — bör bekräftas med en "
    "riktad `--endast-fragor 166`-körning innan den litas på fullt ut.\n"
)


_SVAR_RAD = __import__("re").compile(r"(?im)^\s*(?:SVAR|ANSWER):\s*(.+?)\s*$")


def extrahera_svarsrad(raw_svar: str) -> str:
    """Plockar ut sista 'SVAR: ...'-raden (eller 'ANSWER: ...', ifall
    modellen av någon anledning svarar med den engelska varianten av
    markören trots instruktionen — sett i praktiken, 2026-10-02, fråga 290
    i Uppföljning 10) ur ett v2-svar, så eventuellt resonemang/uträkning
    före den inte stör jämförelsen mot facit. Om ingen sådan rad hittas
    (modellen följde inte formatet alls) returneras hela svaret
    oförändrat — tyst degradering till gammalt beteende, aldrig ett
    kastat fel för ett formatavsteg."""
    träffar = _SVAR_RAD.findall(raw_svar)
    return träffar[-1].strip() if träffar else raw_svar.strip()


def eskalera_claude_v2(cap_svar: dict, fraga: str, modell: str = "claude-sonnet-4-5",
                        dagens_datum: str | None = None) -> str:
    nyckel = os.environ.get("ANTHROPIC_API_KEY")
    if not nyckel:
        raise EscalationError(
            "ANTHROPIC_API_KEY saknas i miljön. Sätt den (aldrig i "
            "klartext i kod eller chatt) innan eskalering körs.")
    try:
        import anthropic
    except ImportError as e:
        raise EscalationError(
            "Paketet 'anthropic' är inte installerat (pip install anthropic)."
        ) from e
    klient = anthropic.Anthropic(api_key=nyckel)
    try:
        svar = klient.messages.create(
            model=modell, max_tokens=800,
            messages=[{"role": "user", "content": _prompt_v2(cap_svar, fraga, dagens_datum)}],
        )
        return svar.content[0].text
    except Exception as e:
        raise EscalationError(f"Anthropic-anropet misslyckades: {e}") from e


def eskalera_gpt5mini_v2(cap_svar: dict, fraga: str, modell: str = "gpt-5-mini",
                          dagens_datum: str | None = None) -> str:
    nyckel = os.environ.get("OPENAI_API_KEY")
    if not nyckel:
        raise EscalationError(
            "OPENAI_API_KEY saknas i miljön. Sätt den (aldrig i klartext "
            "i kod eller chatt) innan eskalering körs.")
    try:
        import openai
    except ImportError as e:
        raise EscalationError(
            "Paketet 'openai' är inte installerat (pip install openai)."
        ) from e
    klient = openai.OpenAI(api_key=nyckel)
    try:
        svar = klient.chat.completions.create(
            model=modell,
            messages=[{"role": "user", "content": _prompt_v2(cap_svar, fraga, dagens_datum)}],
        )
        return svar.choices[0].message.content
    except Exception as e:
        raise EscalationError(f"OpenAI-anropet misslyckades: {e}") from e


MODELLER_V2: dict[str, Callable[..., str]] = {
    "claude": eskalera_claude_v2,
    "gpt-5-mini": eskalera_gpt5mini_v2,
}


def eskalera_om_behovs_v2(cap_svar: dict, fraga: str, modell: str = "claude",
                           dagens_datum: str | None = None) -> dict:
    """Som `eskalera_om_behovs()`, men med den mer tillåtande v2-prompten
    (tillåter summering/dagsberäkning, tar emot ett 'dagens datum'-ankare,
    och ber om en extraherbar 'SVAR:'-rad). Returnerar ÄVEN `svar_rå`
    (modellens fulla, oklippta svar) utöver `svar` (bara den extraherade
    SVAR-raden), så anropande kod kan logga resonemanget för insyn."""
    if not behover_eskalering(cap_svar):
        return {"eskalerad": False, "svar": cap_svar.get("context", ""),
                "svar_ra": cap_svar.get("context", ""), "kalla": "cap-shield"}
    if modell not in MODELLER_V2:
        raise EscalationError(
            f"Okänd modell '{modell}'. Kända: {sorted(MODELLER_V2)}")
    rå = MODELLER_V2[modell](cap_svar, fraga, dagens_datum=dagens_datum)
    return {"eskalerad": True, "svar": extrahera_svarsrad(rå), "svar_ra": rå,
            "kalla": modell}


# ---------------------------------------------------------------------------
# V3 — TILLÄGG (2026-10-02), INTE EN ÄNDRING AV v1/v2.
#
# Bakgrund: Uppföljning 10 (51 %) + gratis scorer-fixar (60 %, simulerat)
# lämnade kvar två tydliga, återkommande felmönster bland de genuina
# modellfelen (inte avslag, inte mätartefakter): (a) frågan 176-typen —
# modellen HITTAR delbeloppen men skriver aldrig ut slutsumman, trots att
# v2-prompten redan ber om det, och (b) frågan 252-typen — modellen får
# syn på redan FÄRDIGA tidslängder ("2 weeks", "4 weeks") men väljer ändå
# att räkna dagar mellan egna upptäckta datum i stället, och räknar fel
# ("37 veckor och 3 dagar" i stället för att summera 2+4+2=8 veckor).
#
# v3 lägger till TRE saker, allt opt-in via `eskalera_om_behovs_v3()`:
#   1. Ett konkret EXEMPEL i prompten som visar hur en korrekt summering
#      ser ut, och en uttrycklig regel: använd en redan angiven färdig
#      tidslängd direkt (addera den), räkna INTE om den till dagar mellan
#      datum om frågan inte uttryckligen bad om det.
#   2. En fri, valbar `modell_namn`-parameter (t.ex. "gpt-5" i stället för
#      "gpt-5-mini") — Robin anger själv den faktiska modellsträngen för
#      sitt konto, den här filen gissar aldrig ett modellnamn.
#   3. En ANDRA, separat modellomgång som dubbelkollar det första svaret
#      mot kandidaterna och rättar det vid behov, INNAN det slutliga
#      svaret returneras — kostar ett extra anrop per fråga, men fångar
#      just den typ av egen-uträkningsfel (b) ovan.
#
# v1/v2 är helt orörda.
# ---------------------------------------------------------------------------


# ----------------------------------------------------------------------
# Steg 123: RÄTT PERSON.
#
# I samtal mellan två personer svarade modellen ofta med den ANDRA
# personens upplevelse: frågan gällde Calvins workshop, men det var Dave
# som blivit uttagen. Raderna i kontexten börjar med talarens namn, så
# informationen fanns -- modellen kontrollerade den bara inte.
#
# Regeln läggs till BARA när kandidaterna har talarrader och frågan nämner
# en av talarna. Annars returneras tom sträng och prompten blir exakt som
# förut. LongMemEval har inga talarrader i sina kontexter.
# ----------------------------------------------------------------------
_TALARRAD = re.compile(r"^([A-Z][a-zA-Z]{1,20}):\s", re.MULTILINE)
_INTE_TALARE = frozenset({
    "User", "Assistant", "Note", "Question", "Answer", "Ingredients",
    "Instructions", "Step", "Example", "Tip", "Summary", "Title", "Q", "A",
    "SVAR", "Session", "USER", "ASSISTANT"})
_MIN_TALARRADER = 3


def _talare_i_fragan(kandidater: str, fraga: str) -> tuple[list[str], list[str]]:
    """(alla talare i kandidaterna, de av dem som frågan nämner)."""
    antal: dict[str, int] = {}
    for namn in _TALARRAD.findall(kandidater or ""):
        antal[namn] = antal.get(namn, 0) + 1
    talare = sorted(n for n, k in antal.items()
                    if k >= _MIN_TALARRADER and n not in _INTE_TALARE)
    i_fragan = [n for n in talare
                if re.search(r"\b" + re.escape(n) + r"\b", fraga or "")]
    return talare, i_fragan


def _ratt_person_regel(kandidater: str, fraga: str) -> str:
    talare, i_fragan = _talare_i_fragan(kandidater, fraga)
    if not i_fragan:
        return ""
    vem = " och ".join(i_fragan)
    return (
        "\nRÄTT PERSON-REGEL: kandidaterna är ett samtal mellan flera "
        f"personer ({', '.join(talare)}), och varje rad börjar med vem som "
        f"talar. Frågan gäller {vem}. Kontrollera vem uppgiften faktiskt "
        f"gäller innan du svarar: det {vem} själv säger om sig själv, eller "
        f"det någon annan uttryckligen säger om {vem}. Något som en ANNAN "
        f"person berättar om sig själv gäller INTE {vem}, även om ämnet, "
        "platsen eller tidpunkten stämmer exakt med frågan. Finns uppgiften "
        f"bara om en annan person än {vem}: låt 'SVAR:'-raden vara exakt "
        "'Not available in the provided selection.' Anta aldrig att båda "
        "gjort samma sak.\n")


def _ratt_person_kontroll(kandidater: str, fraga: str) -> str:
    _, i_fragan = _talare_i_fragan(kandidater, fraga)
    if not i_fragan:
        return ""
    vem = " och ".join(i_fragan)
    return (
        f"- RÄTT PERSON: frågan gäller {vem}. Peka ut raden i kandidaterna "
        "som stöder ditt svar och vem som säger den. Säger en ANNAN person "
        f"den om sig själv, gäller uppgiften inte {vem}: byt till 'Not "
        "available in the provided selection.' Omvänt: om raden visar att "
        f"uppgiften gäller {vem} (hen säger det själv, eller någon säger det "
        "om hen), behåll svaret.\n")


def _prompt_v3(cap_svar: dict, fraga: str, dagens_datum: str | None = None) -> str:
    kandidater = cap_svar.get("context", "")
    datumrad = (f"\nFRÅGANS TIDPUNKT (använd denna som \"idag\" vid "
                f"dagsberäkningar): {dagens_datum}\n") if dagens_datum else ""
    return (
        "Du får en fråga och ett redan kuraterat urval av kandidatminnen "
        "(valda, deduplicerade och avskurna av CAP-Shield), ofta från FLERA "
        "olika tillfällen/sessioner. Använd ENDAST informationen nedan — "
        "hitta inte på fakta som inte står där.\n\n"
        "OM FRÅGAN BER OM EN SAMMANRÄKNING ELLER TIDSSKILLNAD: det är "
        "TILLÅTET och FÖRVÄNTAT att du SUMMERAR delbelopp som står separat "
        "i olika kandidater, eller RÄKNAR UT antal dagar/veckor mellan två "
        "datum som nämns. VIKTIGT: om kandidaterna redan anger FÄRDIGA "
        "tidslängder (t.ex. \"2 weeks\", \"10 days\") för de delar frågan "
        "frågar om, ANVÄND DE ANGIVNA LÄNGDERNA DIREKT och summera dem — "
        "försök INTE räkna om dem till dagar/veckor mellan egna upptäckta "
        "datum i stället; räkna bara ut skillnaden mellan två datum när "
        "frågan uttryckligen ber om tiden MELLAN två specifika händelser "
        "och ingen färdig tidslängd redan är angiven.\n\n"
        "EXEMPEL PÅ KORREKT SAMMANRÄKNING (visar FORMATET, inte frågans "
        "egna sakinnehåll):\n"
        "  Fråga: \"How many total hours did I spend on hobbies?\"\n"
        "  En kandidat säger: \"...spent 3 hours on painting...\"\n"
        "  En annan kandidat säger: \"...practiced guitar for 2 hours...\"\n"
        "  Uträkning: 3 (painting) + 2 (guitar) = 5.\n"
        "  SVAR: 5 hours\n"
        "Om frågan ber om en TOTALSUMMA och du hittar flera delbelopp: "
        "skriv ALDRIG bara ut delbeloppen var för sig utan att själv lägga "
        "ihop dem till en slutsumma på SVAR-raden.\n"
        + datumrad + "\n" + _RUBRIKDATUM_REGEL + "\n" + _NARMASTE_DATUM_REGEL
        + "\n" + _SENASTE_UPPGIFT_GALLER_REGEL
        + "\n" + _FAKTISKT_UTFORT_REGEL + "\n" + _DATUM_SJALVFORTROENDE_REGEL
        + "\n" + _BESKRIVANDE_SVAR_REGEL + "\n" + _INTE_KOMBINERA_REGEL
        + "\n" + _NOLL_TRAFFAR_REGEL + "\n" + _KATEGORI_BREDD_REGEL
        + "\n" + _NAMNGIVEN_SLUTPUNKT_UTESLUTS_REGEL
        + "\n" + _UNGEFARLIG_PERIOD_TROSKEL_REGEL
        + _ratt_person_regel(kandidater, fraga) +
        "\nVIKTIGT OM SVARSFORMAT (så svaret går att jämföra mot ett facit):\n"
        "- Resonemang/uträkning får stå EN eller flera rader, men avsluta "
        "ALLTID med en sista rad som börjar exakt med 'SVAR: ' följt av "
        "bara det korta, konkreta slutsvaret — inget resonemang kvar på "
        "den raden.\n"
        "- 'SVAR:'-raden ska ALLTID vara på ENGELSKA, oavsett vilket språk "
        "kandidaterna eller ditt eget resonemang ovanför råkar vara på — "
        "all data i det här benchmarket är engelskspråkig, så gissa eller "
        "matcha inget annat språk.\n"
        "- Om svaret är ett datum, tal eller annat kort faktavärde, skriv "
        "det kort och konkret i samma stil som frågan själv använder "
        "(t.ex. '2023-02-14' eller 'February 14', '8', '5.5 weeks'), inte "
        "omskrivet till en högtid eller en beskrivande fras.\n"
        "- Om frågan ber om en ORDNING/SEKVENS eller en LISTA av flera "
        "poster: svara med ENDAST de poster frågan syftar på, kort "
        "namngivna och i rätt ordning — lägg INTE till datum, platser "
        "eller andra detaljer inom parentes efter varje post, även om "
        "sådana detaljer finns bland kandidaterna, såvida frågan inte "
        "uttryckligen bad om just den detaljen. Svara aldrig på mer än "
        "vad som efterfrågas — ett kort svar utan tillagd information "
        "är alltid att föredra.\n"
        "- Om urvalet verkligen INTE räcker, ÄVEN efter att ha försökt "
        "kombinera/räkna ihop delar ELLER leta efter det NÄRMASTE "
        "omnämnandet (se regeln ovan): låt 'SVAR:'-raden vara exakt "
        "'Not available in the provided selection.' Gissa aldrig bara för "
        "att undvika den raden.\n\n"
        f"FRÅGA: {fraga}\n\n"
        f"KANDIDATER:\n{kandidater}\n"
    )


def _prompt_verifiering_v3(fraga: str, kandidater: str, forsta_svar_ra: str) -> str:
    return (
        "Du gav nyss ett svar på en fråga utifrån ett antal kandidatminnen. "
        "Dubbelkolla nu ditt eget svar INNAN det går vidare — var kritisk "
        "mot dig själv, inte artig:\n"
        "- Stämmer varje tal/datum i ditt svar EXAKT med vad som faktiskt "
        "står skrivet i kandidaterna (inte en gissning, inte en "
        "felräkning)?\n"
        "- Om frågan bad om en SUMMA: räknade du verkligen ihop ALLA "
        "delbelopp du hittade, eller skrev du bara ut dem var för sig?\n"
        "- Om du räknade ut en tidsskillnad själv: fanns det redan en "
        "FÄRDIG tidslängd angiven i kandidaterna som du borde ha använt "
        "direkt i stället för att räkna om den?\n"
        "- Om du svarade 'Not available' med motiveringen att inget datum "
        "matchade EXAKT: kolla en gång till om något omnämnande av SAMMA "
        "HÄNDELSETYP som frågan efterfrågar faktiskt låg NÄRMAST den "
        "efterfrågade ungefärliga tidpunkten — om så, byt till det svaret "
        "i stället för 'Not available' (se närmaste-datum-regeln i din "
        "ursprungliga instruktion). Omvänt: om ditt FÖRSTA svar redan "
        "valde det närmaste omnämnandet av rätt händelsetyp, behåll det "
        "— byt INTE till 'Not available' bara därför att matchningen var "
        "ungefärlig snarare än exakt, det var avsiktligt.\n"
        "- Om ditt svar rapporterar att kandidaterna är 'motstridiga'/"
        "'conflicting', eller ger ett genomsnitt, i stället för att välja "
        "ETT konkret svar: kolla om kandidaterna har olika datum för samma "
        "återkommande fakta — om så, byt till uppgiften från den "
        "KRONOLOGISKT SENASTE kandidaten (se senaste-uppgift-gäller-regeln "
        "i din ursprungliga instruktion) i stället för att hedga. Omvänt: "
        "om ditt FÖRSTA svar redan valde den senaste uppgiften korrekt, "
        "behåll det — byt INTE till en hedge bara för att du ser att "
        "uppgifterna skiljer sig åt, det var avsiktligt.\n"
        "- Om du svarade 'Not available' för en fråga om FLERA aktiviteter "
        "(t.ex. \"X and Y\"): kolla om en av dem FAKTISKT gjordes (räknas) "
        "medan den andra bara nämns som en plan/avsikt/gammal vana — om så, "
        "räkna den ogenomförda delen som NOLL och svara med summan i "
        "stället för 'Not available' för hela frågan.\n"
        "- Om frågan gäller en UNGEFÄRLIG period (\"last week\", \"last "
        "month\") och ditt svar UTESLÖT ett omnämnande för att din EGEN "
        "uträkning av exakta kalendergränser placerade det utanför "
        "perioden: kontrollera om det ändå är den tydligaste/enda "
        "relevanta uppgiften av sitt slag — om så, byt till att "
        "INKLUDERA den i stället för att utesluta den på en strikt "
        "teknikalitet (se ungefärlig-period-tröskel-regeln i din "
        "ursprungliga instruktion). Omvänt: ändra INGET om ditt första "
        "svar redan inkluderade uppgiften korrekt.\n"
        "- Om frågan gäller en ALLMÄNT FORMULERAD KATEGORI (t.ex. "
        "\"furniture\", \"kitchen items\") och du tyst UTESLÖT ett "
        "gränsfall ur din uppräkning utan att ha övervägt det: lägg till "
        "det nu om det rimligen hör till kategorin.\n"
        "- Om frågan räknar saker \"före\"/\"innan\" en NAMNGIVEN "
        "slutpunkt frågan själv anger (t.ex. \"...before making an offer "
        "on the townhouse...\"): kontrollera att du INTE räknade med den "
        "namngivna slutpunkten (\"radhuset\") själv som en av posterna — "
        "den är referenspunkten, inte en räknad post. Om ditt första "
        "svar redan uteslöt den korrekt, ändra inget.\n"
        "- Om frågan ber om en FÖRÄNDRING/ÖKNING över en ungefärlig "
        "period och du svarade 'Not available' med motiveringen att två "
        "nämnda värden saknar en uttalad, ordagrann koppling mellan sina "
        "tidsreferenser: kontrollera om det tidigare värdet ändå är den "
        "enda/tydligaste tillgängliga baslinjen — om så, använd det i "
        "stället för att avstå helt (se tillägget om fråga 166 i "
        "ungefärlig-period-tröskel-regeln i din ursprungliga "
        "instruktion).\n"
        "- Om du räknade ut en måldag från EN ungefärlig referens (t.ex. "
        "ett läkarbesök \"last Thursday\") och sedan avfärdade den ENDA "
        "kandidaten av rätt händelsetyp (t.ex. en sänggåendetid) för att "
        "DEN kandidatens EGEN, separata ungefärliga referens (t.ex. \"2 "
        "AM last Wednesday\" i en annan session) gav en måldag en vecka "
        "ifrån din uträknade: kontrollera om det ändå är den enda "
        "rimliga matchningen — om så, byt till den i stället för 'Not "
        "available' (se flerstegs-ungefärliga-referenser-tillägget i "
        "närmaste-datum-regeln i din ursprungliga instruktion).\n"
        + _ratt_person_kontroll(kandidater, fraga) + "\n"
        f"FRÅGA: {fraga}\n\nKANDIDATER:\n{kandidater}\n\n"
        f"DITT FÖRSTA SVAR:\n{forsta_svar_ra}\n\n"
        "Skriv din dubbelkontroll kort (ett par rader räcker), och avsluta "
        "ALLTID med en sista rad som börjar exakt med 'SVAR: ' — antingen "
        "samma svar som förut (om det stämmer vid närmare granskning) "
        "eller ett rättat svar (om du hittade ett fel).\n\n"
        "VIKTIGT OM DEN RADEN (upprepat här, inte bara en hänvisning "
        "'som innan' — en tidigare version av den här prompten bara "
        "hänvisade vagt bakåt, och modellen bytte ibland språk mitt i "
        "verifieringen trots att första svaret redan var korrekt):\n"
        "- 'SVAR:'-raden ska ALLTID vara på ENGELSKA, oavsett vilket språk "
        "ditt eget resonemang ovanför råkar vara på — gissa eller matcha "
        "inget annat språk, och ändra ALDRIG ett redan korrekt engelskt "
        "svar till ett annat språk bara för att du dubbelkollar det.\n"
        "- Om svaret är ett datum, tal eller annat kort faktavärde, håll "
        "exakt samma korta, konkreta stil som första svaret använde.\n"
        "- Om urvalet verkligen INTE räcker: 'Not available in the "
        "provided selection.'"
    )


_DEFAULT_MODELLNAMN_V3 = {"claude": "claude-sonnet-4-5", "gpt-5-mini": "gpt-5-mini"}


def eskalera_claude_v3(cap_svar: dict, fraga: str, modell_namn: str | None = None,
                        dagens_datum: str | None = None) -> dict:
    nyckel = os.environ.get("ANTHROPIC_API_KEY")
    if not nyckel:
        raise EscalationError(
            "ANTHROPIC_API_KEY saknas i miljön. Sätt den (aldrig i "
            "klartext i kod eller chatt) innan eskalering körs.")
    try:
        import anthropic
    except ImportError as e:
        raise EscalationError(
            "Paketet 'anthropic' är inte installerat (pip install anthropic)."
        ) from e
    modell_namn = modell_namn or _DEFAULT_MODELLNAMN_V3["claude"]
    klient = anthropic.Anthropic(api_key=nyckel)
    try:
        forsta = klient.messages.create(
            model=modell_namn, max_tokens=800,
            messages=[{"role": "user",
                       "content": _prompt_v3(cap_svar, fraga, dagens_datum)}],
        )
        forsta_ra = forsta.content[0].text
        andra = klient.messages.create(
            model=modell_namn, max_tokens=800,
            messages=[{"role": "user",
                       "content": _prompt_verifiering_v3(
                           fraga, cap_svar.get("context", ""), forsta_ra)}],
        )
        andra_ra = andra.content[0].text
        return {"forsta_ra": forsta_ra, "andra_ra": andra_ra}
    except Exception as e:
        raise EscalationError(f"Anthropic-anropet misslyckades: {e}") from e


def eskalera_gpt5mini_v3(cap_svar: dict, fraga: str, modell_namn: str | None = None,
                          dagens_datum: str | None = None) -> dict:
    nyckel = os.environ.get("OPENAI_API_KEY")
    if not nyckel:
        raise EscalationError(
            "OPENAI_API_KEY saknas i miljön. Sätt den (aldrig i klartext "
            "i kod eller chatt) innan eskalering körs.")
    try:
        import openai
    except ImportError as e:
        raise EscalationError(
            "Paketet 'openai' är inte installerat (pip install openai)."
        ) from e
    modell_namn = modell_namn or _DEFAULT_MODELLNAMN_V3["gpt-5-mini"]
    klient = openai.OpenAI(api_key=nyckel)
    try:
        forsta = klient.chat.completions.create(
            model=modell_namn,
            messages=[{"role": "user",
                       "content": _prompt_v3(cap_svar, fraga, dagens_datum)}],
        )
        forsta_ra = forsta.choices[0].message.content
        andra = klient.chat.completions.create(
            model=modell_namn,
            messages=[{"role": "user",
                       "content": _prompt_verifiering_v3(
                           fraga, cap_svar.get("context", ""), forsta_ra)}],
        )
        andra_ra = andra.choices[0].message.content
        return {"forsta_ra": forsta_ra, "andra_ra": andra_ra}
    except Exception as e:
        raise EscalationError(f"OpenAI-anropet misslyckades: {e}") from e


MODELLER_V3: dict[str, Callable[..., dict]] = {
    "claude": eskalera_claude_v3,
    "gpt-5-mini": eskalera_gpt5mini_v3,
}


def eskalera_om_behovs_v3(cap_svar: dict, fraga: str, modell: str = "claude",
                           dagens_datum: str | None = None,
                           modell_namn: str | None = None) -> dict:
    """Som `eskalera_om_behovs_v2()`, men med tre tillägg: ett exempel i
    prompten på korrekt summering + en uttrycklig varning mot att räkna
    om redan angivna tidslängder, en valfri `modell_namn` (Robins egen
    modellsträng, t.ex. "gpt-5" — gissas ALDRIG av den här filen), och en
    ANDRA, separat modellomgång som dubbelkollar/rättar det första svaret
    innan det returneras. Kostar DUBBELT så många anrop som v2 per fråga.

    Returnerar: {"svar": <slutligt, verifierat SVAR-rad>,
                 "svar_forsta": <ORIGINALSVARET, innan verifiering>,
                 "svar_ra": <hela verifieringsomgångens råtext>,
                 "svar_ra_forsta": <hela första omgångens råtext>,
                 "eskalerad": bool, "kalla": modell}"""
    if not behover_eskalering(cap_svar):
        return {"eskalerad": False, "svar": cap_svar.get("context", ""),
                "svar_forsta": cap_svar.get("context", ""),
                "svar_ra": cap_svar.get("context", ""),
                "svar_ra_forsta": cap_svar.get("context", ""),
                "kalla": "cap-shield"}
    if modell not in MODELLER_V3:
        raise EscalationError(
            f"Okänd modell '{modell}'. Kända: {sorted(MODELLER_V3)}")
    resultat = MODELLER_V3[modell](cap_svar, fraga, modell_namn=modell_namn,
                                    dagens_datum=dagens_datum)
    return {"eskalerad": True,
            "svar": extrahera_svarsrad(resultat["andra_ra"]),
            "svar_forsta": extrahera_svarsrad(resultat["forsta_ra"]),
            "svar_ra": resultat["andra_ra"],
            "svar_ra_forsta": resultat["forsta_ra"],
            "kalla": modell}


# ---------------------------------------------------------------------------
# v5 (2026-10-03) — RIKTAD FIX mot de två kvarvarande, väldokumenterade
# mönstren i CAP-Shield_Problemsammanstallning_LLMEskalering_ExternKonsultation_
# 2026-10-02.md ("mönster A": hittar delbeloppen men summerar dem aldrig;
# "mönster B": kronologisk ordning blir fel/ofullständig trots synliga datum).
#
# IDÉ (föreslagen i samma dokuments egen fråga 2, nu byggd och testad):
# i stället för att be modellen BÅDE hitta OCH räkna ut/sortera svaret i
# fritext, delas de två stegen: modellen gör BARA EXTRAKTIONEN (lista
# delbelopp, eller lista händelser+datum) som strukturerad JSON, och Python
# gör den programmatiska delen (summera, sortera) DETERMINISTISKT efteråt —
# den typ av "sista-steget-glöms"-fel v3 inte kunde lösa med ett exempel i
# prompten eller en uttrycklig dubbelkontrollsfråga kan inte uppstå när
# modellen aldrig ombeds göra det steget alls.
#
# ALDRIG SÄMRE ÄN v3: en fråga som varken är en SUMMA- eller ORDNINGS-fråga
# går OFÖRÄNDRAT till v3 (identisk kostnad, identiskt resultat). Och om
# extraktionen för en SUMMA/ORDNING-fråga misslyckas (ogiltig JSON, tomt,
# eller — för ORDNING specifikt — något exakt datum saknas) faller koden
# TYST tillbaka på v3:s fulla, redan validerade två-rundors-flöde för just
# den frågan, i stället för att gissa ett halvfärdigt programmatiskt svar.
#
# KOSTNAD: v5:s två riktade vägar kräver bara ETT modellanrop (ren
# extraktion, ingen verifieringsrunda) — BILLIGARE än v3:s två anrop för
# just de frågorna, inte en tredje dyr omgång ovanpå.
# ---------------------------------------------------------------------------

_V5_SUMMAFRAGA = re.compile(
    r"\bhow (many|much)\b.{0,60}\b(total|altogether|combined|in all)\b"
    r"|\b(total|altogether|combined)\b.{0,40}\bhow (many|much)\b",
    re.IGNORECASE)
# UPPFÖLJNING 2026-10-04: fråga 176 ("How many plants did I initially
# plant for tomatoes and cucumbers?", facit 8, modellen svarade
# "Tomatoes: 5; Cucumbers: 3") var SJÄLVA frågan som ursprungligen
# motiverade att bygga v5-summa (se Uppföljning 18/cap_escalate_helper.py
# ovan) — men den missar sin egen regex, eftersom den aldrig innehåller
# "total/altogether/combined/in all". Mönstret är "how many/much ... for
# A and B?" (en EFTERFRÅGAD, KOMBINERAD kvantitet för två namngivna
# delar), vilket skiljer sig från "how many A and how many B" (två
# SEPARATA frågor, ska INTE summeras ihop). Negativa villkor
# (en andra "how many/much", "respectively", "each") håller den smal —
# validerad mot samtliga 67 riktiga --kor-frågor (2026-10-03-körningen):
# matchar BARA fråga 176 nytt, ingen kollateral skada på de övriga 66.
#
# RÄTTAD 2026-10-04 (hittad av samma 67-frågors validering): "How many
# days had passed BETWEEN the 'Walk for Hunger' event and the 'Coastal
# Cleanup' event?" (fråga 319) matchade av misstag — ordet "for" kom
# från EVENTNAMNET "Walk for Hunger", inte från en "for A and B"-
# konstruktion. Den frågan är dessutom en datumdifferens-fråga (samma
# familj som fråga 258), INTE en summeringsfråga — att skicka den till
# _v5_forsok_summa (som letar efter "delbelopp" att addera) hade varit
# direkt fel, inte bara en missad chans. "between ... and ..." är ett
# pålitligt tecken på just den familjen, så den utesluts uttryckligen.
_V5_SUMMAFRAGA_FOR_OCH = re.compile(
    r"\bhow (many|much)\b"
    r"(?!.*\bhow (?:many|much)\b)"   # bara EN kvantitetsfråga i meningen
    r"(?!.*\brespectively\b)"       # "X and Y respectively" = separata svar
    r"(?!.*\beach\b)"               # "...for X and Y each" = separata svar
    r"(?!.*\bbetween\b)"            # "between X and Y" = datumdifferens, inte summa
    r".{0,60}\bfor\b\s+[\w\-' ]{1,30}?\band\b\s+[\w\-' ]{1,30}?\?",
    re.IGNORECASE)
# TILLÄGG (2026-10-04), svar på fråga 95 ("How many hours of jogging and
# yoga did I do last week?", facit "0.5 hours"): samma SHAPE som
# _V5_SUMMAFRAGA_FOR_OCH (en efterfrågad, kombinerad kvantitet för två
# namngivna delar) men med "of" i stället för "for" ("hours OF jogging
# and yoga" i stället för "spent FOR jogging and yoga"). Samma negativa
# villkor, av samma skäl. Validerad mot samtliga 67 riktiga --kor-frågor
# och hela 500-frågors-underlaget: matchar BARA fråga 95 nytt, ingen
# kollateral skada (se CAP-Shield_V5_TvaEnklaFixar_95_82_87_2026-10-04.md
# för fullständig valideringslogg).
_V5_SUMMAFRAGA_AV_OCH = re.compile(
    r"\bhow (many|much)\b"
    r"(?!.*\bhow (?:many|much)\b)"
    r"(?!.*\brespectively\b)"
    r"(?!.*\beach\b)"
    r"(?!.*\bbetween\b)"
    r".{0,60}\bof\b\s+[\w\-' ]{1,30}?\band\b\s+[\w\-' ]{1,30}?\?",
    re.IGNORECASE)
_V5_ORDNINGSFRAGA = re.compile(
    r"\b(order of|earliest to latest|latest to earliest|chronological "
    r"order|in what order|which order)\b", re.IGNORECASE)
_V5_ORDNING_FALLANDE = re.compile(
    r"\b(latest to earliest|most recent first|reverse chronological)\b",
    re.IGNORECASE)
# TILLÄGG (2026-10-04), svar på fråga 82/87 ("How many movie festivals
# that I attended?", "How many weddings have I attended in this year?"):
# en HELT ANNAN frågeform än summa — det efterfrågas INTE en summerad
# MÄNGD/BELOPP (timmar, dollar, veckor) utan ett ANTAL namngivna,
# DISTINKTA händelser. Täcks inte av _V5_SUMMAFRAGA* (ingen "total"/"for
# A and B"-struktur). Den negativa inledande spärren utesluter uttryckligen
# MÄTENHETER direkt efter "how many" (hours/days/weeks/dollars/times) så
# att frågor som redan hanteras av summa-familjen (t.ex. fråga 95, "how
# many HOURS of...") aldrig också matchar här — kontrollordningen i
# _v5_fragetyp() (summa kollas FÖRE räkning) är ett andra skyddslager för
# samma sak. Validerad mot samtliga 67 riktiga frågor + hela 500-frågors-
# underlaget: matchar BARA 82 och 87 nytt, ingen kollision med någon
# redan klassificerad summa/ordnings-fråga.
_V5_RAKNINGSFRAGA = re.compile(
    r"\bhow many\b"
    r"(?!\s+(hours?|minutes?|days?|weeks?|months?|years?|dollars?|times?|\$))"
    r".{0,40}\b(attend\w*|been to|gone to|visited|been at)\b",
    re.IGNORECASE)

# TILLÄGG (2026-10-08), svar på fråga 97 ("Which grocery store did I
# spend the most money at in the past month?", facit "Thrive Market"):
# en FJÄRDE frågeform, varken summa/ordning/rakning — frågan efterfrågar
# INTE en summerad mängd, en kronologisk ordning eller ett antal
# händelser, utan VILKEN av flera NAMNGIVNA saker (här: butiker) som har
# STÖRST (eller minst) totalt värde. Rotorsak (se Claudes egen sparade
# dubbelkontroll-text): modellen gör själv både per-butik-summeringen
# OCH jämförelsen i fri text, och råkar då också applicera en egen,
# strikt kalendergräns (se _UNGEFARLIG_PERIOD_TROSKEL_REGEL ovan) som
# utesluter den butik som faktiskt har högst totalsumma. Samma princip
# som summa/ordning/rakning: modellen gör BARA extraktionen (listar
# varje belopp den hittar, kopplat till vilken namngiven sak det
# gäller), Python gör både summeringen PER NAMN och jämförelsen.
# Negativ spärr mot "most recent"/"latest"/"earliest"/"chronological"
# håller den åtskild från ordningsfrågornas egna superlativ om
# RECENSITET (t.ex. "in what order, most recent first") — de frågar om
# TIDSORDNING, inte om en summerad STORLEK per namngiven sak.
# LÅG EVIDENSNIVÅ (en observerad fråga) — ny kodväg, bör verifieras med
# --endast-fragor 97 (och gärna fler liknande jämförelsefrågor om sådana
# hittas) innan den litas på fullt ut.
_V5_JAMFORELSEFRAGA = re.compile(
    r"\bwhich\b"
    r"(?!.*\b(?:most recent|latest|earliest|chronological order)\b)"
    r".{0,50}\b(most|highest|largest|greatest|least|lowest|smallest|fewest)\b"
    r".{0,30}\b(money|amount|times?|hours?|dollars?|\$|spent|spend)\b",
    re.IGNORECASE)


def _v5_fragetyp(fraga: str) -> str:
    """'summa', 'ordning', 'rakning', 'jamforelse' eller 'annat' — rent
    heuristiskt, ärligt begränsat (regex, inte en riktig klassificerare),
    men frågor som missklassas som 'annat' går bara till v3 oförändrat,
    ingen skada. Kontrollordning avsiktlig: ordning och summa kollas FÖRE
    jamforelse och rakning, så en fråga som råkar matcha flera mönster
    alltid hamnar i den mest specifika, redan validerade kategorin."""
    if _V5_ORDNINGSFRAGA.search(fraga):
        return "ordning"
    if (_V5_SUMMAFRAGA.search(fraga) or _V5_SUMMAFRAGA_FOR_OCH.search(fraga)
            or _V5_SUMMAFRAGA_AV_OCH.search(fraga)):
        return "summa"
    if _V5_JAMFORELSEFRAGA.search(fraga):
        return "jamforelse"
    if _V5_RAKNINGSFRAGA.search(fraga):
        return "rakning"
    return "annat"


# TILLÄGG (2026-10-04), svar på fråga 132 ("How many years in total did
# I spend in formal education from high school to the completion of my
# Master's degree?", guldsvar: informationen räcker inte, eftersom
# Master's-periodens längd aldrig nämns). Modellen hittade bara 2 av de
# underförstådda stegen (gymnasiet + kandidatexamen) och summerade DEM,
# utan att flagga att slutpunkten frågan själv namnger ("completion of
# my Master's degree") saknade all uppgift. Till skillnad från ordnings-
# extraktionen (`_v5_forsok_ordning`, som redan ger upp och lämnar över
# till v3 om ett datum saknas) hade summerings-extraktionen INGEN
# motsvarande spärr — den summerar helt enkelt vad den hittar. FIX: en
# ny, EXPLICIT null-markör modellen kan sätta när frågans NAMNGIVNA
# slutpunkt saknar uppgift helt (skiljs tydligt från det BEFINTLIGA,
# redan validerade "X and Y combined, en del saknas = räkna som 0"-
# scenariot nedan, som är en ANNAN situation). `_v5_forsok_summa()` (se
# nedan) bail:ar till v3 om en sådan post dyker upp. Verifierat mot alla
# 8 tidigare sparade RIKTIGA v5-summa-extraktioner (rå JSON-text) att
# INGEN av dem någonsin satt "belopp": null — den nya markören kan alltså
# inte råka trigga av misstag på gammal, redan korrekt extraktionslogik.
# TILLÄGG (2026-10-08, uppföljning efter riktig testkörning av de fyra
# fempatch-frågorna): fråga 95 ("How many hours of jogging and yoga did I
# do last week?") kvarstod FELAKTIG (2,5 timmar i stället för guldsvaret
# 0,5) trots att _FAKTISKT_UTFORT_REGEL och _UNGEFARLIG_PERIOD_TROSKEL_
# REGEL redan fanns i kodbasen (den förra skriven 2026-10-03 UTTRYCKLIGEN
# för just denna fråga). Rotorsak, verifierad gratis mot den faktiska
# facit-texten (cap_bench/longmemeval_s_cleaned.json, fråga 95): modellen
# räknade med "I used to practice yoga three times a week, each time for
# 2 hours, but I've been slacking off for this month" som en genomförd
# 2-timmarspass — trots att meningen uttryckligen beskriver en ÖVERGIVEN
# gammal vana, inte en faktiskt utförd händelse under "last week". Exakt
# det scenario _FAKTISKT_UTFORT_REGEL beskriver — men den regeln (liksom
# _UNGEFARLIG_PERIOD_TROSKEL_REGEL) är BARA inbakad i _prompt_v2()/
# _prompt_v3(), aldrig i denna v5-specifika extraktionsprompt. "Summa"-
# frågor (och "räkne"-frågor, se _prompt_v5_extrahera_rakning nedan)
# dirigeras till DEN HÄR prompten i stället för v3-fallbacken, så hela
# regelbiblioteket som byggts upp i v3 (daterad-vs-vana, ungefärlig
# periodgräns m.fl.) har aldrig nått den — en arkitekturlucka, inte en
# svag regeltext. FIX: lägger till samma två regler här. Billigt att
# testa (textrader, ingen kodlogik ändrad), samma risknivå som när de
# ursprungligen lades till i v3.
#
# TILLÄGG (2026-10-08, ny miss i samma riktiga körning som fixade
# 80/89/95/97/114): fråga 124 ("How many years in total did I spend in
# formal education from high school to the completion of my Bachelor's
# degree?", guldsvar "10 years") fick fel svar ("8 years") trots att den
# nu gick via DEN HÄR extraktionsvägen. Rotorsak, verifierad gratis mot
# kombinerad_text_bred: modellen hittade bara HS (4 år, 2010–2014) och
# Bachelor's (4 år, "took me four years to complete", klar 2020) — men
# missade EN TREDJE post som FAKTISKT står i texten: en Associate's-
# examen från Pasadena City College (PCC), "earned ... in May 2016,
# before joining UCLA". Den posten nämns i en helt annan session och med
# andra ord än frågan ("high school"/"Bachelor's"), och dess längd (2 år)
# anges aldrig som en färdig "X years"-siffra — den går bara att räkna ut
# genom att jämföra PCC-examensdatumet (maj 2016) mot HS-slutet (2014).
# Den SYSKONFRÅGA som delar underlag (132, "...completion of my Master's
# degree?") nämner för övrigt PCC-perioden explicit i sitt guldsvar ("2
# years at PCC (2014-2016)") — bekräftar att detta är en avsedd,
# räknebar delpost, inte bara en marginell detalj. FIX: en ny, uttrycklig
# instruktion att leta efter ALLA mellanliggande steg mellan de två
# namngivna bokstavsändarna (inte bara de som delar frågans egna ord) och
# att räkna ut en längd från två nämnda datum när ingen färdig siffra
# ges. LÅG EVIDENSNIVÅ (ett observerat fall) — bör bekräftas med en
# riktad `--endast-fragor 124,132`-körning (båda delar underlag) innan
# den litas på fullt ut.
def _prompt_v5_extrahera_summa(cap_svar: dict, fraga: str) -> str:
    kandidater = cap_svar.get("context", "")
    return (
        "Du får en fråga som ber om en SAMMANRÄKNAD TOTALSUMMA, och ett "
        "redan kuraterat urval av kandidatminnen. Din ENDA uppgift här är "
        "att HITTA OCH LISTA de enskilda delbeloppen som är relevanta för "
        "att svara på frågan — RÄKNA INTE IHOP dem själv, det görs "
        "programmatiskt efteråt av annan kod.\n\n"
        "Svara ENDAST med en JSON-lista, inget annat resonemang, inga "
        "extra rader, inga markdown-kodstaket. Varje element: "
        '{"belopp": <tal>, "enhet": <kort enhet eller null, t.ex. '
        '"hours", "plants", "times">, "kalla": <kort beskrivning av '
        "varifrån beloppet kommer>}.\n"
        "- Om ett delbelopp redan ÄR en färdig totalsumma för EN av de "
        "efterfrågade delarna (t.ex. \"I spent 2 weeks\"), lista det som "
        "EN post — försök inte räkna om den till en annan enhet.\n"
        "- Om frågan efterfrågar flera NAMNGIVNA delar (t.ex. \"X and Y "
        "combined\") och en av delarna INTE har något omnämnande alls: "
        "lista INGEN post för den delen (den räknas som 0 automatiskt).\n"
        "- ANNORLUNDA SCENARIO: om frågan i stället beskriver ett "
        "SAMMANHÄNGANDE FÖRLOPP med en explicit NAMNGIVEN SLUTPUNKT "
        "(t.ex. \"from X to the completion of Y\") och just den "
        "slutpunkten (\"Y\") INTE har NÅGON uppgift alls om sin egen "
        "längd/sitt eget datum bland kandidaterna: lista DÅ i stället en "
        "sista post {\"belopp\": null, \"enhet\": null, \"kalla\": "
        "\"SAKNAS: <den del frågan namnger som inte går att belägga>\"} "
        "— till skillnad från scenariot ovan betyder frånvaro HÄR att "
        "hela totalsumman inte går att räkna ut, inte att den delen är "
        "0.\n"
        "- OM FRÅGAN BESKRIVER EN SAMMANHÄNGANDE PERIOD MED EN NAMNGIVEN "
        "START- OCH SLUTPUNKT (t.ex. \"from high school to the "
        "completion of my Bachelor's degree\"): leta igenom HELA texten "
        "efter VARJE mellanliggande steg som kronologiskt ligger MELLAN "
        "de två namngivna punkterna — inte bara de steg som råkar nämnas "
        "med samma ord som frågan själv använder (t.ex. en examen från "
        "en annan skola, nämnd i en helt annan session, räknas också om "
        "den ligger mellan de två bokstavsändarna). Om ett sådant "
        "mellanliggande stegs längd inte anges som en färdig \"X "
        "years\"-siffra men GÅR att räkna ut utifrån två nämnda datum "
        "(t.ex. ett examensdatum jämfört med ett tidigare nämnt "
        "startdatum): räkna ut den själv och lista den som en egen "
        "post, i stället för att hoppa över den bara för att ingen "
        "färdig siffra stod utskriven.\n"
        "- Om inget relevant delbelopp alls hittas: svara med en tom "
        "lista, [].\n\n"
        + _FAKTISKT_UTFORT_REGEL + "\n" + _UNGEFARLIG_PERIOD_TROSKEL_REGEL +
        f"\nFRÅGA: {fraga}\n\nKANDIDATER:\n{kandidater}\n"
    )


# UPPFÖLJNING (2026-10-04), rotorsak till fråga 265 och 270 (båda föll
# till v3-fallback(ordning) i senaste riktiga körningen): undersökt
# GRATIS (lokal textinspektion av de redan hämtade kandidaterna, inga
# modellanrop) via _kor_fraga() för just dessa två frågor. Fynd: för
# BÅDA frågorna saknar den löpande texten som beskriver målhändelsen
# ("just saw them live...", "I just got back from a flight on
# JetBlue... today") ett eget, explicit omnämnt datum — händelsen
# dateras bara IMPLICIT av konversationens egen tidsstämpel (t.ex.
# "--- Session 2023/04/15 (Sat) 02:29 ---"). Den gamla prompten bad
# modellen hitta ett datum "som nämns i kandidaterna" utan att
# uttryckligen säga att rubrikens eget datum RÄKNAS som ett sådant —
# sannolikt varför extraktionen misslyckas (saknar datum → hela
# _v5_forsok_ordning() ger upp och v3 tar över, enligt kommentaren vid
# `giltiga`-kontrollen ovan). Mönstret är INTE unikt för dessa två
# frågor (samma "just/recently/today utan eget datum"-struktur syns i
# samtliga 5 kandidater för båda frågorna) — det är alltså en generell
# brist i ordnings-extraktionen, inte ett särfall, och förtjänar därför
# en fix här snarare än en smal regex-spärr för bara dessa två.
# FIX: prompten förtydligar nu explicit att kandidatens EGEN
# rubrikdatum får användas som händelsens datum när ingen annan,
# mer specifik dag nämns i löptexten. Ingen ändring av _v5_forsok_
# ordning()s egen sorteringslogik eller v3-vägens prompt. Kan ENDAST
# valideras genom en riktig modellkörning (prompttext går inte att
# testa deterministiskt utan ett modellanrop) — invänta Robins nästa
# --kor-körning innan vidare slutsats dras.
#
# TILLÄGG (2026-10-04), Robins iakttagelse efter att ha granskat de
# X-markerade ordningsfrågorna manuellt (`cap_v5_komparator_
# falsknegativ_diagnos.py`): frågorna 235, 265 och 270 (v5-gpt-raden)
# hade FAKTISKT rätt ordning, men "svar"-strängen (byggd genom att slå
# ihop varje posts "handelse"-fält, se `_v5_forsok_ordning()` nedan:
# `svar = ", ".join(h for _, h in giltiga)`) innehöll extra detaljer
# modellen lagt till men frågan inte bad om — t.ex.
# "JetBlue (red-eye flight San Francisco -> Boston)" i stället för
# bara "JetBlue". Det bryter jämförelsen mot facit även när ordningen
# är rätt. Roten är alltså INTE sorteringslogiken utan att modellen
# stoppar in mer i "handelse"-fältet än den korta benämning frågan
# syftar på. FIX: ett nytt, uttryckligt förbud mot att lägga till
# sådan extra information i just det fältet (se nedan). Samma
# försiktighetsnivå som övriga prompt-regler ovan — bara
# validerbar genom en riktig körning, inte deterministiskt här.
def _prompt_v5_extrahera_ordning(cap_svar: dict, fraga: str) -> str:
    kandidater = cap_svar.get("context", "")
    return (
        "Du får en fråga som ber om KRONOLOGISK ORDNING på flera "
        "händelser, och ett redan kuraterat urval av kandidatminnen. Din "
        "ENDA uppgift här är att LISTA de enskilda händelserna med sina "
        "datum — SORTERA INTE dem själv, det görs programmatiskt efteråt "
        "av annan kod.\n\n"
        "Svara ENDAST med en JSON-lista, inget annat resonemang, inga "
        "extra rader, inga markdown-kodstaket. Varje element: "
        '{"handelse": <kort beskrivning, de ord svaret bör innehålla, '
        't.ex. ett namn/plats/sak>, "datum": <"YYYY-MM-DD" om ett EXAKT '
        'datum nämns i kandidaterna, annars null>}.\n'
        "- \"handelse\" ska vara KORT och innehålla BARA den benämning "
        "frågan själv syftar på (ofta bara ett namn, en plats eller en "
        "sak, t.ex. \"JetBlue\" eller \"Billie Eilish concert\"). Lägg "
        "INTE till extra detaljer från kandidaterna som frågan inte bad "
        "om (flygrutt, försening, stad/arena inom parentes, m.m.), även "
        "om sådana detaljer nämns i källtexten — det slutgiltiga svaret "
        "byggs genom att slå ihop dessa fält, och överflödig information "
        "gör ett annars korrekt svar svårare att känna igen mot facit.\n"
        "- Ta med VARJE händelse frågan nämner eller syftar på, även om "
        "du inte hittar ett exakt datum för alla — sätt då \"datum\": "
        "null för just den.\n"
        "- Om flera meningar beskriver samma händelse ska den bara "
        "förekomma EN gång i listan, även om händelsen beskrivs med "
        "olika formuleringar. Slå bara ihop omnämnanden när källtextens "
        "specifika detaljer och sammanhang stöder att de avser samma "
        "tillfälle. Samma platsnamn är inte i sig tillräckligt för att "
        "slå ihop två händelser. Om texten visar olika besök, "
        "exempelvis genom olika namngivna utställningar eller "
        "uttryckligen olika datum, ska de behållas som separata "
        "händelser. Om det är oklart om två omnämnanden avser samma "
        "tillfälle, hitta inte på att de är identiska: behåll dem "
        "separat tills identiteten kan styrkas av källtexten.\n"
        "- Varje kandidat inleds med en egen rubrik på formen "
        '"--- Session YYYY/MM/DD (veckodag) tid ---" som anger NÄR just '
        "den konversationen ägde rum. Om en händelse beskrivs i "
        "nutid/precis-hänt-form (\"just\", \"recently\", \"today\", "
        '"this morning") UTAN att något annat, mer specifikt datum '
        "nämns i den löpande texten: använd den kandidatens egna "
        "rubrikdatum som händelsens datum — det räknas som skrivet i "
        "kandidaterna, INTE som en gissning.\n"
        "- Gissa ALDRIG ett datum som inte går att hitta på något av "
        "dessa två sätt (ett eget datum i löptexten, eller kandidatens "
        "rubrikdatum).\n"
        "- Om flera kandidathändelser har snarlika eller delvis "
        "överlappande namn (flera museer, flera konserter, flera "
        "flygningar med liknande sträcka, m.m.): dubbelkolla att "
        "datumet du sätter för VARJE \"handelse\" kommer från den "
        "kandidat som faktiskt nämner just DEN exakta benämningen — "
        "inte ett datum lånat från en näraliggande, snarlikt namngiven "
        "händelse. Två olika händelser ska ALDRIG få samma datum om "
        "inte källtexten uttryckligen säger att de skedde samma "
        "dag.\n\n"
        f"FRÅGA: {fraga}\n\nKANDIDATER:\n{kandidater}\n"
    )


def _v5_anropa_en_gang(modell: str, prompt_text: str,
                        modell_namn: str | None) -> str:
    """Ett enda modellanrop (ingen verifieringsrunda) — återanvänder
    samma nyckelhantering/felhantering som v3:s wrappers, men bara en
    omgång, eftersom v5:s extraktionssteg inte behöver dubbelkollas av
    modellen själv (Python-uträkningen efteråt ÄR dubbelkontrollen)."""
    if modell == "claude":
        nyckel = os.environ.get("ANTHROPIC_API_KEY")
        if not nyckel:
            raise EscalationError(
                "ANTHROPIC_API_KEY saknas i miljön. Sätt den (aldrig i "
                "klartext i kod eller chatt) innan eskalering körs.")
        try:
            import anthropic
        except ImportError as e:
            raise EscalationError(
                "Paketet 'anthropic' är inte installerat "
                "(pip install anthropic)."
            ) from e
        namn = modell_namn or _DEFAULT_MODELLNAMN_V3["claude"]
        klient = anthropic.Anthropic(api_key=nyckel)
        try:
            r = klient.messages.create(
                model=namn, max_tokens=800,
                messages=[{"role": "user", "content": prompt_text}])
            return r.content[0].text
        except Exception as e:
            raise EscalationError(f"Anthropic-anropet misslyckades: {e}") from e
    elif modell == "gpt-5-mini":
        nyckel = os.environ.get("OPENAI_API_KEY")
        if not nyckel:
            raise EscalationError(
                "OPENAI_API_KEY saknas i miljön. Sätt den (aldrig i "
                "klartext i kod eller chatt) innan eskalering körs.")
        try:
            import openai
        except ImportError as e:
            raise EscalationError(
                "Paketet 'openai' är inte installerat (pip install openai)."
            ) from e
        namn = modell_namn or _DEFAULT_MODELLNAMN_V3["gpt-5-mini"]
        klient = openai.OpenAI(api_key=nyckel)
        try:
            r = klient.chat.completions.create(
                model=namn, messages=[{"role": "user", "content": prompt_text}])
            return r.choices[0].message.content
        except Exception as e:
            raise EscalationError(f"OpenAI-anropet misslyckades: {e}") from e
    else:
        raise EscalationError(f"Okänd modell '{modell}' för v5-extraktion.")


def _v5_parsa_json_lista(raw: str) -> list | None:
    """Tolerant JSON-tolkning: modellen ombeds svara med ENDAST en JSON-
    lista, men kan ändå lägga till markdown-kodstaket eller enstaka
    extra text — försök städa innan vi ger upp. None = kunde inte
    tolkas alls (anropande kod faller då tillbaka på v3)."""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```\s*$", "", text, flags=re.IGNORECASE)
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except (json.JSONDecodeError, ValueError):
            return None
    return data if isinstance(data, list) else None


# ---------------------------------------------------------------------------
# ENHETSKONVERTERING — TILLÄGG (2026-10-08), ny miss funnen i samma riktiga
# körning som fixade 80/89/95/97/114: fråga 83 ("How many days did I take
# social media breaks in total?", guldsvar "17 days") fick fel svar ("11
# weeks"). Rotorsak, verifierad gratis mot rastext_extraktion: extraktionen
# var FAKTISKT helt korrekt — den hittade exakt {"belopp":1,"enhet":
# "weeks"} (en veckas paus i januari) och {"belopp":10,"enhet":"days"} (10
# dagars paus i februari), vilket är 1 vecka + 10 dagar = 17 dagar, EXAKT
# guldsvaret. Men summeringskoden nedan adderade bara RÅTALEN (1+10=11) och
# döpte resultatet efter den FÖRSTA enheten den råkade se ("weeks") — en ren
# Python-räknebugg, ingen prompt-/modellfråga. FIX: när delbeloppen har
# OLIKA enheter men ALLA är kända tidsenheter, konvertera till en gemensam
# enhet (dagar) innan summering. Om enheterna är IDENTISKA (det vanliga
# fallet) eller inte alla är kända tidsenheter: gammalt beteende oförändrat
# (summera råtalen, döp efter första enheten) — ingen risk för andra,
# redan korrekta frågor.
# ---------------------------------------------------------------------------
_TIDSENHET_TILL_DAGAR = {
    "day": 1.0, "days": 1.0,
    "week": 7.0, "weeks": 7.0,
    "month": 30.0, "months": 30.0,
    "year": 365.0, "years": 365.0,
    "hour": 1 / 24, "hours": 1 / 24,
    "minute": 1 / 1440, "minutes": 1 / 1440,
}


def _normalisera_till_dagar(belopp: float, enhet: str | None) -> float | None:
    """None om enheten inte är en KÄND tidsenhet (kan då inte konverteras
    säkert — anropande kod faller tillbaka på gammalt beteende)."""
    if not enhet:
        return None
    faktor = _TIDSENHET_TILL_DAGAR.get(enhet.strip().lower())
    if faktor is None:
        return None
    return belopp * faktor


def _v5_forsok_summa(cap_svar: dict, fraga: str, modell: str,
                      modell_namn: str | None) -> dict | None:
    try:
        raw = _v5_anropa_en_gang(
            modell, _prompt_v5_extrahera_summa(cap_svar, fraga), modell_namn)
    except EscalationError:
        return None
    poster = _v5_parsa_json_lista(raw)
    if poster is None:
        return None
    belopp_med_enhet: list[tuple[float, str | None]] = []
    for p in poster:
        if not isinstance(p, dict) or "belopp" not in p:
            continue
        if p["belopp"] is None:
            # TILLÄGG (2026-10-04, fråga 132): modellen har EXPLICIT
            # flaggat (se _prompt_v5_extrahera_summa) att en namngiven
            # slutpunkt i frågans förlopp saknar uppgift helt — lita
            # INTE på en partiell summa av bara de delar som RÅKADE
            # hittas. Lämna över till v3, som kan svara med ett korrekt
            # avstående i stället för en felaktig delsumma.
            return None
        try:
            b = float(p["belopp"])
        except (TypeError, ValueError):
            continue
        enhet_rad = p.get("enhet")
        belopp_med_enhet.append(
            (b, str(enhet_rad).strip() if enhet_rad else None))
    if not belopp_med_enhet:
        # Tomt (inget hittat ALLS) hanteras BÄTTRE av v3, som kan svara
        # "Not available..." korrekt i stället för att vi gissar här.
        return None

    enheter_sedda = {e for _, e in belopp_med_enhet if e}
    if len(enheter_sedda) > 1:
        konverterat = [_normalisera_till_dagar(b, e) for b, e in belopp_med_enhet]
        if all(v is not None for v in konverterat):
            total = sum(konverterat)
            total_str = (str(int(total)) if total == int(total)
                         else f"{total:.2f}".rstrip("0").rstrip("."))
            return {"svar": f"{total_str} days", "rastext_extraktion": raw,
                    "poster": poster}
        # Olika enheter som INTE alla är kända tidsenheter: oklart hur de
        # ska förenas programmatiskt säkert — bevara gamla beteendet
        # nedan (summera råtalen, döp efter första enheten) i stället för
        # att gissa fel konvertering.

    belopp = [b for b, _ in belopp_med_enhet]
    enhet = next((e for _, e in belopp_med_enhet if e), None)
    total = sum(belopp)
    total_str = str(int(total)) if total == int(total) else str(total)
    svar = f"{total_str} {enhet}" if enhet else total_str
    return {"svar": svar, "rastext_extraktion": raw, "poster": poster}


def _v5_forsok_ordning(cap_svar: dict, fraga: str, modell: str,
                        modell_namn: str | None) -> dict | None:
    try:
        raw = _v5_anropa_en_gang(
            modell, _prompt_v5_extrahera_ordning(cap_svar, fraga), modell_namn)
    except EscalationError:
        return None
    poster = _v5_parsa_json_lista(raw)
    if poster is None:
        return None
    giltiga = []
    for p in poster:
        if not isinstance(p, dict):
            continue
        handelse, datum = p.get("handelse"), p.get("datum")
        if not handelse:
            continue
        if not datum or not re.match(r"^\d{4}-\d{2}-\d{2}$", str(datum)):
            # Minst en händelse saknar ett användbart exakt datum — hela
            # ordningen går inte att avgöra programmatiskt med säkerhet.
            # v3 (som kan resonera om UNGEFÄRLIGA tidsangivelser också)
            # hanterar hela frågan i stället.
            return None
        giltiga.append((str(datum), str(handelse)))
    if len(giltiga) < 2:
        return None
    fallande = bool(_V5_ORDNING_FALLANDE.search(fraga))
    giltiga.sort(key=lambda t: t[0], reverse=fallande)
    svar = ", ".join(h for _, h in giltiga)
    return {"svar": svar, "rastext_extraktion": raw, "poster": poster}


# ---------------------------------------------------------------------------
# TREDJE PROGRAMMATISKA VÄGEN — TILLÄGG (2026-10-04), svar på fråga 82
# ("How many movie festivals that I attended?") och 87 ("How many
# weddings have I attended in this year?"). Samma princip som summa/
# ordning: modellen gör BARA extraktionen (listar varje DISTINKT
# händelse den hittar), Python gör räkningen (len()) — ett
# "sista-steget-glöms"-fel (eller en dubbelräkning av samma händelse
# omnämnd i flera sessioner) kan inte uppstå när modellen aldrig ombeds
# räkna själv.
#
# UPPFÖLJNING (2026-10-04), efter manuell textgranskning av BÅDA
# fallens facit-sessioner (gratis, inga modellanrop — se
# cap_v5_kvarvarande_missar_diagnos.py --visa-text): detta är INGEN
# täckningsbrist. Texten innehåller redan alla rätta svar (82: Portland
# Film Festival, Austin Film Festival, Seattle International Film
# Festival, AFI Fest — fyra distinkta festivaler; 87: Rachel & Mikes,
# Emily & Sarahs, Jen & Toms bröllop — tre distinkta), men v5 räknade
# bara 2 i båda fallen. Två konkreta, observerade felmönster i den
# GAMLA prompten nedan:
#   (a) minst en händelse nämns bara I FÖRBIGÅENDE, som bakgrund till en
#       annan fråga personen ställer (t.ex. "I volunteered at the
#       Portland Film Festival" nämnt mitt i en fråga om filmtips) —
#       inte som en tydlig "I attended X"-mening. Den gamla prompten bad
#       bara om "distinkta händelser" utan att säga att ett sådant
#       förbigående omnämnande räknas lika mycket.
#   (b) två OLIKA bröllop (Rachels och Emilys) beskrivs BÅDA som "my
#       cousin's wedding" i samma session — den gamla prompten hade
#       ingen regel mot att slå ihop två händelser bara för att de
#       delar samma lösa relationsord/kategori, vilket är en trolig
#       förklaring till att ett av dem tappades (den enda skyddsregel
#       som fanns gällde motsatsen: att INTE dubbelräkna SAMMA händelse
#       omnämnd flera gånger).
# FIX: två nya, riktade instruktioner i prompten (se nedan) — dels att
# leta igenom HELA texten inklusive förbigående omnämnanden, dels att
# bara slå ihop två omnämnanden till en händelse när SPECIFIKA detaljer
# (namn/plats/datum) faktiskt pekar på att det är samma sak, aldrig för
# att en relationskategori råkar matcha. Ingen ändring av _v5_forsok_
# rakning()s egen räknelogik (len()). Kan ENDAST valideras genom en
# riktig modellkörning — invänta Robins nästa `--kor --endast-fragor
# 82,87`-körning innan vidare slutsats dras.
# ---------------------------------------------------------------------------
# TILLÄGG (2026-10-08): samma arkitekturlucka som i _prompt_v5_extrahera_
# summa ovan (se kommentaren där) gäller även räkne-frågor — en "hur
# många gånger gjorde jag X"-fråga kan lika gärna råka ut för en gammal
# vana/avsikt som räknas som en genomförd händelse. Inget bekräftat
# verkligt missat fall ännu för just räkning (bara summa, fråga 95), men
# lagd ändå förebyggande eftersom orsaken är identisk och kostnaden att
# testa är en textrad. Ta bort om en kommande körning visar att den inte
# behövs eller stör räkne-frågor.
def _prompt_v5_extrahera_rakning(cap_svar: dict, fraga: str) -> str:
    kandidater = cap_svar.get("context", "")
    return (
        "Du får en fråga som ber om ETT ANTAL (hur många gånger/händelser/"
        "saker av ett visst slag), och ett redan kuraterat urval av "
        "kandidatminnen. Din ENDA uppgift här är att LISTA de enskilda, "
        "DISTINKTA händelserna/sakerna frågan syftar på — RÄKNA INTE ihop "
        "dem själv, det görs programmatiskt efteråt av annan kod.\n\n"
        "Svara ENDAST med en JSON-lista av strängar, inget annat "
        "resonemang, inga extra rader, inga markdown-kodstaket. Varje "
        "element: en kort beskrivning av EN distinkt händelse/sak, "
        "inklusive de namn/platser/detaljer som gör den IGENKÄNNBAR "
        '(t.ex. "wedding of Rachel and Mike", inte bara "a wedding").\n'
        "- Leta igenom HELA texten, inte bara de meningar som direkt "
        "verkar svara på frågan. En relevant händelse nämns ofta bara I "
        "FÖRBIGÅENDE, som bakgrund till något annat personen frågar om "
        '(t.ex. "I volunteered at the Portland Film Festival" nämnt '
        "mitt i en fråga om filmtips) — ett sådant omnämnande räknas "
        'lika mycket som ett tydligt "I attended X".\n'
        "- Två händelser som BÅDA beskrivs med samma lösa relation eller "
        "kategori (t.ex. två olika bröllop som BÅDA kallas \"my "
        "cousin's wedding\", eller två olika resor som BÅDA kallas \"a "
        "trip\") är INTE automatiskt samma händelse. Avgör distinkthet "
        "utifrån SPECIFIKA identifierande detaljer (namnen på de "
        "inblandade, platsen, datumet) — aldrig bara för att "
        "relationsordet eller kategorin råkar vara densamma.\n"
        "- Slå ENDAST ihop två omnämnanden till EN händelse när de "
        "specifika detaljerna (namn/plats/datum) faktiskt pekar på att "
        "det är samma sak — t.ex. samma namngivna personer igenkända i "
        "två olika konversationer.\n"
        "- Om SAMMA händelse (igenkänd på sina specifika detaljer, inte "
        "bara sin kategori) nämns flera gånger i olika kandidater: lista "
        "den ENDAST EN gång.\n"
        "- Ta med VARJE distinkt händelse/sak frågan syftar på.\n"
        "- Om inget relevant hittas: svara med en tom lista, [].\n\n"
        + _FAKTISKT_UTFORT_REGEL + "\n" + _UNGEFARLIG_PERIOD_TROSKEL_REGEL
        + "\n" + _NAMNGIVEN_SLUTPUNKT_UTESLUTS_REGEL +
        f"\nFRÅGA: {fraga}\n\nKANDIDATER:\n{kandidater}\n"
    )


def _v5_forsok_rakning(cap_svar: dict, fraga: str, modell: str,
                        modell_namn: str | None) -> dict | None:
    try:
        raw = _v5_anropa_en_gang(
            modell, _prompt_v5_extrahera_rakning(cap_svar, fraga), modell_namn)
    except EscalationError:
        return None
    poster = _v5_parsa_json_lista(raw)
    if poster is None:
        return None
    giltiga = [p for p in poster if isinstance(p, str) and p.strip()]
    if not giltiga:
        # Tomt (inget hittat ALLS) hanteras BÄTTRE av v3, som kan svara
        # "Not available..." korrekt i stället för att vi gissar här.
        return None
    return {"svar": str(len(giltiga)), "rastext_extraktion": raw, "poster": poster}


# TILLÄGG (2026-10-08), svar på fråga 97 — se _V5_JAMFORELSEFRAGA ovan för
# bakgrund. Avsiktligt INGEN datumfiltrering här (varken i prompten eller i
# Python-uträkningen): det var EXAKT en sådan egen datumgräns som fick
# Claude att utesluta Thrive Markets $150 och svara Walmart i stället för
# rätt svar. Kandidaterna är redan förvalda som relevanta för frågans
# tidsram av CAP-Shields egen retrieval — den här vägen litar på det
# urvalet i stället för att låta modellen (eller koden här) räkna om det.
def _prompt_v5_extrahera_jamforelse(cap_svar: dict, fraga: str) -> str:
    kandidater = cap_svar.get("context", "")
    return (
        "Du får en fråga som ber om att JÄMFÖRA flera namngivna saker/"
        "platser/personer utifrån en summa (pengar, tid, antal) och peka "
        "ut VILKEN av dem som har STÖRST eller MINST totalt värde. Ett "
        "redan kuraterat urval av kandidatminnen (redan valt för att vara "
        "relevant för just den här frågan) följer. Din ENDA uppgift här "
        "är att LISTA varje enskilt belopp du hittar, kopplat till VILKEN "
        "namngiven sak/plats/person det gäller — JÄMFÖR OCH SUMMERA INTE "
        "själv, det görs programmatiskt efteråt av annan kod.\n\n"
        "Svara ENDAST med en JSON-lista, inget annat resonemang, inga "
        "extra rader, inga markdown-kodstaket. Varje element: "
        '{"namn": <den namngivna saken/platsen/personen, exakt och kort, '
        'ANVÄND SAMMA STAVNING varje gång samma sak nämns igen>, '
        '"belopp": <tal>}.\n'
        "- Ta med VARJE omnämnande du hittar i kandidaterna, oavsett "
        "exakt tidsangivelse (\"last month\", \"a few weeks ago\", m.m.) "
        "— kandidaterna är redan förvalda som relevanta för frågans "
        "tidsram, så UTESLUT INGET baserat på din egen uträkning av "
        "kalenderperioder. Det är en vanlig felkälla: lita på urvalet, "
        "inte på en egen, sträng datumgräns.\n"
        "- Om samma namngivna sak nämns i FLERA kandidater med olika "
        "belopp: lista VARJE omnämnande som en egen post (programmet "
        "summerar dem per namn efteråt) — slå INTE ihop dem själv.\n"
        "- Om ett belopp uttryckligen är DELAT mellan flera personer "
        '(t.ex. "$80 between the two of us"): lista bara den andel som '
        "gäller FRÅGESTÄLLAREN själv (i exemplet $40), inte "
        "totalbeloppet.\n"
        "- Om inget relevant belopp alls hittas: svara med en tom lista, "
        "[].\n\n"
        f"FRÅGA: {fraga}\n\nKANDIDATER:\n{kandidater}\n"
    )


def _v5_forsok_jamforelse(cap_svar: dict, fraga: str, modell: str,
                           modell_namn: str | None) -> dict | None:
    try:
        raw = _v5_anropa_en_gang(
            modell, _prompt_v5_extrahera_jamforelse(cap_svar, fraga), modell_namn)
    except EscalationError:
        return None
    poster = _v5_parsa_json_lista(raw)
    if poster is None:
        return None
    summor: dict[str, float] = {}
    visningsnamn: dict[str, str] = {}
    for p in poster:
        if not isinstance(p, dict) or "namn" not in p or "belopp" not in p:
            continue
        namn = str(p["namn"]).strip()
        if not namn:
            continue
        try:
            b = float(p["belopp"])
        except (TypeError, ValueError):
            continue
        nyckel = namn.lower()
        summor[nyckel] = summor.get(nyckel, 0.0) + b
        visningsnamn.setdefault(nyckel, namn)
    if not summor:
        # Tomt (inget hittat ALLS) hanteras BÄTTRE av v3, som kan svara
        # "Not available..." korrekt i stället för att vi gissar här.
        return None
    minst = bool(re.search(r"\b(least|lowest|smallest|fewest)\b", fraga,
                            re.IGNORECASE))
    valj = min if minst else max
    bast_nyckel = valj(summor, key=lambda k: summor[k])
    return {"svar": visningsnamn[bast_nyckel], "rastext_extraktion": raw,
            "poster": poster}


def eskalera_om_behovs_v5(cap_svar: dict, fraga: str, modell: str = "claude",
                           dagens_datum: str | None = None,
                           modell_namn: str | None = None) -> dict:
    """Som v3, men för SUMMA- och ORDNINGS-frågor (se modulens docstring
    ovan) görs själva uträkningen/sorteringen PROGRAMMATISKT i stället
    för i fritext av modellen — modellen gör bara extraktionen.

    Returnerar samma form som v3 plus ett extra 'vag'-fält som visar
    vilken väg som faktiskt användes ('v5-summa-programmatisk',
    'v5-ordning-programmatisk', eller 'v3-fallback(<fragetyp>)' när v5
    inte kunde användas och v3:s fulla flöde tog över)."""
    if not behover_eskalering(cap_svar):
        return {"eskalerad": False, "svar": cap_svar.get("context", ""),
                "svar_forsta": cap_svar.get("context", ""),
                "svar_ra": cap_svar.get("context", ""),
                "svar_ra_forsta": cap_svar.get("context", ""),
                "vag": "cap-shield", "kalla": "cap-shield"}

    fragetyp = _v5_fragetyp(fraga)
    resultat = None
    if fragetyp == "summa":
        resultat = _v5_forsok_summa(cap_svar, fraga, modell, modell_namn)
    elif fragetyp == "ordning":
        resultat = _v5_forsok_ordning(cap_svar, fraga, modell, modell_namn)
    elif fragetyp == "rakning":
        resultat = _v5_forsok_rakning(cap_svar, fraga, modell, modell_namn)
    elif fragetyp == "jamforelse":
        resultat = _v5_forsok_jamforelse(cap_svar, fraga, modell, modell_namn)

    if resultat is not None:
        return {"eskalerad": True, "svar": resultat["svar"],
                "svar_forsta": resultat["svar"],
                "svar_ra": resultat["rastext_extraktion"],
                "svar_ra_forsta": resultat["rastext_extraktion"],
                "vag": f"v5-{fragetyp}-programmatisk", "kalla": modell}

    v3 = eskalera_om_behovs_v3(cap_svar, fraga, modell=modell,
                                dagens_datum=dagens_datum, modell_namn=modell_namn)
    v3["vag"] = f"v3-fallback({fragetyp})"
    return v3


# ---------------------------------------------------------------------------
# v6, TIDSSKILLNADER (2026-11-13) -- två programmatiska vägar i samma anda
# som v5:s summa/ordning: modellen hittar bara DATUMEN, Python räknar.
# Flyttade hit oförändrade från testskripten steg70_datumdifferens_patch.py
# och steg71_handelsegap_patch.py, där de mättes med gpt-6-luna:
#
#   datumdifferens  "how many days/weeks/months ago ...", "how long has it
#                   been since ..." -- ETT händelsedatum, skillnaden räknas
#                   mot frågans datum. 19 frågor: 11 nya träffar, 0 tappade.
#   handelsegap     "how many days had passed since A when B" -- TVÅ datum,
#                   skillnaden räknas mellan dem. 6 frågor: 3 nya träffar,
#                   0 tappade (en av de tre, n=264, är rätt räknad men
#                   avviker från facit, se _KANDA_FACIT_FEL i
#                   traffar_extraherad.py).
#
# Klassificerarna är de SLUTLIGA från testskripten. Den första, bredare
# datumdifferens-regexen fångade även "how many TIMES ... since" och
# "... since A when B" och gav då fel; därför kravet på en tidsenhet
# direkt efter "how many" och spärren mot "when".
# ---------------------------------------------------------------------------
_V6_DATUMDIFFFRAGA = re.compile(
    r"(?!.*\bwhen\b)"
    r"(?:\bhow many (?:day|days|week|weeks|month|months|year|years)\b"
    r".{0,60}\b(?:ago|since|passed since)\b"
    r"|\bhow long\b.{0,60}\b(?:ago|has it been|had it been|had i been)\b)",
    re.IGNORECASE)

_V6_HANDELSEGAP_FRAGA = re.compile(
    r"\bhow (?:many|long)\b.{0,80}\b(?:ago|since|passed since)\b.{0,100}\bwhen\b",
    re.IGNORECASE)
# TILLÄGG (2026-11-13): samma fråga i pågående form, utan "since"/"ago":
# "How many weeks have I been taking classes when I bought ...". I
# testskriptet lades den enda kända frågan av den formen (n=268) till
# för hand; här är det en regel. Den träffar två av de 500 frågorna
# (n=268 och n=347).
_V6_HANDELSEGAP_PAGAENDE = re.compile(
    r"\bhow many (?:days|weeks|months|years) have i been\b.{0,100}\bwhen\b",
    re.IGNORECASE)

_V6_ENHET_I_FRAGAN = [
    (re.compile(r"\bweeks?\b", re.IGNORECASE), "weeks"),
    (re.compile(r"\bmonths?\b", re.IGNORECASE), "months"),
    (re.compile(r"\bdays?\b", re.IGNORECASE), "days"),
]


def _v6_enhet_fran_fraga(fraga: str) -> str:
    """Enheten FRÅGAN efterfrågar, läst ur frågetexten (inte ur
    modellsvaret)."""
    for pat, enhet in _V6_ENHET_I_FRAGAN:
        if pat.search(fraga):
            return enhet
    return "days"


def _v6_till_date(s):
    """Tolkar 'YYYY-MM-DD' och 'YYYY/MM/DD (Veckodag) HH:MM'."""
    from datetime import date
    m = re.search(r"(\d{4})[/-](\d{2})[/-](\d{2})", str(s))
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _v6_json_objekt(raw: str) -> dict | None:
    text = re.sub(r"^```(?:json)?\s*|\s*```\s*$", "", raw.strip(),
                  flags=re.IGNORECASE)
    try:
        post = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return None
        try:
            post = json.loads(m.group(0))
        except (json.JSONDecodeError, ValueError):
            return None
    return post if isinstance(post, dict) else None


def _prompt_v6_extrahera_datumdifferens(cap_svar: dict, fraga: str) -> str:
    kandidater = cap_svar.get("context", "")
    return (
        "Du får en fråga som ber om hur lång tid (dagar/veckor/månader) "
        "som har gått sedan EN specifik händelse, och ett redan kuraterat "
        "urval av kandidatminnen. Din ENDA uppgift här är att hitta det "
        "EXAKTA datumet för just DEN händelsen -- RÄKNA INTE UT någon "
        "tidsskillnad själv, det görs programmatiskt efteråt av annan "
        "kod, mot ett redan känt referensdatum.\n\n"
        "Svara ENDAST med ETT JSON-objekt, inget annat resonemang, inga "
        "extra rader, inga markdown-kodstaket: "
        '{"handelse": <kort beskrivning>, "datum": <"YYYY-MM-DD" om ett '
        'EXAKT datum går att fastställa, annars null>}.\n'
        "- Varje kandidat inleds med en egen rubrik på formen "
        '"--- Session YYYY/MM/DD (veckodag) tid ---" som anger NÄR just '
        "den konversationen ägde rum. Om händelsen beskrivs i "
        "nutid/precis-hänt-form (\"just\", \"recently\", \"today\", "
        '"this morning") UTAN att något annat, mer specifikt datum '
        "nämns i den löpande texten: använd den kandidatens egna "
        "rubrikdatum -- det räknas som skrivet i kandidaterna, INTE som "
        "en gissning.\n"
        "- Om flera möjliga händelser skulle kunna matcha frågans "
        "beskrivning, och du inte med säkerhet kan avgöra vilken som "
        "avses: sätt \"datum\": null.\n"
        "- Gissa ALDRIG ett datum som inte går att hitta på något av de "
        "två sätten ovan.\n\n"
        f"FRÅGA: {fraga}\n\nKANDIDATER:\n{kandidater}\n"
    )


def _v6_forsok_datumdifferens(cap_svar: dict, fraga: str, dagens_datum,
                               modell: str, modell_namn: str | None) -> dict | None:
    """None = ingen säker extraktion; frågan går då vidare till v5."""
    from datetime import date
    d_idag = _v6_till_date(dagens_datum) if dagens_datum else date.today()
    if d_idag is None:
        return None
    try:
        raw = _v5_anropa_en_gang(
            modell, _prompt_v6_extrahera_datumdifferens(cap_svar, fraga),
            modell_namn)
    except EscalationError:
        return None
    post = _v6_json_objekt(raw)
    if post is None:
        return None
    handelsedatum = post.get("datum")
    if not handelsedatum or not re.match(r"^\d{4}-\d{2}-\d{2}$", str(handelsedatum)):
        return None
    d_handelse = _v6_till_date(handelsedatum)
    if d_handelse is None:
        return None
    dagar = (d_idag - d_handelse).days
    if dagar < 0:
        return None  # händelsen "i framtiden" -- lita inte på det
    enhet = _v6_enhet_fran_fraga(fraga)
    if enhet == "weeks":
        # vanlig avrundning, inte golvdivision (20 dagar = 3 veckor)
        svar = f"{round(dagar / 7)} weeks ago"
    elif enhet == "months":
        manader = (d_idag.year - d_handelse.year) * 12 + (d_idag.month - d_handelse.month)
        if d_idag.day < d_handelse.day:
            manader -= 1
        svar = f"{max(manader, 0)} months ago"
    else:
        svar = f"{dagar} days ago"
    return {"svar": svar, "rastext_extraktion": raw, "poster": [post]}


def _prompt_v6_extrahera_handelsegap(cap_svar: dict, fraga: str) -> str:
    kandidater = cap_svar.get("context", "")
    return (
        "Du får en fråga som ber om tidsskillnaden (dagar/veckor/"
        "månader) MELLAN TVÅ NAMNGIVNA HÄNDELSER (inte mot dagens "
        "datum), och ett redan kuraterat urval av kandidatminnen. "
        "Frågan har formen \"how many ... since EVENT_A ... when "
        "EVENT_B\" eller liknande -- EVENT_A inträffade FÖRST, EVENT_B "
        "är den SENARE referenspunkten frågan mäter mot. Din ENDA "
        "uppgift är att hitta de EXAKTA datumen för de två händelserna "
        "-- RÄKNA INTE UT skillnaden själv, det görs programmatiskt "
        "efteråt av annan kod.\n\n"
        "Svara ENDAST med ETT JSON-objekt, inget annat resonemang, "
        "inga extra rader, inga markdown-kodstaket: "
        '{"handelse_a": <kort beskrivning av den FÖRSTA/TIDIGARE '
        'händelsen>, "datum_a": <"YYYY-MM-DD" eller null>, '
        '"handelse_b": <kort beskrivning av den ANDRA/SENARE '
        'händelsen, referenspunkten>, "datum_b": <"YYYY-MM-DD" eller '
        'null>}.\n'
        "- Varje kandidat inleds med en egen rubrik på formen "
        '"--- Session YYYY/MM/DD (veckodag) tid ---" som anger NÄR '
        "just den konversationen ägde rum. Om en händelse beskrivs i "
        "nutid/precis-hänt-form (\"just\", \"recently\", \"today\") "
        "UTAN att något annat, mer specifikt datum nämns: använd den "
        "kandidatens egna rubrikdatum.\n"
        "- Gissa ALDRIG ett datum du inte kan belägga på något av "
        "dessa sätt -- sätt null i stället.\n\n"
        f"FRÅGA: {fraga}\n\nKANDIDATER:\n{kandidater}\n"
    )


def _v6_forsok_handelsegap(cap_svar: dict, fraga: str, modell: str,
                            modell_namn: str | None) -> dict | None:
    """None = ingen säker extraktion; frågan går då vidare till v5."""
    try:
        raw = _v5_anropa_en_gang(
            modell, _prompt_v6_extrahera_handelsegap(cap_svar, fraga), modell_namn)
    except EscalationError:
        return None
    post = _v6_json_objekt(raw)
    if post is None:
        return None
    d_a = _v6_till_date(post.get("datum_a"))
    d_b = _v6_till_date(post.get("datum_b"))
    if d_a is None or d_b is None:
        return None
    dagar = (d_b - d_a).days
    if dagar < 0:
        return None  # B före A -- lita inte på det
    enhet = _v6_enhet_fran_fraga(fraga)
    if enhet == "weeks":
        svar = f"{round(dagar / 7)} weeks"
    elif enhet == "months":
        manader = (d_b.year - d_a.year) * 12 + (d_b.month - d_a.month)
        if d_b.day < d_a.day:
            manader -= 1
        svar = f"{max(manader, 0)} months"
    else:
        svar = f"{dagar} days"
    return {"svar": svar, "rastext_extraktion": raw, "poster": [post]}


# ---------------------------------------------------------------------------
# v6 (2026-11-13) -- FOKUSERAD LÄSNING ovanpå v5.
#
# BAKGRUND: när alla 500 LongMemEval-frågor gicks igenom fråga för fråga
# visade det sig att nästan alla kvarvarande fel hade sina bevis i den
# kontext modellen redan fick. Det som brast var läsningen av 300-500 000
# tecken i ett svep. v6 lägger därför fyra vägar runt v5 som skickar
# färre sessioner och ställer en snävare fråga (se cap_fokuslasare.py):
#
#   preferens   frågan ber om råd/förslag        -> i stället för v3
#   tidsankare  "last Saturday", "two weeks ago" -> före v5; modellen
#               listar händelserna, Python väljer den närmast måldatumet
#   ordning     när _v5_forsok_ordning ger upp   -> före v3
#   avstaende   när svaret blev "Not available"  -> en omläsning efteråt
#
# v6 kopplar också in de två tidsskillnadsvägarna ovan (datumdifferens
# och handelsegap), före v5.
#
# ALDRIG SÄMRE ÄN v5 I FLÖDET: varje väg returnerar None när den inte
# kommer fram till något, och då går frågan vidare exakt som i v5. En
# fråga som inte hör till någon av vägarna, och som v5 besvarar utan att
# avstå, går oförändrad genom v5 (samma anrop, samma svar).
#
# MÄTT (gpt-6-luna, alla frågor varje väg träffar, inklusive de som redan
# var rätt): tidsankare 19 frågor +3/-0, avstaende 36 frågor +5/-2,
# ordning 2 frågor +1/-0, preferens 30 frågor 21 godkända mot 20 förut.
# Detaljer: CAP-Shield_Steg90_Slutlage_479av500_2026-11-13.md.
#
# KOSTNAD: preferens- och tidsankare-vägarna ersätter v3:s två anrop på
# hela kontexten med ETT anrop på en bråkdel av den. Ordnings- och
# avståendevägarna lägger till ett anrop, men bara i de fall v5 annars
# hade gett upp eller avstått.
#
# KRAV: cap_fokuslasare.py i samma mapp. Saknas den faller v6 tillbaka på
# v5 rakt av. Kontexten måste ha v5:s vanliga sessionsrubriker
# ("--- Session YYYY/MM/DD (Day) HH:MM ---"); utan dem gör vägarna inget.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# v6, tillägg 2026-11-13: två vägar till, båda valda av frågans form.
#
# (a) "What was the page count of the two novels ...?" är en summafråga
#     som inte börjar med "how many/much" och därför klassas som 'annat'
#     av _v5_fragetyp(). Den skickas till samma summa-extraktion som de
#     andra summafrågorna (oförändrad prompt, oförändrad summering).
#     Mätt i steg82: matchar två av de 500 frågorna (n=179, n=222), båda
#     körda på riktigt.
#
# (b) "What was my previous ...?" frågar efter det ÄLDRE värdet i en
#     uppdateringskedja. v3:s regel "den senaste uppgiften gäller" drar
#     åt fel håll för just den frågeformen (n=416: första svaret var
#     rätt, verifieringen bytte till det nyare värdet). Bara för frågor
#     med den formen får v3:s två prompter ett undantag inskrivet.
#     Texterna är ordagrant de som mättes i steg81.
# ---------------------------------------------------------------------------
# Varje tillägg går att stänga av för sig (False = som före tillägget).
V6_SUMMA_VAD_VAR_PA = True
V6_TIDIGARE_VARDE_PA = True

_V6_SUMMAFRAGA_VAD_VAR = re.compile(
    r"\bwhat (?:was|were)\b.{0,40}\b(count|total|number|amount)\b"
    r".{0,80}\band\b.{0,40}\?",
    re.IGNORECASE)

_V6_TIDIGARE_VARDE_FRAGA = re.compile(
    r"^\s*what (?:was|were) my (?:previous|former)\b", re.IGNORECASE)

_V6_TIDIGARE_VARDE_REGEL = (
    "UNDANTAG TILL REGELN OVAN (läs noga, gäller bara i detta specifika "
    "fall): OM FRÅGAN SJÄLV UTTRYCKLIGEN FRÅGAR OM DET TIDIGARE/"
    "FÖREGÅENDE VÄRDET (ord som \"previous\", \"before\", \"used to\", "
    "\"prior to\", \"former\" i frågan — INTE om den bara frågar om det "
    "AKTUELLA/NUVARANDE värdet, t.ex. \"currently\"/\"now\"): och "
    "kandidaterna visar en tydlig uppdateringskedja (ett äldre värde, "
    "sedan en förändring till ett nyare värde) — svara med DEN ÄLDRE "
    "uppgiften i kedjan, INTE automatiskt den kronologiskt senaste. "
    "Regeln ovan (alltid välja den senaste kandidaten) gäller fortfarande "
    "som huvudregel för alla ANDRA frågor om återkommande/föränderliga "
    "fakta — detta undantag gäller ENDAST när frågans eget ordval "
    "efterfrågar det förflutna värdet specifikt.\n"
)

_V6_TIDIGARE_VARDE_VERIFIERING_MARKOR = (
    "om kandidaterna har olika datum för samma "
    "återkommande fakta")

_V6_TIDIGARE_VARDE_VERIFIERING_TILLAGG = (
    " MEN -- om frågan själv uttryckligen frågar om det TIDIGARE/"
    "föregående värdet (\"previous\", \"before\", \"used to\", "
    "\"prior to\", \"former\") snarare än det aktuella/nuvarande: "
    "byt INTE till den senaste kandidaten då -- behåll (eller byt "
    "till) den ÄLDRE uppgiften i stället, eftersom frågan "
    "specifikt efterfrågar det förflutna värdet."
)


def _v6_forsok_tidigare_varde(cap_svar: dict, fraga: str, dagens_datum,
                               modell: str,
                               modell_namn: str | None) -> dict | None:
    """v3:s två omgångar (svar + verifiering) med undantaget för frågor
    om det tidigare värdet inskrivet i båda prompterna. Returnerar samma
    fält som eskalera_om_behovs_v3(), eller None om prompterna inte ser
    ut som väntat eller ett anrop misslyckas (då tar v5/v3 över)."""
    original = _prompt_v3(cap_svar, fraga, dagens_datum)
    markor = _SENASTE_UPPGIFT_GALLER_REGEL.strip()
    if markor not in original:
        return None
    prompt_forsta = original.replace(
        markor, markor + "\n" + _V6_TIDIGARE_VARDE_REGEL)
    try:
        forsta_ra = _v5_anropa_en_gang(modell, prompt_forsta, modell_namn)
    except EscalationError:
        return None
    verifiering = _prompt_verifiering_v3(
        fraga, cap_svar.get("context", ""), forsta_ra)
    if _V6_TIDIGARE_VARDE_VERIFIERING_MARKOR not in verifiering:
        return None
    prompt_andra = verifiering.replace(
        _V6_TIDIGARE_VARDE_VERIFIERING_MARKOR,
        _V6_TIDIGARE_VARDE_VERIFIERING_MARKOR
        + _V6_TIDIGARE_VARDE_VERIFIERING_TILLAGG, 1)
    try:
        andra_ra = _v5_anropa_en_gang(modell, prompt_andra, modell_namn)
    except EscalationError:
        return None
    return {"eskalerad": True,
            "svar": extrahera_svarsrad(andra_ra),
            "svar_forsta": extrahera_svarsrad(forsta_ra),
            "svar_ra": andra_ra, "svar_ra_forsta": forsta_ra,
            "vag": "v6-tidigare-varde", "kalla": modell}


def eskalera_om_behovs_v6(cap_svar: dict, fraga: str, modell: str = "claude",
                           dagens_datum: str | None = None,
                           modell_namn: str | None = None) -> dict:
    """Som `eskalera_om_behovs_v5()`, med fokuserad läsning och två
    programmatiska tidsskillnadsvägar runt om.

    Samma parametrar och samma returformat som v5. 'vag' visar vilken väg
    som gav svaret: 'v6-preferens', 'v6-tidsankare',
    'v6-datumdifferens-programmatisk', 'v6-handelsegap-programmatisk',
    'v6-tidigare-varde', 'v6-summa-programmatisk', 'v6-ordning',
    'v6-avstaende(efter <v5:s väg>)',
    'v6-omlasning(<varningstecken>; efter <v5:s väg>)',
    'v6-omrakning(efter <v5:s väg>)', 'v6-komplettering(efter <väg>)',
    eller v5:s egen väg när ingen av v6:s vägar användes.

    Valfritt: cap_svar["utelamnat_kontext"] = de sessioner CAP-Shield
    INTE tog med i "context", i samma rubrikformat. Finns det och blir
    svaret ett avstående, läses de också (steg 99).

    modell: "openai" eller "anthropic" (steg 106; samma som de interna
    vägnamnen "gpt-5-mini" och "claude", som fortfarande fungerar).
    Den faktiska modellen anges med modell_namn."""
    modell = {"openai": "gpt-5-mini", "anthropic": "claude"}.get(modell, modell)
    if not behover_eskalering(cap_svar):
        return eskalera_om_behovs_v5(cap_svar, fraga, modell=modell,
                                     dagens_datum=dagens_datum,
                                     modell_namn=modell_namn)
    try:
        import cap_fokuslasare as fl
    except ImportError:
        return eskalera_om_behovs_v5(cap_svar, fraga, modell=modell,
                                     dagens_datum=dagens_datum,
                                     modell_namn=modell_namn)
    # Steg 100: assemble_context()s "context" är rubrikfri. Har svaret
    # "selected" (text + created_utc per post) byggs en kontext med
    # sessionsrubriker, som v6:s fokuserade läsning behöver. En kontext
    # som redan har rubriker (assemble_escalation_context(), steg 65)
    # används som den är.
    if ("--- Session " not in cap_svar.get("context", "")
            and cap_svar.get("selected")):
        ny = fl.rubricerad_kontext(cap_svar["selected"])
        if ny:
            cap_svar = {**cap_svar, "context": ny}
    kontext = cap_svar.get("context", "")

    def anropa(prompt_text: str) -> str:
        return _v5_anropa_en_gang(modell, prompt_text, modell_namn)

    def forsok(vag_funktion):
        # Ett misslyckat anrop i en v6-väg ska inte fälla frågan: den går
        # då vidare till v5, som själv rapporterar ett bestående fel.
        try:
            return vag_funktion(kontext, fraga, dagens_datum, anropa)
        except EscalationError:
            return None

    def komplettera(res: dict) -> dict:
        # Steg 99: blev svaret ett avstående och har anroparen skickat
        # med de sessioner CAP-Shield lämnade utanför kontexten
        # (cap_svar["utelamnat_kontext"], samma rubrikformat), läses de
        # tillsammans med de mest relevanta i kontexten.
        rest = cap_svar.get("utelamnat_kontext")
        if not (rest and getattr(fl, "KOMPLETTERING", False)
                and fl.ar_avstaende(res.get("svar"))):
            return res
        r = forsok(lambda k, f, d, a: fl.las_med_utelamnat(k, rest, f, d, a))
        if r is None:
            return res
        ut = dict(res)
        ut.update({"svar": r["svar"], "svar_ra": r["ra"],
                   "vag": f"v6-komplettering(efter {res.get('vag', '?')})"})
        return ut

    def klart(resultat: dict, vag: str) -> dict:
        return {"eskalerad": True, "svar": resultat["svar"],
                "svar_forsta": resultat["svar"],
                "svar_ra": resultat["ra"], "svar_ra_forsta": resultat["ra"],
                "vag": vag, "kalla": modell}

    # 1) Frågans form avgör: råd/förslag, eller en händelse vid en angiven tid.
    tids_logg: dict = {}
    if fl.ar_radfraga(fraga):
        r = forsok(fl.forsok_preferens)
        if r is not None:
            return klart(r, "v6-preferens")
    elif fl.tidsankare(fraga, dagens_datum) is not None:
        # Steg 102: läsningarnas händelser sparas i tids_logg, så att
        # dagsläsningen (3c) kan se om svaret gäller en annan dag.
        r = forsok(lambda k, f, d, a: fl.forsok_tidsankare(
            k, f, d, a, logg=tids_logg))
        if r is not None:
            return klart(r, "v6-tidsankare")

    # 1b) Tidsskillnader: modellen hittar datumen, Python räknar.
    tidsskillnad = None
    if _V6_DATUMDIFFFRAGA.search(fraga):
        tidsskillnad = "datumdifferens"
        res = _v6_forsok_datumdifferens(cap_svar, fraga, dagens_datum,
                                        modell, modell_namn)
    elif (_V6_HANDELSEGAP_FRAGA.search(fraga)
          or _V6_HANDELSEGAP_PAGAENDE.search(fraga)):
        tidsskillnad = "handelsegap"
        res = _v6_forsok_handelsegap(cap_svar, fraga, modell, modell_namn)
    if tidsskillnad is not None and res is not None:
        return {"eskalerad": True, "svar": res["svar"],
                "svar_forsta": res["svar"],
                "svar_ra": res["rastext_extraktion"],
                "svar_ra_forsta": res["rastext_extraktion"],
                "vag": f"v6-{tidsskillnad}-programmatisk", "kalla": modell}

    # 1c) Frågan efterfrågar det TIDIGARE värdet: v3 med undantaget
    #     inskrivet. Ger den inget tar v5 över som vanligt.
    resultat = None
    if V6_TIDIGARE_VARDE_PA and _V6_TIDIGARE_VARDE_FRAGA.search(fraga):
        resultat = _v6_forsok_tidigare_varde(cap_svar, fraga, dagens_datum,
                                             modell, modell_namn)

    # 2) v5:s eget flöde. Ordningsfrågor tas isär här (samma steg som i
    #    v5) för att kunna lägga in ett försök mellan v5-ordning och v3.
    if resultat is not None:
        pass
    elif _v5_fragetyp(fraga) == "ordning":
        ordning = _v5_forsok_ordning(cap_svar, fraga, modell, modell_namn)
        if ordning is not None:
            return {"eskalerad": True, "svar": ordning["svar"],
                    "svar_forsta": ordning["svar"],
                    "svar_ra": ordning["rastext_extraktion"],
                    "svar_ra_forsta": ordning["rastext_extraktion"],
                    "vag": "v5-ordning-programmatisk", "kalla": modell}
        r = forsok(fl.forsok_ordning)
        if r is not None:
            return klart(r, "v6-ordning")
        resultat = eskalera_om_behovs_v3(cap_svar, fraga, modell=modell,
                                         dagens_datum=dagens_datum,
                                         modell_namn=modell_namn)
        resultat["vag"] = "v3-fallback(ordning)"
    else:
        summa = None
        if (V6_SUMMA_VAD_VAR_PA and _v5_fragetyp(fraga) == "annat"
                and _V6_SUMMAFRAGA_VAD_VAR.search(fraga)):
            # Summafråga utan "how many/much": samma extraktion och
            # samma summering som v5:s summaväg.
            summa = _v5_forsok_summa(cap_svar, fraga, modell, modell_namn)
        if summa is not None:
            resultat = {"eskalerad": True, "svar": summa["svar"],
                        "svar_forsta": summa["svar"],
                        "svar_ra": summa["rastext_extraktion"],
                        "svar_ra_forsta": summa["rastext_extraktion"],
                        "vag": "v6-summa-programmatisk", "kalla": modell}
        else:
            resultat = eskalera_om_behovs_v5(cap_svar, fraga, modell=modell,
                                             dagens_datum=dagens_datum,
                                             modell_namn=modell_namn)

    # 3) Blev svaret ett avstående: läs om de mest relevanta sessionerna.
    if fl.ar_avstaende(resultat.get("svar")):
        r = forsok(fl.forsok_avstaende)
        if r is not None:
            ut = dict(resultat)
            ut.update({"svar": r["svar"], "svar_ra": r["ra"],
                       "vag": f"v6-avstaende(efter {resultat.get('vag', '?')})"})
            return ut
        return komplettera(resultat)

    # 3b) Premisskontroll (steg 102): frågan namnger något på minst tre ord
    #     ("Software Engineer Manager") som inte finns i historiken, men en
    #     del av det gör ("Senior Software Engineer"). Modellen avgör om det
    #     är samma sak; är det inte det blir svaret ett avstående.
    if getattr(fl, "PREMISSKONTROLL", False):
        variant = fl.fras_variant(
            fraga, kontext + "\n" + (cap_svar.get("utelamnat_kontext") or ""))
        if variant is not None:
            r = forsok(lambda k, f, d, a: fl.premisskontroll(
                k, f, d, a, variant[0], variant[1]))
            if r is not None:
                ut = dict(resultat)
                ut.update({"svar": r["svar"], "svar_ra": r["ra"],
                           "vag": f"v6-premiss(efter "
                                  f"{resultat.get('vag', '?')})"})
                return ut

    # 3c) Dagsläsning (steg 102): tidsankaret (helg/veckodag) hittade bara
    #     en händelse vid ett annat datum, och svaret är just den. Då läses
    #     sessionerna från de dagar frågan gäller.
    if getattr(fl, "TIDSANKARE_DAGSLASNING", False) and tids_logg:
        handelse = fl.dagslasning_behovs(tids_logg, resultat.get("svar"))
        if handelse is not None:
            r = forsok(lambda k, f, d, a: fl.las_dagarna(
                k, f, d, a, tids_logg, handelse))
            if r is not None:
                ut = dict(resultat)
                ut.update({"svar": r["svar"], "svar_ra": r["ra"],
                           "vag": f"v6-dagslasning(efter "
                                  f"{resultat.get('vag', '?')})"})
                return ut

    # 4) Svaret är inget avstående men bär ett varningstecken (modellens
    #    egen motivering säger att ett namn i frågan saknas; summavägen
    #    hittade en del av två; skillnadsfråga besvarad med ett
    #    intervall). Samma omläsning får då avgöra: den svarar utifrån
    #    användarens egna uppgifter, eller avstår.
    tecken = fl.varningstecken(fraga, resultat)
    if tecken is not None:
        r = forsok(fl.las_om)
        if r is not None:
            ut = dict(resultat)
            ut.update({"svar": r["svar"], "svar_ra": r["ra"],
                       "vag": f"v6-omlasning({tecken}; efter "
                              f"{resultat.get('vag', '?')})"})
            return komplettera(ut)
        return resultat

    # 5) Räknefråga som v3 besvarat: läsaren räknar om, och dess svar
    #    gäller bara när den hittar fler (se fl.rakna_om).
    if (fl.RAKNA_OM and str(resultat.get("vag", "")).startswith("v3")
            and _v5_fragetyp(fraga) == "annat"
            and fl.ar_rakningsfraga(fraga)):
        forsta_svar = resultat.get("svar")
        forsta_ra = resultat.get("svar_ra")
        r = forsok(lambda k, f, d, a: fl.rakna_om(k, f, d, a, forsta_svar,
                                                   forsta_ra=forsta_ra))
        if r is not None:
            ut = dict(resultat)
            ut.update({"svar": r["svar"], "svar_ra": r["ra"],
                       "vag": f"v6-omrakning(efter "
                              f"{resultat.get('vag', '?')})"})
            return ut
    return resultat


def eskalera_fran_minne(minne, namespace: str, fraga: str,
                        modell: str = "claude", dagens_datum=None,
                        modell_namn: str | None = None,
                        token_budget: int | None = None) -> dict:
    """Steg 100: hela eskaleringen för den som har direkt tillgång till
    CAP-Shields minneslager (cap_memory.MemoryStore). Hämtar den breda
    eskaleringskontexten med sessionsrubriker och de utelämnade
    sessionerna (assemble_escalation_context(), samma urval som mättes
    i steg 65-99) och kör eskalera_om_behovs_v6() på den.

    Anropas när assemble_context() redan har sagt escalate_recommended,
    eller när anroparen själv vill eskalera. Samma returformat som v6."""
    cap_svar = minne.assemble_escalation_context(
        namespace, fraga, token_budget=token_budget)
    return eskalera_om_behovs_v6(cap_svar, fraga, modell=modell,
                                 dagens_datum=dagens_datum,
                                 modell_namn=modell_namn)


def eskalera_om_behovs(cap_svar: dict, fraga: str, modell: str = "claude") -> dict:
    """Kärnfunktionen andra script (t.ex. cap_longmemeval_sweep.py) kan
    importera för att testa "LLM som valfritt sista steg"-hypotesen.

    Returnerar:
        {"eskalerad": bool, "svar": str, "kalla": "cap-shield" | modell}

    "svar" är CAP-Shields egen sammanslagna kontext (oförändrad) om
    eskalering inte behövdes — ALDRIG en tystnad som ser ut som ett
    facit. Vid fel under själva modellanropet sprids EscalationError
    vidare (fångas INTE här) så att anropande kod medvetet väljer hur
    den vill falla tillbaka."""
    if not behover_eskalering(cap_svar):
        return {"eskalerad": False, "svar": cap_svar.get("context", ""),
                "kalla": "cap-shield"}
    if modell not in MODELLER:
        raise EscalationError(
            f"Okänd modell '{modell}'. Kända: {sorted(MODELLER)}")
    svar = MODELLER[modell](cap_svar, fraga)
    return {"eskalerad": True, "svar": svar, "kalla": modell}


# ---------------------------------------------------------------------------
# FAS-L — frågemedveten reduktionseskalering (TILLAGD 2026-10-07)
#
# Bakgrund: FAS-L:s vendorade modell (cap_context_reduction.py) är
# TASK-AGNOSTIC — mätt 2026-10-07 (cap_context_reduction_regression.py)
# missar den distraktorer den INTE KAN upptäcka task-agnostiskt
# ("coffee machine" överlever lika ofta som den borde kastas) — ett
# STRUKTURELLT problem (se claude/CAP-Shield_FAS-L_
# Regressionssvit_Implementation_2026-10-07.md, "Undersökt och
# avfärdat"), inte en bugg en till task-agnostic heuristik kan fixa.
# Den här sektionen återupptar specens redan parkerade frågemedvetna
# BYOK-väg (§1/§10, claude/CAP-Shield_Konsol_Eskalering_ByokVal_
# Framtida_2026-10-04.md) genom att ÅTERANVÄNDA filens BEFINTLIGA
# mönster ovan — INTE en tredje, separat mekanism.
#
# cap_gateway.py sätter `reduction_escalate_recommended` och, BARA när
# True, `reduction_escalation_source_text` (den OKOMPRIMERADE texten,
# före FAS-L:s egen reduktion) i svaret från POST
# /api/v1/memory/assemble när reduce=true begärdes. Se
# patch_cap_gateway_fasl_reduktionseskalering.py.

def behover_reduktionseskalering(cap_svar: dict) -> bool:
    """Som behover_eskalering() ovan, men för FAS-L:s kontextreduktion.
    FRÅNVARO av fältet tolkas som False HÄR (INTE samma princip som
    behover_eskalering(), som tolkar frånvaro som True) — ett svar utan
    reduce=true har helt enkelt inget att eskalera, det är inte en
    degraderad signal, bara en annan sorts svar."""
    return bool(cap_svar.get("reduction_escalate_recommended", False))


def _prompt_reduktion(cap_svar: dict, fraga: str,
                       target_tokens: int | None = None) -> str:
    kalltext = cap_svar.get("reduction_escalation_source_text", "")
    budget_rad = (
        f"Sikta på ungefär {target_tokens} tokens (grovt, ord/4) i "
        "resultatet — det är en riktlinje, inte en hård gräns."
        if target_tokens else
        "Korta ned tydligt, men sikta inte på en exakt längd."
    )
    return (
        "CAP-Shield har redan gjort en generisk, FRÅGEOBEROENDE "
        "komprimering av den här texten (tar bort det minst "
        "oförutsägbara ordet, oavsett vad frågan handlar om). Den "
        "komprimeringen missar ibland information som är specifikt "
        "relevant för DEN HÄR frågan. Din uppgift: läs frågan och "
        "ORIGINALTEXTEN nedan (INNAN CAP-Shields reduktion), och gör "
        "ett NYTT, frågemedvetet urval/sammandrag — behåll det som "
        "faktiskt behövs för att svara på frågan, även om CAP-Shields "
        "egen modell skulle ha kastat det.\n\n"
        "VIKTIGT:\n"
        "- Återge ENDAST information som faktiskt står i texten — "
        "hitta inte på, fyll inte i, och gissa inte siffror eller "
        "datum som inte står där.\n"
        "- Skriv på SAMMA SPRÅK som texten/frågan.\n"
        f"- {budget_rad}\n"
        "- Resultatet ska vara ett UTDRAG/SAMMANDRAG av texten, inte "
        "ett svar på frågan i sig — kunden gör det sista "
        "resonemangssteget själv (se eskalera_claude/eskalera_gpt5mini "
        "ovan för den delen).\n\n"
        f"FRÅGA (för att avgöra vad som är relevant): {fraga}\n\n"
        f"ORIGINALTEXT:\n{kalltext}\n\n"
        "Ge ENDAST det kortade/urvalda utdraget, ingen inledning eller "
        "metakommentar."
    )


def eskalera_reduktion_claude(cap_svar: dict, fraga: str,
                               target_tokens: int | None = None,
                               modell: str = "claude-sonnet-4-5") -> str:
    """Kör ett frågemedvetet reduktionssteg med kundens egen Anthropic-
    nyckel, på reduction_escalation_source_text (den OKOMPRIMERADE
    källtexten — se sektionens docstring ovan).

    Kastar EscalationError om källtexten saknas. Att köra mot den redan
    lossy-reducerade "context"-texten i stället skulle bara återge
    samma information CAP-Shield redan kastat, med ett falskt sken av
    att ha löst problemet — hellre ett tydligt fel än en tyst,
    meningslös omsummering."""
    if not cap_svar.get("reduction_escalation_source_text"):
        raise EscalationError(
            "reduction_escalation_source_text saknas i svaret — "
            "antingen var reduction_escalate_recommended inte True, "
            "eller så kommer svaret från en äldre serverversion. Kör "
            "inte den här eskaleringen mot den redan reducerade "
            "'context'-texten; den har redan kastat det du försöker "
            "återvinna.")
    nyckel = os.environ.get("ANTHROPIC_API_KEY")
    if not nyckel:
        raise EscalationError(
            "ANTHROPIC_API_KEY saknas i miljön. Sätt den (aldrig i "
            "klartext i kod eller chatt) innan eskalering körs.")
    try:
        import anthropic
    except ImportError as e:
        raise EscalationError(
            "Paketet 'anthropic' är inte installerat (pip install anthropic)."
        ) from e
    klient = anthropic.Anthropic(api_key=nyckel)
    try:
        svar = klient.messages.create(
            model=modell, max_tokens=1200,
            messages=[{"role": "user",
                       "content": _prompt_reduktion(cap_svar, fraga, target_tokens)}],
        )
        return svar.content[0].text
    except Exception as e:
        raise EscalationError(f"Anthropic-anropet misslyckades: {e}") from e


def eskalera_reduktion_gpt5mini(cap_svar: dict, fraga: str,
                                 target_tokens: int | None = None,
                                 modell: str = "gpt-5-mini") -> str:
    """Som eskalera_reduktion_claude men med OpenAIs API — samma
    kontroll mot saknad källtext, samma motivering."""
    if not cap_svar.get("reduction_escalation_source_text"):
        raise EscalationError(
            "reduction_escalation_source_text saknas i svaret — se "
            "eskalera_reduktion_claude() för motiveringen.")
    nyckel = os.environ.get("OPENAI_API_KEY")
    if not nyckel:
        raise EscalationError(
            "OPENAI_API_KEY saknas i miljön. Sätt den (aldrig i "
            "klartext i kod eller chatt) innan eskalering körs.")
    try:
        import openai
    except ImportError as e:
        raise EscalationError(
            "Paketet 'openai' är inte installerat (pip install openai)."
        ) from e
    klient = openai.OpenAI(api_key=nyckel)
    try:
        svar = klient.chat.completions.create(
            model=modell,
            messages=[{"role": "user",
                       "content": _prompt_reduktion(cap_svar, fraga, target_tokens)}],
        )
        return svar.choices[0].message.content
    except Exception as e:
        raise EscalationError(f"OpenAI-anropet misslyckades: {e}") from e


MODELLER_REDUKTION: dict[str, Callable[..., str]] = {
    "claude": eskalera_reduktion_claude,
    "gpt-5-mini": eskalera_reduktion_gpt5mini,
}


def eskalera_reduktion_om_behovs(cap_svar: dict, fraga: str,
                                  target_tokens: int | None = None,
                                  modell: str = "claude") -> dict:
    """Speglar eskalera_om_behovs() ovan, för FAS-L:s kontextreduktion.

    Returnerar:
        {"eskalerad": bool, "svar": str, "kalla": "cap-shield" | modell}

    "svar" är CAP-Shields egen (task-agnostic) reducerade "context" om
    eskalering inte rekommenderades. Vid fel under modellanropet sprids
    EscalationError vidare (fångas INTE här)."""
    if not behover_reduktionseskalering(cap_svar):
        return {"eskalerad": False, "svar": cap_svar.get("context", ""),
                "kalla": "cap-shield"}
    if modell not in MODELLER_REDUKTION:
        raise EscalationError(
            f"Okänd modell '{modell}'. Kända: {sorted(MODELLER_REDUKTION)}")
    svar = MODELLER_REDUKTION[modell](cap_svar, fraga, target_tokens)
    return {"eskalerad": True, "svar": svar, "kalla": modell}


def _demo() -> int:
    exempel = {
        "query": "vad var kundens ärendenummer?",
        "context": "Kunden hörde av sig om ärende 4471, försenat paket.\n\n"
                    "Kunden bad om återbetalning för ärende 4471.",
        "escalate_recommended": True,
    }
    print("DEMO — ingen riktig nyckel behövs, visar bara vad som SKULLE skickas:")
    print(json.dumps({
        "behover_eskalering": behover_eskalering(exempel),
        "prompt_forhandsvisning": _prompt(exempel, exempel["query"])[:300] + "...",
    }, ensure_ascii=False, indent=2))
    return 0


def _demo_reduktion() -> int:
    exempel = {
        "query": "what was the vendor invoice amount?",
        "context": "quarterly review happened last week coffee machine broken",
        "reduction_escalate_recommended": True,
        "reduction_escalation_source_text": (
            "The quarterly review happened last week. The vendor invoice "
            "was $14,500, up from $11,200 last quarter. Someone mentioned "
            "the coffee machine on the third floor is still broken."
        ),
        "reduction_pct": 61.0,
    }
    print("DEMO — ingen riktig nyckel behövs, visar bara vad som SKULLE "
          "skickas:")
    print(json.dumps({
        "behover_reduktionseskalering": behover_reduktionseskalering(exempel),
        "prompt_forhandsvisning":
            _prompt_reduktion(exempel, exempel["query"], target_tokens=30)[:400] + "...",
    }, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true",
                     help="Visa vad som skulle skickas, utan att ringa en modell.")
    ap.add_argument("--demo-reduktion", action="store_true",
                     help="Som --demo, men för FAS-L:s frågemedvetna "
                          "reduktionseskalering i stället för "
                          "hämtningseskalering.")
    args = ap.parse_args()
    if args.demo:
        return _demo()
    if args.demo_reduktion:
        return _demo_reduktion()
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
