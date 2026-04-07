"""
real_world_scenario_tests.py

Real-World Macro Shock Scenario Testing Suite
==============================================
Macro Shock Risk Engine — Full Pipeline Demonstration

This file tests the complete Macro Shock Risk Engine across 12 distinct
real-world scenario archetypes drawn from actual market history. Each scenario
exercises the full pipeline: event detection → NLP language intelligence →
market vulnerability scoring → scenario tree construction → composite risk
scoring → portfolio impact translation → alert generation.

Scenarios Covered
-----------------
  1.  OPEC Surprise Production Cut — Oil Price Shock
  2.  Emergency Fed Rate Hike — Hawkish Inflation Shock
  3.  Bank Failure / Sudden Liquidity Crisis (SVB-style)
  4.  Weekend Emergency Fed Rate Cut — Crisis Easing
  5.  Presidential Election Surprise Outcome
  6.  Military Conflict Escalation — Geopolitical Shock
  7.  Surprise CPI Print — Inflation Data Shock
  8.  Sovereign Debt / Credit Contagion Event
  9.  Flash Crash / Market Microstructure Breakdown
 10.  Massive Fiscal Stimulus Announcement
 11.  Currency Crisis — Emerging Market Contagion
 12.  Coordinated Multi-Central-Bank Emergency Action

Usage
-----
    # Run all scenarios with default stress levels
    python real_world_scenario_tests.py

    # Run a specific scenario by number
    python real_world_scenario_tests.py --scenario 3

    # Run all and export results to JSON
    python real_world_scenario_tests.py --export results.json

    # Run with elevated market stress (0.0 = calm, 1.0 = max stress)
    python real_world_scenario_tests.py --stress 0.75

"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

# ── Path resolution: works whether run from repo root or examples/ ──────────
_repo_root = Path(__file__).resolve().parent
_src = _repo_root / "python" / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from macro_shock.data.ingestion import MarketStateBuilder
from macro_shock.event_detection.calendar import MarketCalendar
from macro_shock.orchestration.pipeline import MacroShockPipeline

# ── Terminal colours ─────────────────────────────────────────────────────────
R  = "\033[91m"   # red
Y  = "\033[93m"   # yellow
G  = "\033[92m"   # green
B  = "\033[94m"   # blue
M  = "\033[95m"   # magenta
C  = "\033[96m"   # cyan
W  = "\033[97m"   # white
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"

SEV_COLOUR = {
    "CRITICAL":      R,
    "HIGH":          Y,
    "MEDIUM":        C,
    "LOW":           G,
    "INFORMATIONAL": DIM,
}

ACTION_COLOUR = {
    "EMERGENCY_DERISKING": R,
    "HEDGE":               Y,
    "REDUCE":              C,
    "MONITOR":             G,
    "NO_ACTION":           DIM,
}


# ═══════════════════════════════════════════════════════════════════════════
#  Scenario Definitions
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class Scenario:
    number: int
    name: str
    category: str
    event_time: str            # ISO 8601
    stress_level: float        # Pre-event market stress 0.0–1.0
    raw_event: Dict
    historical_analog: str     # Real-world event this is modelled on
    expected_severity: str     # What we expect the engine to output


# ── 1. OPEC Surprise Production Cut — Oil Price Shock ────────────────────────
SCENARIO_01 = Scenario(
    number=1,
    name="OPEC Surprise Production Cut — Oil Price Shock",
    category="Commodity / Supply Shock",
    event_time="2025-06-06T14:00:00+00:00",
    stress_level=0.40,
    historical_analog="OPEC+ surprise 1.16mb/d cut, April 2023",
    expected_severity="HIGH",
    raw_event={
        "title": "OPEC+ Emergency Ministerial Meeting — Unscheduled Production Cut",
        "institution": "White House",
        "speaker": "White House Press Secretary",
        "speaker_role": "Press Secretary",
        "event_time": "2025-06-06T14:00:00+00:00",
        "description": "Emergency OPEC+ meeting results in surprise production cut.",
        "headline_summary": (
            "OPEC+ announces surprise 2 million barrel-per-day production cut "
            "effective immediately. WTI crude surges 8%. Energy stocks rally. "
            "U.S. Treasury and White House express concern over inflationary impact."
        ),
        "prepared_remarks": (
            "OPEC+ member nations have agreed to an immediate and substantial reduction "
            "in oil production, effective as of this communique. The cut of approximately "
            "two million barrels per day is a significant and unexpected policy action. "
            "The United States government is deeply concerned about the inflationary "
            "implications of this decision. Higher energy prices feed directly into "
            "core inflation and complicate the Federal Reserve's path toward price "
            "stability. We are monitoring the situation and consulting with allies. "
            "The Strategic Petroleum Reserve remains an option. Financial markets "
            "are experiencing significant volatility in response to this announcement. "
            "Elevated energy costs represent a stagflationary headwind — higher "
            "inflation combined with slower growth — a combination the Federal Reserve "
            "will find extremely difficult to navigate. Rate cuts are now off the table "
            "for the foreseeable future."
        ),
        "qa_section": (
            "Q: Will the Fed now have to raise rates again? "
            "A: The Federal Reserve operates independently. However, a sustained "
            "oil price shock of this magnitude will feed into CPI and PCE data "
            "for multiple quarters. Any expectation of near-term rate cuts must "
            "now be reassessed. Q: Is this an economic emergency? "
            "A: It is a significant economic headwind and we are treating it seriously."
        ),
    },
)

# ── 2. Emergency Fed Rate Hike — Hawkish Inflation Shock ─────────────────────
SCENARIO_02 = Scenario(
    number=2,
    name="Emergency Fed Rate Hike — Hawkish Inflation Shock",
    category="Monetary Policy / Rate Shock",
    event_time="2025-09-19T18:30:00+00:00",
    stress_level=0.55,
    historical_analog="FOMC 75bps hike surprise, June 2022",
    expected_severity="HIGH",
    raw_event={
        "title": "FOMC Press Conference — Emergency 100bps Rate Hike",
        "institution": "Federal Reserve",
        "speaker": "Jerome Powell",
        "speaker_role": "Chair",
        "event_time": "2025-09-19T18:30:00+00:00",
        "description": "Fed delivers emergency 100bps rate hike citing unanchored inflation expectations.",
        "headline_summary": (
            "Federal Reserve raises rates by 100bps in emergency session. "
            "Powell: 'We will not allow inflation expectations to become unanchored.' "
            "Rate now at highest level in 40 years. Markets in freefall."
        ),
        "prepared_remarks": (
            "The Federal Open Market Committee has voted to raise the federal funds "
            "rate by 100 basis points. This is an extraordinary action that reflects "
            "the extraordinary inflationary pressures the economy is facing. "
            "Inflation is simply too high. It has been too high for too long. "
            "Inflation expectations are in danger of becoming unanchored and that "
            "would be catastrophic. We will not let that happen. "
            "Policy must be and will remain sufficiently restrictive for as long "
            "as it takes to bring inflation back to our 2 percent target. "
            "The labor market, though showing some signs of cooling, remains "
            "tight enough that the demand side of the inflation problem has not "
            "been resolved. We are not done. Additional increases remain on the table. "
            "Higher for longer is not a slogan — it is our commitment. "
            "Rate cuts are not in our baseline forecast. Do not expect them."
        ),
        "qa_section": (
            "Q: Are you trying to cause a recession? "
            "A: We are trying to restore price stability. That is our mandate. "
            "The costs of high inflation exceed the costs of the measures needed "
            "to control it. Q: When will you cut? "
            "A: That question is premature. We have more work to do. "
            "Sufficiently restrictive policy must be maintained. We will not flinch."
        ),
    },
)

# ── 3. Bank Failure / Sudden Liquidity Crisis ─────────────────────────────────
SCENARIO_03 = Scenario(
    number=3,
    name="Sudden Bank Failure — Systemic Liquidity Crisis",
    category="Financial Stability / Systemic Risk",
    event_time="2025-03-08T20:00:00+00:00",   # Saturday evening
    stress_level=0.70,
    historical_analog="SVB collapse weekend, March 10-12 2023",
    expected_severity="CRITICAL",
    raw_event={
        "title": "Federal Reserve Emergency Weekend Statement — Bank Failure and Systemic Risk",
        "institution": "Federal Reserve",
        "speaker": "Jerome Powell",
        "speaker_role": "Chair",
        "event_time": "2025-03-08T20:00:00+00:00",
        "description": "Emergency weekend statement following sudden failure of major regional bank.",
        "headline_summary": (
            "BREAKING: Fed, Treasury, FDIC announce emergency backstop following "
            "collapse of major regional bank. All deposits guaranteed. Emergency "
            "Bank Term Funding Program activated. Systemic contagion risk flagged."
        ),
        "prepared_remarks": (
            "Today the Federal Reserve Board, the Treasury Department, and the FDIC "
            "are taking decisive emergency action to protect the U.S. banking system "
            "and prevent systemic contagion. A major financial institution has been "
            "placed into receivership. All depositors will be made whole. "
            "This is a financial stability emergency. Systemic risk is real and present. "
            "We have activated emergency lending facilities under Section 13(3) of "
            "the Federal Reserve Act. The Bank Term Funding Program will provide "
            "emergency liquidity to any eligible depository institution that requires it. "
            "We are prepared to use every tool available to prevent contagion from "
            "spreading to other institutions. The banking system is fundamentally "
            "sound but we are not complacent. We are monitoring counterparty risk "
            "and funding markets extremely closely. This is an evolving situation. "
            "Additional emergency measures are available and will be used if necessary. "
            "Markets will open Monday and we are prepared for volatility. "
            "Whatever it takes to preserve financial stability, we will do."
        ),
        "qa_section": (
            "Q: Are other banks at risk? "
            "A: We are monitoring the situation intensively. We do not comment on "
            "specific institutions. Our emergency facilities are available to all. "
            "Q: Is this 2008? "
            "A: The situation is serious but the banking system has significantly "
            "more capital than in 2008. However we are not underestimating the risk. "
            "Q: Will you cut rates? "
            "A: We will use every tool available. We have not ruled anything out."
        ),
    },
)

# ── 4. Weekend Emergency Fed Rate Cut ────────────────────────────────────────
SCENARIO_04 = Scenario(
    number=4,
    name="Weekend Emergency Fed Rate Cut to Zero — COVID-Style Shock",
    category="Emergency Monetary Easing / Crisis",
    event_time="2025-11-16T17:00:00+00:00",   # Sunday afternoon
    stress_level=0.85,
    historical_analog="March 15 2020 — emergency Sunday rate cut to zero + QE infinity",
    expected_severity="CRITICAL",
    raw_event={
        "title": "Emergency Federal Reserve Action — Sunday Rate Cut to Zero, QE Activated",
        "institution": "Federal Reserve",
        "speaker": "Jerome Powell",
        "speaker_role": "Chair",
        "event_time": "2025-11-16T17:00:00+00:00",
        "description": "Emergency Sunday action: rates cut to zero, unlimited QE announced.",
        "headline_summary": (
            "EMERGENCY: Fed cuts rates to zero in unscheduled Sunday action. "
            "Unlimited asset purchases announced. Powell: 'We will not run out of "
            "ammunition.' Financial markets in freefall. Trading halts expected Monday."
        ),
        "prepared_remarks": (
            "The Federal Open Market Committee has voted unanimously at an emergency "
            "intermeeting session to reduce the federal funds rate to a target range "
            "of 0 to 25 basis points, effective immediately. "
            "We are also announcing an open-ended asset purchase program. "
            "The Federal Reserve will purchase Treasury securities and agency "
            "mortgage-backed securities in whatever amounts are needed to support "
            "smooth market functioning and effective transmission of monetary policy. "
            "There is no upper limit. We will not run out of ammunition. "
            "The crisis we face is severe. Financial conditions have tightened "
            "dramatically. Liquidity has evaporated in critical markets. "
            "Systemic risk is elevated to the highest level since 2008. "
            "We are coordinating with central banks globally. Emergency swap lines "
            "have been activated with the ECB, BOJ, BOE, Bank of Canada, and SNB. "
            "This is a financial stability emergency and we are responding accordingly. "
            "Additional emergency facilities will be announced in coming days."
        ),
        "qa_section": (
            "Q: Is the financial system at risk of collapse? "
            "A: We are acting with the full force of our emergency authority to "
            "prevent that outcome. Q: How long will zero rates last? "
            "A: As long as necessary. This is not a time for forward guidance. "
            "Q: Are circuit breakers likely Monday? "
            "A: We cannot predict market conditions. We are prepared for any scenario."
        ),
    },
)

# ── 5. Presidential Election Surprise — Market Shock ─────────────────────────
SCENARIO_05 = Scenario(
    number=5,
    name="Presidential Election Surprise Outcome — Policy Uncertainty Shock",
    category="Political / Policy Uncertainty",
    event_time="2028-11-06T06:00:00+00:00",   # Wednesday early morning, results coming in
    stress_level=0.50,
    historical_analog="Brexit shock June 24 2016 / Trump election Nov 9 2016",
    expected_severity="HIGH",
    raw_event={
        "title": "White House — Presidential Election Results: Unexpected Outcome",
        "institution": "White House",
        "speaker": "White House Press Secretary",
        "speaker_role": "Press Secretary",
        "event_time": "2028-11-06T06:00:00+00:00",
        "description": "Surprise presidential election outcome creates major policy uncertainty.",
        "headline_summary": (
            "Election results defy all polls. Unexpected winner projected. "
            "Markets pricing in massive policy reversal: tariffs, tax policy, "
            "Fed independence concerns. Dollar crashing. Safe havens surging. "
            "Extreme uncertainty over trade, fiscal, and regulatory direction."
        ),
        "prepared_remarks": (
            "The American people have spoken and we respect the democratic process. "
            "The incoming administration has signaled a fundamental reversal of "
            "current trade, fiscal, and regulatory policy. "
            "Proposed across-the-board tariffs of 25 percent represent an "
            "extraordinary shift in trade policy with significant inflationary "
            "implications. The proposed elimination of Federal Reserve independence "
            "is deeply concerning to financial markets globally. "
            "The fiscal outlook is highly uncertain. Proposed tax cuts combined "
            "with increased spending suggest significant deficit expansion. "
            "We are monitoring financial markets closely. The dollar is experiencing "
            "significant selling pressure. Treasury yields are volatile. "
            "This is a period of extreme policy uncertainty and markets are repricing "
            "the full spectrum of economic outcomes. Recession risk is elevated. "
            "Trade war escalation risk is elevated. Inflation risk is elevated. "
            "We urge calm and orderly markets."
        ),
        "qa_section": (
            "Q: Is the Fed's independence at risk? "
            "A: The independence of the Federal Reserve is a cornerstone of "
            "U.S. financial stability. Any threat to that independence would be "
            "deeply destabilizing. Q: How bad could the market reaction be? "
            "A: We are in a period of significant uncertainty. The range of outcomes "
            "is unusually wide. Circuit breakers are a possibility."
        ),
    },
)

# ── 6. Military Conflict Escalation — Geopolitical Shock ─────────────────────
SCENARIO_06 = Scenario(
    number=6,
    name="Major Power Military Escalation — Geopolitical Black Swan",
    category="Geopolitical / War Risk",
    event_time="2026-04-19T03:00:00+00:00",   # Middle of night Saturday
    stress_level=0.60,
    historical_analog="Russia invasion of Ukraine Feb 24 2022 market open",
    expected_severity="CRITICAL",
    raw_event={
        "title": "White House Emergency National Security Statement — Military Escalation",
        "institution": "White House",
        "speaker": "White House Press Secretary",
        "speaker_role": "Press Secretary",
        "event_time": "2026-04-19T03:00:00+00:00",
        "description": "Emergency overnight statement on major military escalation in strategic region.",
        "headline_summary": (
            "BREAKING: Major military escalation overnight. President activating "
            "emergency economic powers. Sweeping sanctions announced. "
            "Oil surges 15%. Gold at record. Global equities in freefall. "
            "NATO Article 5 consultations underway. Safe haven bid extreme."
        ),
        "prepared_remarks": (
            "The President of the United States has been briefed and is monitoring "
            "the situation in real time. This represents a severe escalation of "
            "geopolitical tensions that poses significant risk to global financial "
            "stability and economic growth. "
            "The President is invoking emergency economic powers under IEEPA. "
            "Comprehensive sanctions are being imposed immediately. "
            "Energy markets are experiencing extreme volatility. Oil prices are "
            "surging and energy supply disruption risk is acute. "
            "We are coordinating with G7 allies. Emergency consultations are "
            "underway with NATO partners. "
            "Financial markets face extraordinary uncertainty. The risk to global "
            "growth is severe. Supply chain disruptions are expected. "
            "Commodity markets — oil, natural gas, wheat, metals — are all "
            "at risk of severe dislocation. "
            "This is a national security emergency with profound financial implications. "
            "We are prepared for a range of scenarios including the worst case. "
            "The Federal Reserve and Treasury are monitoring markets closely and "
            "are in contact with global central bank counterparts."
        ),
        "qa_section": (
            "Q: Could this trigger a global recession? "
            "A: The risk to global growth is severe and real. We are not minimizing it. "
            "Q: Will the Fed cut rates to cushion the shock? "
            "A: The Federal Reserve will take whatever action is appropriate. "
            "Q: Are we prepared for oil at $150? "
            "A: We are prepared for a range of scenarios."
        ),
    },
)

# ── 7. Surprise CPI Print — Inflation Data Shock ─────────────────────────────
SCENARIO_07 = Scenario(
    number=7,
    name="Shock CPI Print — Inflation Acceleration Surprise",
    category="Economic Data / Inflation Shock",
    event_time="2025-10-14T12:30:00+00:00",   # Tuesday 8:30am ET
    stress_level=0.45,
    historical_analog="CPI print Aug 2022 showing 8.3% vs 8.1% expected; market -4%",
    expected_severity="HIGH",
    raw_event={
        "title": "U.S. CPI Data Release — Massive Upside Inflation Surprise",
        "institution": "U.S. Treasury",
        "speaker": "Janet Yellen",
        "speaker_role": "Secretary",
        "event_time": "2025-10-14T12:30:00+00:00",
        "description": "CPI comes in dramatically above expectations. Treasury Secretary reacts.",
        "headline_summary": (
            "SHOCK CPI: Headline +1.2% MoM vs +0.3% expected. Core CPI reaccelerates. "
            "Inflation expectations becoming unanchored. Rate cut expectations "
            "completely repriced. Treasury yields spike 30bps. Equities -3.5%."
        ),
        "prepared_remarks": (
            "Today's Consumer Price Index data is deeply concerning and significantly "
            "above all expectations. Headline inflation re-accelerated sharply. "
            "Core inflation, which excludes food and energy, also re-accelerated — "
            "this is the number the Federal Reserve watches most closely and it is "
            "moving in the wrong direction. Services inflation remains persistently "
            "elevated. Shelter costs continue to rise. This data fundamentally "
            "changes the calculus for monetary policy. "
            "Rate cuts are off the table. The Federal Reserve's work is not done. "
            "Inflation expectations risk becoming unanchored — that would be "
            "catastrophic and must be prevented at all costs. "
            "The Treasury is monitoring financial market conditions. "
            "The repricing of rate expectations is orderly but significant. "
            "Treasury yields are moving higher in an orderly fashion. "
            "However the magnitude of this surprise creates tail risk for leveraged "
            "positions and could trigger forced deleveraging across asset classes."
        ),
        "qa_section": (
            "Q: Will the Fed hike again? "
            "A: The Federal Reserve operates independently. But this data clearly "
            "removes any near-term option to reduce rates. Additional firming "
            "cannot be ruled out. Q: Is a recession now more likely? "
            "A: The path to a soft landing has narrowed considerably."
        ),
    },
)

# ── 8. Sovereign Debt / Credit Contagion ──────────────────────────────────────
SCENARIO_08 = Scenario(
    number=8,
    name="Sovereign Debt Crisis — Credit Contagion Event",
    category="Credit / Sovereign Risk",
    event_time="2026-07-11T21:00:00+00:00",   # Saturday evening
    stress_level=0.65,
    historical_analog="European sovereign debt crisis 2011-12; Liz Truss UK gilt crisis Sep 2022",
    expected_severity="CRITICAL",
    raw_event={
        "title": "IMF Emergency Statement — Sovereign Debt Crisis and Contagion Risk",
        "institution": "International Monetary Fund",
        "speaker": "Kristalina Georgieva",
        "speaker_role": "Managing Director",
        "event_time": "2026-07-11T21:00:00+00:00",
        "description": "IMF emergency weekend statement on sovereign debt crisis spreading.",
        "headline_summary": (
            "IMF declares emergency. Major economy sovereign spreads at crisis levels. "
            "Contagion spreading to IG credit. Global banks with sovereign exposure flagged. "
            "Emergency IMF/ESM facility being constructed over weekend. "
            "Monday open expected to be disorderly."
        ),
        "prepared_remarks": (
            "The International Monetary Fund is issuing an emergency statement "
            "regarding the sovereign debt situation, which has deteriorated to "
            "a level requiring immediate international action. "
            "Sovereign spreads have reached levels that are inconsistent with "
            "debt sustainability. Contagion risk to the broader financial system "
            "is severe and real. Global banks with significant sovereign bond "
            "exposure face material losses. Credit default swap markets are "
            "indicating elevated probability of restructuring. "
            "We are working urgently with member nations and partner institutions "
            "to construct an emergency financing facility over this weekend. "
            "Time is of the essence. A disorderly sovereign default would trigger "
            "financial contagion of systemic proportions. "
            "Liquidity in sovereign bond markets has deteriorated sharply. "
            "Forced selling by leveraged investors is amplifying the stress. "
            "Central banks must be prepared to act as buyers of last resort. "
            "We cannot allow this to become a repeat of 2012. "
            "Whatever it takes to prevent systemic collapse, the international "
            "community must and will do."
        ),
        "qa_section": (
            "Q: Is a default imminent? "
            "A: We are working to prevent it. The next 48 hours are critical. "
            "Q: Will the ECB activate emergency bond purchases? "
            "A: All options are on the table. Q: How bad is contagion risk? "
            "A: Severe. We are in crisis management mode."
        ),
    },
)

# ── 9. Flash Crash / Market Microstructure Breakdown ─────────────────────────
SCENARIO_09 = Scenario(
    number=9,
    name="Flash Crash — Market Microstructure and Liquidity Breakdown",
    category="Market Microstructure / Liquidity Shock",
    event_time="2025-05-06T14:47:00+00:00",   # Intraday Tuesday — like May 6 2010
    stress_level=0.55,
    historical_analog="Flash crash May 6 2010; August 24 2015 ETF breakdown",
    expected_severity="CRITICAL",
    raw_event={
        "title": "SEC/CFTC Joint Emergency Statement — Market Microstructure Breakdown",
        "institution": "U.S. Treasury",
        "speaker": "Treasury Secretary",
        "speaker_role": "Secretary",
        "event_time": "2025-05-06T14:47:00+00:00",
        "description": "Emergency joint statement following sudden market liquidity breakdown.",
        "headline_summary": (
            "MARKET EMERGENCY: SPX drops 7% in 4 minutes. Circuit breakers activated. "
            "Trading halted across major exchanges. ETF pricing breakdown. "
            "SEC/CFTC joint emergency statement. Market makers withdrawing. "
            "Liquidity evaporated. Extraordinary market dysfunction."
        ),
        "prepared_remarks": (
            "The Securities and Exchange Commission and the Commodity Futures Trading "
            "Commission are issuing a joint emergency statement regarding extraordinary "
            "market dysfunction occurring in equity markets right now. "
            "Market-wide circuit breakers have been activated. Trading is halted. "
            "We are experiencing a severe and sudden deterioration in market liquidity "
            "and market microstructure integrity. Market makers have withdrawn from "
            "providing liquidity in a self-reinforcing cascade. "
            "ETF pricing has broken down with premiums and discounts of unprecedented "
            "magnitude. Algorithmic trading systems appear to have amplified the move. "
            "This is an extraordinary market event. "
            "We are in contact with exchange operators and are evaluating all options "
            "including extended trading halts and potential cancellation of clearly "
            "erroneous trades. "
            "Financial stability is at risk if confidence in market functioning is "
            "not restored quickly. "
            "The Federal Reserve is monitoring liquidity conditions and is prepared "
            "to act. Systemic risk is elevated to crisis levels."
        ),
        "qa_section": (
            "Q: Will trades be cancelled? "
            "A: We are evaluating clearly erroneous transactions. "
            "Q: Is the financial system stable? "
            "A: We are in active crisis management. Q: How long will halt last? "
            "A: As long as needed to restore orderly conditions."
        ),
    },
)

# ── 10. Massive Fiscal Stimulus Announcement ──────────────────────────────────
SCENARIO_10 = Scenario(
    number=10,
    name="Massive Fiscal Stimulus Announcement — Reflationary Shock",
    category="Fiscal Policy / Stimulus",
    event_time="2026-01-15T15:00:00+00:00",   # Thursday afternoon
    stress_level=0.35,
    historical_analog="CARES Act March 2020 ($2.2T); Biden ARP March 2021 ($1.9T)",
    expected_severity="MEDIUM",
    raw_event={
        "title": "White House — $3 Trillion Emergency Fiscal Stimulus Package Announced",
        "institution": "White House",
        "speaker": "President of the United States",
        "speaker_role": "President of the United States",
        "event_time": "2026-01-15T15:00:00+00:00",
        "description": "White House announces unprecedented $3T fiscal stimulus package.",
        "headline_summary": (
            "White House announces $3 trillion emergency fiscal package. "
            "Direct payments, infrastructure, defense spending. "
            "Deficit to GDP surges. Bond vigilantes emerge. "
            "Yields spike. Equities rally on growth bet then sell on inflation fear."
        ),
        "prepared_remarks": (
            "Today I am announcing the American Economic Resilience Act — "
            "a three trillion dollar package of direct support to American families, "
            "investment in critical infrastructure, and strengthening of our "
            "national defense and energy independence. "
            "This is the most ambitious fiscal investment in American history. "
            "Direct payments will go to every American household. "
            "Infrastructure spending will create millions of jobs. "
            "This will drive robust economic growth for years to come. "
            "We are not concerned about the deficit. Growth pays for itself. "
            "We are prepared for the bond market reaction. "
            "Inflation is a risk we take seriously but growth and jobs come first. "
            "The Federal Reserve has the tools to manage inflation if necessary. "
            "This package will be funded through a combination of new issuance "
            "and tax reform on corporations and high earners. "
            "We expect GDP growth to accelerate significantly."
        ),
        "qa_section": (
            "Q: How do you fund this without triggering a bond crisis? "
            "A: Growth creates tax revenue. This is an investment not a giveaway. "
            "Q: Will the Fed have to raise rates faster? "
            "A: The Federal Reserve is independent and will do what it must. "
            "Q: Are you worried about inflation? "
            "A: We are watching it carefully. The growth benefits outweigh the risks."
        ),
    },
)

# ── 11. Currency Crisis — Emerging Market Contagion ──────────────────────────
SCENARIO_11 = Scenario(
    number=11,
    name="Emerging Market Currency Crisis — Contagion to Developed Markets",
    category="FX / EM Contagion",
    event_time="2026-08-22T18:00:00+00:00",   # Friday after close
    stress_level=0.60,
    historical_analog="1997 Asian currency crisis; 1998 Russian default/LTCM; 2018 EM rout",
    expected_severity="HIGH",
    raw_event={
        "title": "IMF / Federal Reserve Joint Statement — EM Currency Crisis and Contagion",
        "institution": "International Monetary Fund",
        "speaker": "Kristalina Georgieva",
        "speaker_role": "Managing Director",
        "event_time": "2026-08-22T18:00:00+00:00",
        "description": "Joint IMF/Fed statement on EM currency crisis spreading to DM credit.",
        "headline_summary": (
            "EM currency crisis escalating. Multiple currencies in free fall. "
            "Carry trade unwind accelerating. Dollar surging. EM sovereign spreads "
            "at crisis levels. Contagion to DM credit spreading. "
            "Fed activates EM swap lines. IMF emergency facilities mobilized."
        ),
        "prepared_remarks": (
            "The International Monetary Fund and the Federal Reserve are issuing "
            "a coordinated statement regarding the deteriorating situation in "
            "emerging market currency and credit markets. "
            "Multiple emerging market currencies have experienced disorderly "
            "declines of 15 to 30 percent against the dollar in recent weeks. "
            "This is triggering a violent unwind of the global carry trade. "
            "Capital flows are reversing at a pace not seen since 1998. "
            "EM sovereign spreads have blown out to levels indicating significant "
            "default risk across multiple nations. "
            "More concerning is the transmission to developed market credit. "
            "High yield spreads in the U.S. and Europe are widening rapidly. "
            "Banks with significant EM exposure are under severe pressure. "
            "Dollar funding stress is emerging as evidenced by FX swap basis "
            "moving sharply negative. "
            "The Federal Reserve has activated emergency dollar swap lines with "
            "multiple central bank counterparts to ensure dollar liquidity. "
            "The IMF has activated emergency funding facilities. "
            "Contagion risk is severe. Forced deleveraging by global macro funds "
            "is amplifying the stress. Liquidity in EM markets is near zero. "
            "We are in active coordination with G20 counterparts."
        ),
        "qa_section": (
            "Q: Is this 1998 again? "
            "A: The parallels are concerning. We are acting more forcefully. "
            "Q: Is LTCM-style blowup risk present? "
            "A: We are monitoring hedge fund positioning very carefully. "
            "Q: Will the Fed cut rates to ease dollar strength? "
            "A: All options are being considered."
        ),
    },
)

# ── 12. Coordinated Multi-Central-Bank Emergency Action ──────────────────────
SCENARIO_12 = Scenario(
    number=12,
    name="Coordinated G7 Central Bank Emergency Action — Global Crisis Response",
    category="Coordinated Policy / Global Crisis",
    event_time="2026-10-18T14:00:00+00:00",   # Sunday afternoon
    stress_level=0.90,
    historical_analog="Coordinated CB action Oct 8 2008; COVID-19 March 2020 CB coordination",
    expected_severity="CRITICAL",
    raw_event={
        "title": "Joint G7 Central Bank Emergency Statement — Coordinated Global Action",
        "institution": "Federal Reserve",
        "speaker": "Jerome Powell",
        "speaker_role": "Chair",
        "event_time": "2026-10-18T14:00:00+00:00",
        "description": "Unprecedented G7 coordinated emergency action: simultaneous rate cuts + QE.",
        "headline_summary": (
            "HISTORIC: Fed, ECB, BOJ, BOE, BOC, SNB, RBA announce simultaneous "
            "emergency rate cuts and unlimited QE. 'Whatever it takes — globally.' "
            "Circuit breakers certain at Monday open. Financial system stability "
            "in question. Most significant coordinated CB action since 2008."
        ),
        "prepared_remarks": (
            "The central banks of the G7 nations are today taking an unprecedented "
            "coordinated emergency action. This is a joint statement on behalf of "
            "the Federal Reserve, the European Central Bank, the Bank of Japan, "
            "the Bank of England, the Bank of Canada, the Swiss National Bank, "
            "and the Reserve Bank of Australia. "
            "We are each announcing simultaneous and substantial reductions in "
            "our respective policy rates. Additionally, each institution is "
            "announcing open-ended asset purchase programs. "
            "We are also announcing the activation and significant expansion of "
            "bilateral dollar swap lines to ensure dollar liquidity globally. "
            "The global financial system is under severe stress. "
            "Systemic risk has reached crisis levels not seen since 2008. "
            "Contagion is spreading across all asset classes simultaneously. "
            "Correlation across risk assets has moved to one — everything is "
            "selling simultaneously and liquidity has evaporated. "
            "We are acting together because this threat is global and requires "
            "a global response. "
            "We will do whatever it takes. There are no limits on our commitment "
            "to financial stability. No limits whatsoever. "
            "Emergency market closure is under consideration. "
            "Circuit breakers will activate at Monday's open. We are prepared."
        ),
        "qa_section": (
            "Q: Is the global financial system in danger of collapse? "
            "A: We are acting to prevent that. Our commitment is unlimited. "
            "Q: Will markets be closed Monday? "
            "A: That option is being evaluated by exchange operators. "
            "Q: Is this worse than 2008? "
            "A: This is a global systemic crisis requiring a global response. "
            "We are acting with appropriate urgency and force."
        ),
    },
)

ALL_SCENARIOS = [
    SCENARIO_01, SCENARIO_02, SCENARIO_03, SCENARIO_04,
    SCENARIO_05, SCENARIO_06, SCENARIO_07, SCENARIO_08,
    SCENARIO_09, SCENARIO_10, SCENARIO_11, SCENARIO_12,
]


# ═══════════════════════════════════════════════════════════════════════════
#  Result Container
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class ScenarioResult:
    number: int
    name: str
    category: str
    historical_analog: str
    expected_severity: str

    composite_score: float = 0.0
    actual_severity: str = "N/A"
    action_level: str = "N/A"
    regime: str = "N/A"

    stance: str = "N/A"
    surprise_magnitude: float = 0.0
    net_direction: float = 0.0
    crisis_language: bool = False
    urgency: float = 0.0

    expected_equity_pct: float = 0.0
    tail_loss_5pct: float = 0.0
    monday_gap_pct: Optional[float] = None
    expected_vix_change: float = 0.0
    expected_yield_bps: float = 0.0

    weekend_gap_active: bool = False
    hours_to_open: Optional[float] = None
    kill_switch: bool = False
    n_hedges: int = 0
    n_alerts: int = 0

    sub_scores: Dict[str, float] = field(default_factory=dict)
    top_hedge: str = "None"
    elapsed_ms: float = 0.0
    errors: List[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════
#  Runner
# ═══════════════════════════════════════════════════════════════════════════

def run_scenario(
    scenario: Scenario,
    pipeline: MacroShockPipeline,
    stress_override: Optional[float] = None,
) -> ScenarioResult:
    """Run a single scenario through the full MSRE pipeline."""
    result = ScenarioResult(
        number=scenario.number,
        name=scenario.name,
        category=scenario.category,
        historical_analog=scenario.historical_analog,
        expected_severity=scenario.expected_severity,
    )

    try:
        stress = stress_override if stress_override is not None else scenario.stress_level
        event_time = datetime.fromisoformat(
            scenario.event_time.replace("Z", "+00:00")
        ).astimezone(timezone.utc)

        market_state = MarketStateBuilder.build_synthetic(
            as_of=event_time,
            calendar=pipeline.calendar,
            stress_level=stress,
            seed=scenario.number * 7,   # Deterministic per scenario
        )

        t0 = time.monotonic()
        ctx = pipeline.process_raw_event(scenario.raw_event, market_state=market_state)
        result.elapsed_ms = (time.monotonic() - t0) * 1000

        # Event
        if ctx.event:
            result.weekend_gap_active = ctx.event.full_weekend_gap
            result.hours_to_open = ctx.event.hours_until_next_open

        # NLP
        if ctx.policy_surprise:
            ps = ctx.policy_surprise
            result.surprise_magnitude = ps.composite_surprise_magnitude
            result.net_direction = ps.net_direction
            result.urgency = ps.urgency_surprise
            if ps.hawkish_dovish:
                result.stance = ps.hawkish_dovish.stance.value
                result.crisis_language = ps.hawkish_dovish.crisis_language_detected

        # Scenario tree
        if ctx.scenario_tree:
            tree = ctx.scenario_tree
            result.expected_equity_pct = tree.expected_equity_impact_pct
            result.tail_loss_5pct = tree.tail_loss_5pct
            result.expected_vix_change = tree.expected_vix_change
            result.expected_yield_bps = tree.expected_yield_change_bps
            result.monday_gap_pct = tree.monday_gap_estimate_pct

        # Risk score
        if ctx.risk_score:
            rs = ctx.risk_score
            result.composite_score = rs.composite_score
            result.actual_severity = rs.severity.value
            result.action_level = rs.recommended_action_level
            result.regime = rs.regime.value
            result.sub_scores = {
                "Liquidity":       rs.liquidity_risk.score,
                "Volatility":      rs.volatility_risk.score,
                "Rate Shock":      rs.rate_shock_risk.score,
                "Equity Downside": rs.equity_downside_risk.score,
                "Credit Spread":   rs.credit_spread_risk.score,
                "FX Risk":         rs.fx_risk.score,
                "Commodity":       rs.commodity_shock_risk.score,
                "Weekend Gap":     rs.weekend_gap_risk.score,
                "Policy Ambiguity":rs.policy_ambiguity_risk.score,
            }

        # Portfolio
        if ctx.portfolio_impact:
            pi = ctx.portfolio_impact
            result.kill_switch = pi.trigger_kill_switch
            result.n_hedges = len(pi.hedge_recommendations)
            if pi.hedge_recommendations:
                h = pi.hedge_recommendations[0]
                result.top_hedge = f"[{h.urgency}] {h.action} {h.asset_class.value.upper()}: {h.instrument_description[:50]}"

        result.n_alerts = len(ctx.alerts)
        result.errors = ctx.errors

    except Exception as e:
        result.errors.append(str(e))

    return result


# ═══════════════════════════════════════════════════════════════════════════
#  Printing
# ═══════════════════════════════════════════════════════════════════════════

def sev_c(s: str) -> str:
    return SEV_COLOUR.get(s, "") + s + RESET

def act_c(s: str) -> str:
    return ACTION_COLOUR.get(s, "") + s + RESET

def score_bar(score: float, width: int = 30) -> str:
    filled = int(score / 100 * width)
    colour = R if score >= 75 else Y if score >= 55 else C if score >= 35 else G
    return colour + "█" * filled + DIM + "░" * (width - filled) + RESET

def print_scenario_result(r: ScenarioResult) -> None:
    print()
    print(f"{BOLD}{'═' * 70}{RESET}")
    print(f"{BOLD}  SCENARIO {r.number:02d}  ·  {r.name}{RESET}")
    print(f"  {DIM}Category: {r.category}  ·  Analog: {r.historical_analog}{RESET}")
    print(f"{'═' * 70}")

    # Main score line
    sev_col = SEV_COLOUR.get(r.actual_severity, "")
    print(f"\n  {score_bar(r.composite_score)}  "
          f"{BOLD}{sev_col}{r.composite_score:5.1f}/100{RESET}  "
          f"[{sev_c(r.actual_severity)}]  →  {act_c(r.action_level)}")
    print(f"  Regime: {B}{r.regime}{RESET}  "
          f"{'  ' + R + '⚠ KILL SWITCH' + RESET if r.kill_switch else ''}")

    # NLP line
    direction_arrow = "▲ hawkish" if r.net_direction > 0.1 else "▼ dovish" if r.net_direction < -0.1 else "● neutral"
    crisis_flag = f"  {R}[CRISIS LANGUAGE]{RESET}" if r.crisis_language else ""
    print(f"\n  Language:  Stance={M}{r.stance}{RESET}  |  "
          f"Surprise={r.surprise_magnitude:.2f}  |  "
          f"Direction={direction_arrow}{crisis_flag}")

    # Market impact
    gap_note = ""
    if r.weekend_gap_active:
        gap_note = f"  {Y}[WEEKEND GAP: {r.hours_to_open:.0f}h]{RESET}"
        if r.monday_gap_pct:
            gap_note += f"  Monday est: {R}{r.monday_gap_pct:+.1f}%{RESET}"

    eq_col = R if r.expected_equity_pct < -2 else Y if r.expected_equity_pct < 0 else G
    print(f"  Impact:    E[Equity]={eq_col}{r.expected_equity_pct:+.1f}%{RESET}  "
          f"Tail(5%)={R}{r.tail_loss_5pct:.1f}%{RESET}  "
          f"E[ΔVix]={r.expected_vix_change:+.1f}  "
          f"E[Δ10Y]={r.expected_yield_bps:+.0f}bps"
          f"{gap_note}")

    # Sub-scores bar chart
    print(f"\n  {DIM}Sub-Score Breakdown:{RESET}")
    sorted_subs = sorted(r.sub_scores.items(), key=lambda x: x[1], reverse=True)
    for name, score in sorted_subs:
        col = R if score >= 70 else Y if score >= 50 else C if score >= 30 else DIM
        bar = col + "█" * int(score / 10) + RESET + DIM + "░" * (10 - int(score / 10)) + RESET
        print(f"  {name:<20} {bar}  {col}{score:5.1f}{RESET}")

    # Hedges and alerts
    print(f"\n  Hedges: {r.n_hedges}  |  Alerts: {r.n_alerts}")
    if r.top_hedge != "None":
        print(f"  Top Hedge: {Y}{r.top_hedge}{RESET}")

    # Expected vs actual severity
    match = r.expected_severity == r.actual_severity
    match_str = f"{G}✓ matches expected{RESET}" if match else f"{Y}↕ expected {r.expected_severity}{RESET}"
    print(f"\n  Severity check: {match_str}  |  "
          f"Computed in {r.elapsed_ms:.0f}ms")

    if r.errors:
        print(f"  {R}Errors: {'; '.join(r.errors[:2])}{RESET}")


def print_comparison_table(results: List[ScenarioResult]) -> None:
    print()
    print(f"\n{BOLD}{'═' * 90}{RESET}")
    print(f"{BOLD}  SCENARIO COMPARISON SUMMARY — ALL {len(results)} SCENARIOS{RESET}")
    print(f"{'═' * 90}")
    print(f"\n  {'#':>2}  {'Scenario':<42} {'Score':>6}  {'Severity':<12} {'Action':<22} {'E[Eq]':>7}  {'Tail5%':>7}")
    print(f"  {'─' * 86}")
    for r in sorted(results, key=lambda x: x.composite_score, reverse=True):
        sev_col = SEV_COLOUR.get(r.actual_severity, "")
        act_col = ACTION_COLOUR.get(r.action_level, "")
        eq_col  = R if r.expected_equity_pct < -2 else Y if r.expected_equity_pct < 0 else G
        gap_marker = f"{Y}[GAP]{RESET}" if r.weekend_gap_active else "     "
        print(
            f"  {r.number:>2}  {r.name[:42]:<42} "
            f"{sev_col}{r.composite_score:>5.1f}{RESET}  "
            f"{sev_col}{r.actual_severity:<12}{RESET} "
            f"{act_col}{r.action_level:<22}{RESET} "
            f"{eq_col}{r.expected_equity_pct:>+6.1f}%{RESET}  "
            f"{R}{r.tail_loss_5pct:>6.1f}%{RESET}  {gap_marker}"
        )

    # Aggregate stats
    scores = [r.composite_score for r in results]
    critical_count = sum(1 for r in results if r.actual_severity == "CRITICAL")
    gap_count = sum(1 for r in results if r.weekend_gap_active)
    kill_count = sum(1 for r in results if r.kill_switch)
    crisis_count = sum(1 for r in results if r.crisis_language)

    print(f"\n  {'─' * 86}")
    print(f"  Mean score: {sum(scores)/len(scores):.1f}  |  "
          f"Max: {max(scores):.1f}  |  "
          f"CRITICAL: {critical_count}/{len(results)}  |  "
          f"Weekend gap: {gap_count}  |  "
          f"Kill switch: {kill_count}  |  "
          f"Crisis language: {crisis_count}")
    print(f"{'═' * 90}\n")


# ═══════════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Macro Shock Risk Engine — Real-World Scenario Tests",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--scenario", type=int, default=None,
                        help="Run a single scenario by number (1-12). Default: all.")
    parser.add_argument("--stress", type=float, default=None,
                        help="Override market stress level for all scenarios (0.0–1.0).")
    parser.add_argument("--export", default=None,
                        help="Export results to JSON file (e.g. results.json).")
    parser.add_argument("--quiet", action="store_true",
                        help="Print only the comparison table, not individual results.")
    args = parser.parse_args()

    # ── Header ──────────────────────────────────────────────────────────────
    print(f"\n{BOLD}{W}{'=' * 70}{RESET}")
    print(f"{BOLD}{W}  MACRO SHOCK RISK ENGINE{RESET}")
    print(f"{BOLD}{W}  Real-World Scenario Testing Suite{RESET}")
    print(f"{BOLD}{W}  12 Historical Macro Shock Archetypes — Full Pipeline{RESET}")
    print(f"{BOLD}{W}{'=' * 70}{RESET}\n")

    # ── Pipeline init ────────────────────────────────────────────────────────
    config = {
        "use_transformer": False,
        "fail_fast": False,
        "audit_log_dir": "/tmp/msre_scenarios",
    }
    print(f"  Initialising pipeline... ", end="", flush=True)
    pipeline = MacroShockPipeline(config=config, environment="research")
    print(f"{G}ready{RESET}")

    # ── Select scenarios ─────────────────────────────────────────────────────
    scenarios = ALL_SCENARIOS
    if args.scenario is not None:
        scenarios = [s for s in ALL_SCENARIOS if s.number == args.scenario]
        if not scenarios:
            print(f"{R}Scenario {args.scenario} not found. Valid: 1-12.{RESET}")
            sys.exit(1)

    print(f"  Running {len(scenarios)} scenario(s)...\n")

    # ── Run ──────────────────────────────────────────────────────────────────
    results: List[ScenarioResult] = []
    for scenario in scenarios:
        if not args.quiet:
            pass  # print happens inside run+print
        result = run_scenario(scenario, pipeline, stress_override=args.stress)
        results.append(result)
        if not args.quiet:
            print_scenario_result(result)

    # ── Comparison table ─────────────────────────────────────────────────────
    if len(results) > 1 or args.quiet:
        print_comparison_table(results)

    # ── Export ───────────────────────────────────────────────────────────────
    if args.export:
        export_data = []
        for r in results:
            d = asdict(r)
            export_data.append(d)
        with open(args.export, "w") as f:
            json.dump(export_data, f, indent=2, default=str)
        print(f"  Results exported to: {G}{args.export}{RESET}\n")

    print(f"  {DIM}All scenarios complete.{RESET}\n")


if __name__ == "__main__":
    main()
