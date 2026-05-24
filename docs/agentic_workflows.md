# Agentic Workflows

This guide shows how AI agents can use Smaug to answer complex research administration questions that require multi-step reasoning. Each example demonstrates an **observe → reason → decide → act** loop where the agent queries data, interprets intermediate results, and adapts its plan based on what it finds.

Agents can interact with Smaug via the **CLI** (shell-based agents read [`AGENTS.md`](../AGENTS.md)), the **Python API** (`smaug.api.SmaugAPI`, returns plain dicts), or the **MCP server** (`smaug-mcp`). For detailed setup and agent-specific configurations, please refer to the [Agent Getting Started Guides](agents/overview.md).

---

## 1. "We have a $300k plus-up to spend by September. How much can we feasibly spend?"

A sponsor offers a $300,000 budget plus-up on QUASAR, but fiscal year constraints require all funds to be obligated by September 30, 2026. The PI asks: *what hires and purchases can we make?*

This is a constraint-satisfaction problem. A human administrator would spend hours with a spreadsheet. An agent can search the option space programmatically.

### Agent Trace

```
Agent: I need to figure out what $300k buys in 4 months under JHU rates.
       Let me establish the baseline so I know what's incremental.

> api.spend_plan(projects=["QUASAR"], months=6)

Agent: Baseline burn is ~$23,844/month. Now let me price out a postdoc.

> api.spend_plan(projects=["QUASAR"], months=6,
>     add_personnel=[{"type": "postdoc", "effort_pct": 100, "salary": 85000}])

Agent: Hypothetical total for June–Sept is $175k vs. baseline $100k.
       Delta is ~$75k for one postdoc over 4 months. That's fully loaded:
       $85k salary → $7,083/mo + 21.1% fringe + 55% F&A.
       Leaves $225k. Can I add PhD students too?

       Wait — I should check whether September creates a billing spike.
       JHU bills tuition and health insurance semi-annually in Jan and Sept.

> api.spend_plan(projects=["QUASAR"], months=6,
>     add_personnel=[
>         {"type": "postdoc", "effort_pct": 100, "salary": 85000},
>         {"type": "grad_student", "effort_pct": 100, "salary": 50000},
>         {"type": "grad_student", "effort_pct": 100, "salary": 50000}
>     ])

Agent: Confirmed — September projection jumps to $58k because of the tuition
       charge ($6,667/student) and insurance ($2,182/student). The 4-month
       delta for postdoc + 2 PhDs is ~$195k.

       That leaves ~$105k. Equipment over $5k is F&A-exempt at JHU, so a
       $100k GPU server costs exactly $100k, not $155k.

       Total: 1 postdoc + 2 PhDs + $100k equipment = ~$295k. Under ceiling.

       But I should check whether the PI can absorb 2 more students.

> smaug personnel --project QUASAR

Agent: PI Smith already supervises Chen (postdoc) and Martinez (PhD, 50%).
       Adding 2 more students plus a new postdoc brings the lab to 5 direct
       reports. That's a judgment call for the PI.

       Presenting 3 options with trade-offs:
       A) 1 postdoc + 2 PhDs + $100k equipment = $295k (max research capacity)
       B) 1 postdoc + 1 PhD + $150k equipment = $248k (fewer mentees)
       C) 2 postdocs + $100k equipment = $249k (no tuition overhead)
```

**What makes this agentic:** The agent doesn't call one function. It queries the baseline, tests a hypothesis, discovers a non-obvious billing spike (September tuition), reasons about F&A exemptions to stretch the budget, checks a constraint it wasn't asked about (mentoring load), and presents trade-offs rather than a single answer.

---

## 2. "Chen's salary looks low this month. What happened?"

The PI glances at the March spending report and notices postdoc Chen's charge looks wrong. Rather than manually cross-referencing spreadsheets, they ask the agent to investigate.

### Agent Trace

