# PawPal+

PawPal+ is a pet care scheduling assistant for busy owners who want to go past a simple to-do list. It uses a 0/1 knapsack algorithm to build the highest-priority care plan that actually fits your time budget, and a Google Gemini-powered chat assistant that uses your pets' real schedules so the advice it gives is grounded in your actual day — not generic pet tips. 

<a href="demo-screenshot.png"><img src="./assets/demo.png" alt="PawPal+ app screenshot" width="100%"/></a>

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Setup Instructions](#setup-instructions)
- [Sample Interactions](#sample-interactions)
- [Design Decisions](#design-decisions)
- [Testing Summary](#testing-summary)
- [Reflection](#reflection)

---

## Architecture Overview

The system is split into three layers that talk to each other in one direction: the data model feeds the scheduler, the scheduler feeds the UI and AI assistant.

```
┌─────────────────────────────────────────────────┐
│                  Streamlit UI (app.py)           │
│  Owner → Pets → Tasks → Schedule → Chat sidebar │
└────────────────────┬────────────────────────────┘
                     │
          ┌──────────┴──────────┐
          │                     │
┌─────────▼──────────┐  ┌──────▼──────────────────┐
│   Scheduler        │  │   PetAssistant           │
│   (pawpal_system)  │  │   (pawpal_system)        │
│                    │  │                          │
│  knapsack_select() │  │  ask() → Gemini API      │
│  generate_plan()   │  │  build_context_block()   │
│  sort/filter       │  │  _parse_confidence()     │
└─────────┬──────────┘  └──────────────────────────┘
          │
┌─────────▼──────────────────────────────┐
│   Data Model (pawpal_system)           │
│   Task · Pet · Owner · Enums           │
└────────────────────────────────────────┘
```

**Data model** — Four dataclasses: `Task` (what needs doing, how long, how often, how urgent), `Pet` (owns its own task list), `Owner` (holds pets, provides a flat task view), and three enums (`TaskType`, `Priority`, `FrequencyPeriod`) that keep values consistent across the whole system.

**Scheduler** — Takes all pets' tasks, runs a 0/1 knapsack DP to select the best-fit subset for today, assigns real start times back-to-back, and groups future tasks by `next_due_date()` for the upcoming view. Returns a `dict[date, list[Task]]`.

**PetAssistant** — Wraps the Gemini API. On every call it builds a context block from live app state (pet profiles, sick flags, today's schedule, 7-day upcoming), injects it as a system instruction, and maintains multi-turn conversation history. Every response is logged to `pawpal_ai.log`, parsed for a confidence score, and stored in `chat_history` so the UI can surface both.

---

## Setup Instructions

### Prerequisites

- Python 3.11+
- A Google Gemini API key ([get one here](https://aistudio.google.com/app/apikey))

### 1. Clone and create a virtual environment

```bash
git clone <your-repo-url>
cd applied-ai-system-project

python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Add your API key

Create the file `.streamlit/secrets.toml` (this stays out of version control):

```toml
GEMINI_API_KEY = "your-key-here"
```

### 4. Run the app

```bash
streamlit run app.py
```

Opens at `http://localhost:8501`. Fill in the four steps from top to bottom — owner name, pets, tasks, then generate your schedule.

### 5. Run the tests

```bash
# Original scheduling logic tests (34 tests, no API key needed)
python -m pytest test/test_pawpal.py -v

# AI integration tests (23 tests, no API key needed — fully mocked)
python -m pytest test/test_ai_integration.py -v

# Human evaluation script (requires real API key)
GEMINI_API_KEY=your-key python test/eval_ai_responses.py
```

---

## Sample Interactions

These examples use a scenario with two pets: Mochi (3yo Shiba Inu) and Biscuit (7yo Golden Retriever, flagged as unwell). The schedule has a morning walk, grooming, feeding, and joint supplements loaded in.

---

**Example 1 — Schedule query**

> **You:** What does Mochi need today?

> **PawPal:** Hey! Based on today's schedule, Mochi has two things lined up: a 30-minute Morning Walk starting at 8:00 AM (HIGH priority) and a Grooming session for 45 minutes at 8:30 AM (MEDIUM priority). The walk is due daily so definitely don't skip it — the grooming is weekly and today's the day it cycles back around. You've got about 75 minutes of Mochi-time blocked in total, so plan accordingly!
>
> *(Confidence: 92%)*

---

**Example 2 — Sick pet awareness**

> **You:** Biscuit hasn't been herself lately. Should I change anything about her routine?

> **PawPal:** Since Biscuit is flagged as unwell, I'd keep her Joint Supplement on schedule — that's HIGH priority and especially important when she's not feeling great. For the Feeding, stick with normal timing but maybe watch her appetite and portion down if she seems off. I'd hold off on anything more physically demanding until she's back to herself. Hope she feels better soon — senior dogs can bounce back fast when they're well-rested!
>
> *(Confidence: 78%)*

---

**Example 3 — Time-constrained prioritisation**

> **You:** I only have 20 minutes this morning. What's the one thing I absolutely have to do?

> **PawPal:** If you've only got 20 minutes, go straight to Biscuit's Joint Supplement — it's a 5-minute HIGH-priority task and missing it consistently can really affect her mobility long-term. After that, Mochi's Feeding (15 min, HIGH priority) fits right in your window too. You'd be cutting the walk, but both of those are more time-sensitive than exercise when you're tight on time. Make up the walk later in the day if you can!
>
> *(Confidence: 85%)*

---

## Design Decisions

**Knapsack over greedy scheduling**

The first instinct for fitting tasks into a time budget is to sort by priority and grab them one by one until you run out of time. The problem is that greedy locks in whatever task it picks first, even if two smaller tasks together score higher. The classic case: one HIGH-priority 90-minute task (score = 3) versus two MEDIUM-priority 50-minute tasks (combined score = 4) in a 100-minute budget. Greedy takes the HIGH task and blocks the two MEDIUMs. Knapsack evaluates every combination via dynamic programming and picks the two MEDIUMs because 4 > 3. That feels like the correct behavior for a care app where the owner's overall wellbeing coverage matters more than maximizing any single task's priority.

**Tasks live on Pet, not Scheduler**

The original design had the Scheduler owning the task list. That created an annoying problem: the Scheduler needed to track which tasks belonged to which pet in order to do conflict detection and filtering, which meant maintaining a separate mapping that had to stay in sync with the actual task data. Moving tasks onto `Pet` made `Pet` the single source of truth and let the Scheduler just iterate `pet.tasks` directly. The Scheduler ended up cleaner and Pet ended up more useful.

**`daily_rate` as a tiebreaker**

Priority alone creates ties. A daily 10-minute feeding and a weekly 10-minute check both have MEDIUM priority — but the feeding is objectively more urgent because it needs to happen today. The secondary sort key `daily_rate = times_per_period / period.value` breaks those ties naturally by how often the task recurs. A twice-daily task rates higher than a twice-weekly one even at the same priority level.

**Confidence scoring baked into every AI response**

Rather than hoping the AI sounds confident, the system prompt instructs Gemini to append `[Confidence: N%]` to every reply. A regex strips the tag from the displayed text and stores the integer score in `chat_history` alongside the response. This means confidence is always available to the UI without a second API call, and it's automatically tested — if the tag is missing or malformed, the parser returns `None` gracefully.

**Logging from day one**

Every `ask()` call logs the message length, history length, API result, and confidence score to `pawpal_ai.log`. Any exception logs the full error type and message before returning a fallback string. This wasn't an afterthought — knowing what failed and why is the difference between debugging a real app and guessing in the dark.

---

## Testing Summary

**What the tests cover**

The project has two test suites, 57 tests total, all passing with zero API calls required.

`test/test_pawpal.py` (34 tests) covers the original scheduling logic:
- **Knapsack optimality** — the "two MEDIUMs beat one HIGH" case that greedy fails
- **Recurrence math** — `next_due_date()` for daily, weekly, and monthly tasks; overdue handling; `unmark_complete()` resetting the chain
- **Time-slot assignment** — same-pet tasks land in non-overlapping slots; tasks too long for the budget are excluded
- **Sort and filter** — both sort directions, filter by status, filter by pet, and both combined

`test/test_ai_integration.py` (23 tests) covers the AI layer:
- **Pure-logic tests** — `build_system_prompt`, `build_context_block`, format helpers, `_parse_confidence` — no API key, no network
- **Mocked integration tests** — `ask()` happy path, history growth, confidence stored correctly, API failure returning a graceful fallback, empty response handled

The mocked tests use `unittest.mock.patch` on `genai.Client`, so the whole AI pipeline runs end-to-end in terms of logic but without touching the network. This was the right call: it means CI can run the suite on any machine without credentials, and failures actually point to logic bugs rather than network flakiness.

**What didn't work (and what I learned from it)**

The conflict detection code (`pawpal_system.py`, the block that bumps a task when it overlaps an existing slot) turns out to be unreachable under the current sequential scheduling algorithm. Because `current_time` always advances forward after each task, two tasks from the same pet can never overlap — the algorithm prevents the problem before the conflict check even runs. The code is correct, it just never fires. The test suite caught this by failing on an assumption that wasn't true, which led to a more interesting discovery: dead code hiding in a tested codebase. If the scheduler ever gains support for user-specified start times, that path would finally be exercised.

I also learned that mocking is genuinely useful, not just a test trick. Testing `ask()` behavior — error handling, fallback strings, history management — without an API key means those tests are stable and fast. The real API behavior gets validated separately through the human evaluation script, which is where the question "does it actually give good advice?" belongs anyway.

---

## Reflection

The biggest thing this project taught me is that "works" has two very different meanings depending on what you're building. For the scheduling logic, "works" is binary and verifiable — either the knapsack finds the optimal combination or it doesn't, and a test tells you which. For the AI integration, "works" is probabilistic and contextual, and that gap changes everything about how you design and test the system.

**Limitations and biases in the system**

The most honest limitation is that the scheduler's only measure of value is priority score, and priority is entirely self-reported by the owner. If someone marks a daily walk as HIGH and a medication as LOW, the algorithm respects that — it has no way to know that one of those actually matters more for the pet's health. Garbage in, garbage out. The knapsack finds the optimal combination given the inputs, but it can't correct for inputs that don't reflect reality.

On the AI side, the model only knows what's inside the context block. It can't look up real veterinary information, and the system prompt deliberately says "never make up medication names or dosages" — which is the right call, but it also means the assistant will sometimes give genuinely vague answers when a specific answer would require actual medical knowledge it doesn't have. The confidence score helps signal this, but it's self-reported by the model and not externally calibrated. An 85% confidence rating doesn't mean the answer is correct 85% of the time — it means the model thinks it's probably right, which is a weaker claim than it sounds.

There's also no feedback loop. The system doesn't learn from corrections or track whether advice was actually followed. Every session starts fresh.

**Could the AI be misused?**

The scope is intentionally narrow — a pet care scheduling assistant — but the underlying model is general-purpose, so there's nothing technically stopping someone from trying to use it for medical advice, off-topic content, or prompt injection via pet names and task titles. Right now the main guardrail is the context injection itself: anchoring every call to the owner's actual pets and schedule naturally keeps responses in scope most of the time. The "never make up medications" instruction in the system prompt is a lightweight second guardrail.

For anything beyond a class project, I'd add input sanitization on pet names and task titles (both get embedded into the system instruction), topic guardrails that detect and deflect out-of-scope requests more reliably, and rate limiting on the API calls. The current implementation trusts the user entirely, which is fine for a controlled demo but not for a real product.

**What surprised me while testing reliability**

The confidence score turned out to be less informative than I expected. I assumed it would be a useful signal — high confidence means good answer, low confidence means be careful. In practice, Gemini would sometimes give low-confidence answers that were completely correct and specific, and high-confidence answers that were fine but generic enough to apply to any pet. The score reflects the model's self-assessment of certainty, not actual accuracy, and those two things aren't the same.

What did work better than expected was the context injection. When the assistant had access to the actual pet names, task details, and schedule, the responses were noticeably more useful than what you'd get from a generic pet care chatbot. Asking "what should I do about Biscuit today?" got a genuinely specific answer that referenced her actual tasks. That specificity only exists because of the pipeline design — the model isn't smarter, it just has better information.

The mocking setup also taught me something. Most of the AI behavior I was testing in the automated suite was actually my own pipeline logic — history growth, context building, fallback handling — not the model itself. Which is correct: those are the parts I own and can assert on. But it was a useful reality check that "testing the AI" and "testing the code around the AI" are different things, and only one of them is really in my control.

**Collaboration with AI — the helpful and the wrong**

The most useful AI suggestion in this project was the knapsack algorithm itself. I knew I wanted something smarter than greedy scheduling, but I'd never actually implemented a DP knapsack before. Walking through the logic with Claude — why the grid approach works, how to trace the backtrack to recover selected items, why it handles ties better than sorting — was genuinely educational. The algorithm went from something I'd heard of in a data structures class to something I can explain and debug. That's the kind of collaboration that actually transfers.

The most concrete example of a wrong suggestion also came from Claude Code. My original implementation used `model="gemini-3-flash-preview"`, which is the model I had access to and intentionally chose. Claude, whose knowledge has a cutoff date, didn't know Gemini 3 existed yet — so it "corrected" the model string to `"gemini-2.0-flash"` as if `gemini-3-flash-preview` was a typo or a made-up name. That change went in, and it caused billing errors because the two models are priced differently. It confidently edited incorrectly, but I understand the shortcoming.

It is important to note AI assistants have knowledge cutoffs, and they don't always know what they don't know. When Claude corrected my model name, it wasn't hallucinating exactly — it was making a reasonable inference from outdated information and presenting it as a fix. The right response was to verify the suggestion against the actual API documentation before accepting it, which I didn't do that time. I do now.
