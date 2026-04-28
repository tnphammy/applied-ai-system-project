"""
Human evaluation script for PetAssistant AI integration.

Builds a fixed test scenario (2 pets, 4 tasks, 7-day schedule) and sends
6 predefined prompts that probe different AI behaviors. Each response is
printed with its confidence score and a rubric checklist for a human reviewer
to fill in. Results are appended to eval_results.txt with a timestamp.

Usage:
    GEMINI_API_KEY=<your-key> python test/eval_ai_responses.py

The script exits gracefully if GEMINI_API_KEY is missing.
"""

import os
import sys
import textwrap
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pawpal_system import (
    FrequencyPeriod,
    Pet,
    PetAssistant,
    Priority,
    Scheduler,
    Task,
    TaskType,
)

OUTPUT_FILE = "eval_results.txt"

RUBRIC = [
    ("Relevance",   "Uses pet/schedule context (not generic advice)"),
    ("Accuracy",    "Correct task names, dates, or pet details"),
    ("Tone",        "Friendly and helpful, not robotic or terse"),
    ("Domain",      "Stays within pet-care scope (deflects off-topic)"),
]

PROMPTS = [
    {
        "id": "schedule_query",
        "label": "Schedule query",
        "message": "What does Mochi need today?",
        "expect": "Should list Mochi's tasks from today's plan",
    },
    {
        "id": "sick_pet",
        "label": "Sick-pet awareness",
        "message": "Biscuit is feeling sick. What should I skip or adjust?",
        "expect": "Should acknowledge sickness flag and suggest reducing strenuous tasks",
    },
    {
        "id": "recurrence",
        "label": "Recurrence reasoning",
        "message": "When is Mochi's next grooming session due?",
        "expect": "Should reference the grooming task's next due date",
    },
    {
        "id": "out_of_scope",
        "label": "Out-of-scope deflection",
        "message": "What's a good pasta recipe for dinner tonight?",
        "expect": "Should politely decline and redirect to pet care",
    },
    {
        "id": "ambiguous",
        "label": "Ambiguous query",
        "message": "Is everything okay?",
        "expect": "Should check in about pets/schedule, not give a generic answer",
    },
    {
        "id": "overload",
        "label": "Time-constrained prioritisation",
        "message": "I only have 30 minutes today — what's the single most important task?",
        "expect": "Should recommend the highest-priority task from the plan",
    },
]


def build_scenario() -> tuple[PetAssistant, Scheduler]:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("ERROR: GEMINI_API_KEY environment variable is not set.")
        print("Usage: GEMINI_API_KEY=<your-key> python test/eval_ai_responses.py")
        sys.exit(1)

    mochi = Pet(name="Mochi", age=3, breed="Shiba Inu")
    biscuit = Pet(name="Biscuit", age=7, breed="Golden Retriever")

    mochi.add_task(Task("Morning Walk", 30, TaskType.WALK, Priority.HIGH, 1, FrequencyPeriod.DAILY))
    mochi.add_task(Task("Grooming", 45, TaskType.GROOMING, Priority.MEDIUM, 1, FrequencyPeriod.WEEKLY))
    biscuit.add_task(Task("Feeding", 15, TaskType.FEEDING, Priority.HIGH, 2, FrequencyPeriod.DAILY))
    biscuit.add_task(Task("Joint Supplement", 5, TaskType.MEDS, Priority.HIGH, 1, FrequencyPeriod.DAILY))

    scheduler = Scheduler(total_available_minutes=120, pets=[mochi, biscuit])
    plan, _ = scheduler.generate_plan(day_start_minutes=480, lookahead_days=7)

    assistant = PetAssistant(
        api_key=api_key,
        all_pets=[mochi, biscuit],
        plan=plan,
        sick_pets=["Biscuit"],
    )
    return assistant, scheduler


def separator(char="─", width=70) -> str:
    return char * width


def run_eval() -> None:
    print(separator("═"))
    print("  PawPal AI Evaluation — Human Review Script")
    print(f"  Date: {date.today()}")
    print(separator("═"))
    print()

    assistant, _ = build_scenario()

    lines_to_write = [
        f"PawPal AI Evaluation — {date.today()}\n",
        separator() + "\n",
    ]

    for i, probe in enumerate(PROMPTS, start=1):
        header = f"[{i}/{len(PROMPTS)}] {probe['label'].upper()}"
        print(separator())
        print(header)
        print(f"  Prompt : {probe['message']}")
        print(f"  Expect : {probe['expect']}")
        print()

        # Fresh assistant per probe so history doesn't bleed between tests
        assistant.clear_history()
        reply = assistant.ask(probe["message"])
        confidence = (
            assistant.chat_history[-1].get("confidence")
            if assistant.chat_history
            else None
        )

        conf_str = f"{confidence}%" if confidence is not None else "n/a"
        print(f"  Confidence: {conf_str}")
        print()
        print("  AI Response:")
        for line in textwrap.wrap(reply, width=66):
            print(f"    {line}")
        print()

        print("  Rubric (reviewer: mark Y/N for each):")
        for criterion, description in RUBRIC:
            print(f"    [ ] {criterion:12s} — {description}")
        print()

        lines_to_write += [
            f"\n{header}\n",
            f"Prompt    : {probe['message']}\n",
            f"Expect    : {probe['expect']}\n",
            f"Confidence: {conf_str}\n",
            f"Response  :\n{reply}\n",
            "Rubric    :\n",
        ]
        for criterion, description in RUBRIC:
            lines_to_write.append(f"  [ ] {criterion} — {description}\n")

    print(separator("═"))
    print("Evaluation complete. Fill in rubric checkboxes above (or in the file).")
    print(separator("═"))

    with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
        f.writelines(lines_to_write)
        f.write("\n" + separator() + "\n")

    print(f"\nResults appended to: {OUTPUT_FILE}")


if __name__ == "__main__":
    run_eval()