```
Agent: Let me run the audit and see if the numbers confirm the PI's hunch.

> smaug audit QUASAR --months 3 --threshold 10

Agent: Confirmed. Chen, Wei: expected $6,000/month (100% of $72k) but
       actual March charge was $3,000. That's a 50% under-billing.

       The money has to be going somewhere. Let me check if Chen shows
       up on any other accounts.

> smaug audit NEXUS --months 3 --threshold 10

Agent: No anomalies on NEXUS. What about the discretionary account?

> smaug report list STARTUP

Agent: Found it — STARTUP shows a $3,000 salary charge in March that
       wasn't there in February. Chen's effort is being split 50/50
       between QUASAR and STARTUP, but the config says 100% QUASAR.

       Is this a one-time error or ongoing?

> smaug audit QUASAR --months 6 --threshold 10

Agent: Only March is flagged. January and February billed correctly at
       $6,000. This looks like a payroll distribution form that took
       effect in March — probably filed by accident or applied to the
       wrong person.

       Recommendation: Submit a retroactive cost transfer of $3,000
       from STARTUP to QUASAR for March. The signed effort agreement
       has Chen at 100% QUASAR.
```

**What makes this agentic:** The agent doesn't just report the anomaly — it investigates where the missing money went by checking other accounts, finds it on STARTUP, then checks the temporal pattern to determine whether it's a one-time error or systemic. Each step depends on the result of the previous one.

---

## 3. "NEXUS is running out of money early. How do we fix it?"

The NEXUS stop-work forecast shows funds exhausted 3 months before the grant ends. The PI asks the agent to find a way to extend the runway without disrupting ongoing research.

### Agent Trace

```
Agent: Let me quantify the gap.

> smaug stopwork NEXUS --ceiling 750000

Agent: NEXUS burns ~$12,745/month. At this rate, funds run out around
       March 2027 — but the grant runs through June 2027. We need to
       cut ~$38k over the remaining period.

       Who's on NEXUS?

> smaug personnel --project NEXUS

Agent: NEXUS personnel:
       - Smith, Jane (PI) — 10% effort
       - Martinez, Sofia (PhD) — 50% effort
       - Patel, Raj (PhD) — 100% effort

       Can't touch the PI. Let me check if Martinez or Patel have room
       on other accounts.

> smaug personnel "Martinez"

Agent: Martinez is 50% QUASAR, 50% NEXUS — total 100%. She can't take on
       more work, but I could shift her NEXUS portion to QUASAR.

       What would removing Martinez do to NEXUS?

> smaug spend-plan NEXUS --if "Martinez=0%" --compare

Agent: Monthly burn drops from $12,745 to $9,105. That extends the stop-
       work date from March 2027 to August 2027 — past the grant end.

       But can QUASAR absorb the cost?

> smaug spend-plan QUASAR --if "Martinez=100%" --compare

Agent: QUASAR projected total goes from $613k to $681k. With $1.37M
       remaining on a $1.5M budget, that's negligible. QUASAR is fine.

       Before I recommend this, let me check project notes for context.

> smaug note list NEXUS

Agent: There's a note titled "Martinez Thesis Chapter 2" — Martinez is writing
       her second thesis chapter using NEXUS data, expected to finish by
       December 2026.

       Revised plan: keep Martinez on NEXUS at 50% through December 2026
       to finish the chapter, then shift to 100% QUASAR in January 2027.
       That still saves ~$19k over the final 6 months.

> smaug spend-plan NEXUS --if "Martinez=0%" --compare

Agent: Even with the delayed shift, the savings from January–June 2027
       are enough to extend past the grant end date.

       Recommendation:
       - Set Martinez's NEXUS end date to December 2026
       - Increase Martinez's QUASAR effort to 100% starting January 2027
       - Total effort stays at 100% throughout — no over-commitment
       - Martinez finishes her thesis chapter before the transition
```

**What makes this agentic:** The agent identifies candidates, simulates the change on both the source and destination accounts, checks that neither budget breaks, reads project notes to discover a thesis-related constraint it wasn't told about, and revises its plan to accommodate a timeline the PI didn't mention. The final recommendation is time-phased rather than immediate, reflecting context the optimizer alone would miss.

### Commands (if PI approves)

```bash
smaug set-end "Martinez" NEXUS 2026-12
smaug set-effort "Martinez" QUASAR 100%
```
