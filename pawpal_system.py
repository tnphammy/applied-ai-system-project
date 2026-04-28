from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum
from google import genai
from google.genai import types
# import google.generativeai as genai



# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TaskType(Enum):
    """Categories of pet care tasks drawn directly from the README."""
    WALK = "walk"
    FEEDING = "feeding"
    MEDS = "meds"
    ENRICHMENT = "enrichment"
    GROOMING = "grooming"


class Priority(Enum):
    """
    Integer values allow direct comparison and sorting (higher = more urgent).
    e.g. Priority.HIGH > Priority.LOW evaluates cleanly using .value.
    """
    LOW = 1
    MEDIUM = 2
    HIGH = 3


class FrequencyPeriod(Enum):
    """
    Represents the time window for a task's frequency.
    The integer value is the number of days in that period — this lets you
    normalize any frequency to a daily rate for sorting/comparison:

        daily_rate = times_per_period / period.value

    Example:
        "twice a day"  → times_per_period=2, period=DAILY  → rate = 2.0
        "twice a week" → times_per_period=2, period=WEEKLY → rate ≈ 0.29
    """
    DAILY = 1
    WEEKLY = 7
    MONTHLY = 30


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------

@dataclass
class Task:
    """
    A single pet care activity. This is the core unit the Scheduler works with.

    Design notes:
    - `title` is for display; `description` is for longer optional detail.
    - `duration_minutes` is in minutes — keep units consistent when summing
      against Scheduler.total_available_minutes.
    - Frequency is split into two fields (times_per_period + period) instead of
      a single value because "twice a day" and "twice a week" share the number 2
      but mean very different things. Normalize with: times_per_period / period.value
    - `completed` lets generate_plan() skip tasks already done today.
    """
    title: str
    duration_minutes: int
    type: TaskType
    priority: Priority
    times_per_period: int       # how many times the task occurs within the period
    period: FrequencyPeriod     # the time window: daily, weekly, or monthly

    # Optional fields with defaults — must come after required fields in dataclasses
    description: str = ""
    completed: bool = False
    # Stores the date this task was last marked complete; None means it has never been done
    last_completed_date: date | None = None
    # Assigned by generate_plan() — minutes from midnight (e.g. 9:00 AM = 540).
    # None until the scheduler places this task into a time slot.
    start_time_minutes: int | None = None

    def daily_rate(self) -> float:
        """Returns how often this task occurs per day — useful for sorting by urgency."""
        return self.times_per_period / self.period.value

    def next_due_date(self) -> date:
        """
        Computes the next date this task should be done.

        Formula: last_completed_date + (period_days / times_per_period)
        Example: a task done 2x per week last completed Monday →
                 7 days / 2 = 3.5 days → due Thursday

        If the task has never been completed, it is due today.
        """
        if self.last_completed_date is None:
            return date.today()   # never done → due immediately
        interval_days = self.period.value / self.times_per_period
        return self.last_completed_date + timedelta(days=interval_days)

    def is_due_today(self) -> bool:
        """Returns True if this task's next due date is today or already past."""
        return self.next_due_date() <= date.today()

    def set_title(self, title: str) -> None:
        self.title = title

    def set_description(self, description: str) -> None:
        self.description = description

    def set_duration(self, duration_minutes: int) -> None:
        self.duration_minutes = duration_minutes

    def set_priority(self, priority: Priority) -> None:
        self.priority = priority

    def set_frequency(self, times_per_period: int, period: FrequencyPeriod) -> None:
        """Set both frequency fields together to avoid them getting out of sync."""
        self.times_per_period = times_per_period
        self.period = period

    def mark_complete(self) -> None:
        """Mark done and record today's date so next_due_date() can compute the next interval."""
        self.completed = True
        self.last_completed_date = date.today()

    def unmark_complete(self) -> None:
        """
        Reverses a mark_complete() call made today.
        Resets completed and clears last_completed_date so the task is treated
        as never done — next_due_date() returns today again and the scheduler
        will include it in the next plan generation.
        """
        self.completed = False
        self.last_completed_date = None


# ---------------------------------------------------------------------------
# Pet
# ---------------------------------------------------------------------------

@dataclass
class Pet:
    """
    Stores pet info and owns the pet's task list.
    Pet is the single source of truth for its tasks — the Scheduler reads
    from Pet, it does not maintain a separate copy.
    """
    name: str
    age: int        # age in years; relevant for scheduling (e.g. senior pets, puppies)
    breed: str
    tasks: list[Task] = field(default_factory=list)
    task_count: int = 0     # mirrors len(self.tasks); kept in sync by add_task/remove_task

    def add_task(self, task: Task) -> None:
        self.tasks.append(task)
        self.task_count += 1

    def remove_task(self, task: Task) -> None:
        self.tasks.remove(task)
        self.task_count -= 1

    def get_name(self) -> str:
        return self.name

    def set_name(self, name: str) -> None:
        self.name = name

    def get_age(self) -> int:
        return self.age

    def set_age(self, age: int) -> None:
        self.age = age

    def get_breed(self) -> str:
        return self.breed

    def set_breed(self, breed: str) -> None:
        self.breed = breed


# ---------------------------------------------------------------------------
# Owner
# ---------------------------------------------------------------------------

@dataclass
class Owner:
    """
    Manages one or more pets and provides access to all of their tasks.
    Owner is a data container — scheduling logic lives in Scheduler, not here.
    """
    name: str
    pets: list[Pet] = field(default_factory=list)   # supports multiple pets

    def add_owner_name(self, name: str) -> None:
        self.name = name

    def edit_owner_name(self, new_name: str) -> None:
        self.name = new_name

    def add_pet(self, pet: Pet) -> None:
        self.pets.append(pet)

    def remove_pet(self, pet: Pet) -> None:
        self.pets.remove(pet)

    def get_all_tasks(self) -> list[Task]:
        """
        Aggregates tasks across all pets into a flat list.
        Useful for giving the Scheduler a flat view of everything that needs doing.
        """
        return [task for pet in self.pets for task in pet.tasks]


# ---------------------------------------------------------------------------
# Time-slot helpers
# ---------------------------------------------------------------------------

def minutes_to_time_str(minutes: int) -> str:
    """
    Converts minutes-from-midnight to a readable 12-hour clock string.
    Example: 540 → '9:00 AM',  795 → '1:15 PM'
    Used both for display and for building conflict warning messages.
    """
    h, m = divmod(minutes, 60)
    period = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12          # convert 0 and 12 to 12; everything else mod 12
    return f"{h12}:{m:02d} {period}"


def _slots_overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    """
    Returns True if two time windows share any overlap.
    Works for all cases: partial overlap, one fully inside the other, etc.

    The condition reads: A starts before B ends, AND B starts before A ends.
    If either half is False, the slots are completely separate.

    Example:
        A = [60, 90],  B = [80, 120]  → 60 < 120 AND 80 < 90  → True (overlap)
        A = [60, 90],  B = [90, 120]  → 60 < 120 AND 90 < 90  → False (back-to-back, no overlap)
    """
    return a_start < b_end and b_start < a_end


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

@dataclass
class Scheduler:
    """
    The brain of the system. Reads tasks from pets, applies constraints,
    and produces a daily plan.

    Design notes:
    - Scheduler holds pets (not tasks directly) because tasks live on Pet.
      This avoids duplicating task lists and keeps Pet as the single source
      of truth. Tasks are accessed via get_all_tasks().
    - total_available_minutes is the daily time budget. Without it, generate_plan()
      has no constraint and would just return everything — which defeats the purpose.
    - sort_tasks() and generate_plan() respect both Priority and daily_rate()
      when deciding what makes the cut.
    """
    total_available_minutes: int
    pets: list[Pet] = field(default_factory=list)

    def add_pet(self, pet: Pet) -> None:
        self.pets.append(pet)

    def remove_pet(self, pet: Pet) -> None:
        self.pets.remove(pet)

    def get_all_tasks(self) -> list[Task]:
        """Collects tasks from every pet into a single flat list."""
        return [task for pet in self.pets for task in pet.tasks]

    def sort_tasks(self) -> list[Task]:
        """
        Returns tasks sorted by scheduling priority.
        Sort order: Priority (desc) → daily_rate (desc) → duration (asc).
        completed is no longer part of this key — generate_plan() separates
        pending from done before calling sort_tasks(), so mixing them here
        would cause already-done tasks to compete with pending ones.
        """
        return sorted(
            self.get_all_tasks(),
            key=lambda t: (-t.priority.value, -t.daily_rate(), t.duration_minutes)
        )

    def filter_tasks(
        self,
        plan: list[Task],
        completed: bool | None = None,
        pet_name: str | None = None,
    ) -> list[Task]:
        """
        Returns a filtered subset of a generated plan.

        Arguments:
          completed — True: only done tasks | False: only pending | None: no filter
          pet_name  — keep only tasks belonging to this pet  | None: no filter

        Both filters apply together (AND logic), so
        filter_tasks(plan, completed=False, pet_name="Amie") returns
        only Amie's incomplete tasks.

        Builds a task → pet name lookup internally so Task doesn't need a
        back-reference to its Pet (which we deliberately removed from the design).
        """
        # Map each Task object's id to its owner's name using the Scheduler's pet list
        task_to_pet = {id(task): pet.name for pet in self.pets for task in pet.tasks}

        result = plan
        if completed is not None:
            # Keep tasks whose completed flag matches the requested status
            result = [t for t in result if t.completed == completed]
        if pet_name is not None:
            # Keep tasks that belong to the requested pet
            result = [t for t in result if task_to_pet.get(id(t)) == pet_name]
        return result

    def sort_by_time(self, plan: list[Task], reverse: bool = False) -> list[Task]:
        """
        Sorts a generated plan by start time, earliest first by default.
        Pass reverse=True to get latest-first order.

        Only call this on the output of generate_plan() — start_time_minutes
        is None on unscheduled tasks and will raise a TypeError if compared.
        """
        return sorted(plan, key=lambda t: t.start_time_minutes, reverse=reverse)

    def knapsack_select(self, tasks: list[Task]) -> list[Task]:
        """
        Picks the combination of tasks with the highest total priority score
        that fits within total_available_minutes. Uses the 0/1 bounded knapsack
        algorithm — each task can only be picked once (0 = skip, 1 = take).

        Why not just sort by priority and grab greedily?
        Greedy can lock in one long task and miss two shorter ones whose combined
        priority is higher. Knapsack evaluates every valid combination and finds
        the true best.

        How the DP table works (think of it as a grid):
          - Rows  = tasks, added one at a time (row 0 = no tasks considered yet)
          - Cols  = every possible minute budget from 0 → total_available_minutes
          - Cell  = best priority score achievable with those tasks and that much time

        For each cell we ask: is it better to SKIP this task (copy score from row above)
        or TAKE it (look up the score with less time remaining, then add this task's value)?
        We keep whichever is higher.

        After filling the grid, we backtrack from the bottom-right corner:
        if a cell's score differs from the one directly above it, that task was taken.
        """
        T = self.total_available_minutes
        n = len(tasks)

        # Build the DP grid — (n+1) rows × (T+1) cols, all starting at 0
        # Row 0 represents "no tasks considered", so score is always 0
        dp = [[0] * (T + 1) for _ in range(n + 1)]

        for i, task in enumerate(tasks, start=1):
            w = task.duration_minutes   # "weight" — how much time this task costs
            v = task.priority.value     # "value"  — the score we gain by taking it

            for t in range(T + 1):
                # Option A: skip this task — inherit the best score without it
                dp[i][t] = dp[i - 1][t]

                # Option B: take this task — only valid if it physically fits
                if t >= w:
                    take_score = dp[i - 1][t - w] + v   # score before this task + this task's value
                    if take_score > dp[i][t]:
                        dp[i][t] = take_score            # taking is better — overwrite

        # Backtrack from bottom-right to recover which tasks were selected.
        # If dp[i][t] != dp[i-1][t], the score only changed because task i was taken.
        selected = []
        t = T
        for i in range(n, 0, -1):
            if dp[i][t] != dp[i - 1][t]:       # score changed → task i was included
                selected.append(tasks[i - 1])
                t -= tasks[i - 1].duration_minutes  # reclaim the time it used

        return selected

    def generate_plan(
        self,
        day_start_minutes: int = 480,
        lookahead_days: int = 7,
    ) -> tuple[dict[date, list[Task]], list[str]]:
        """
        Builds a multi-day care plan grouped by due date.

        Today's section — two stages:
          1. Knapsack selects the highest-priority pending tasks that fit the time budget.
          2. Time-slot assignment gives each selected task a real start time.
             Already-completed-today tasks are appended after (no slot needed).

        Future sections (days 1..lookahead_days):
          Tasks are grouped by next_due_date() with no time-slot assignment —
          we don't know the owner's schedule for future days yet.

        Parameters:
            day_start_minutes : schedule start as minutes from midnight (default 480 = 8 AM)
            lookahead_days    : how many days ahead to include future tasks (default 7)

        Returns:
            plan      — {date: [Task, ...]} sorted chronologically
            conflicts — human-readable strings for any time bumps that happened today
        """
        today     = date.today()
        all_tasks = self.get_all_tasks()

        # --- Today: separate pending from already-done-today ---

        # Pending = due today AND not yet completed in this session
        pending_today = [t for t in self.sort_tasks() if t.is_due_today() and not t.completed]

        # Done today = completed flag is True AND last_completed_date is today
        done_today = [t for t in all_tasks if t.completed and t.last_completed_date == today]

        # Knapsack picks the best-fit subset; re-sort for chronological time-slot assignment
        selected = self.knapsack_select(pending_today)
        selected.sort(key=lambda t: (-t.priority.value, -t.daily_rate(), t.duration_minutes))

        # --- Time-slot assignment + conflict detection for today's pending tasks ---

        task_to_pet_name = {id(task): pet.name for pet in self.pets for task in pet.tasks}
        pet_slots: dict[str, list[tuple[int, int]]] = {pet.name: [] for pet in self.pets}

        today_scheduled: list[Task] = []
        conflicts: list[str] = []
        current_time = day_start_minutes
        day_end      = day_start_minutes + self.total_available_minutes

        for task in selected:
            pet_name       = task_to_pet_name[id(task)]
            proposed_start = current_time

            # Bump past any same-pet conflicts; loop because each bump may expose another
            bumped = True
            while bumped:
                bumped        = False
                proposed_end  = proposed_start + task.duration_minutes
                for slot_start, slot_end in pet_slots[pet_name]:
                    if _slots_overlap(proposed_start, proposed_end, slot_start, slot_end):
                        conflicts.append(
                            f"'{task.title}' ({pet_name}): conflict — "
                            f"moved from {minutes_to_time_str(proposed_start)} "
                            f"to {minutes_to_time_str(slot_end)}"
                        )
                        proposed_start = slot_end
                        bumped         = True
                        break

            if proposed_start + task.duration_minutes > day_end:
                continue    # bumped past end of day — drop it

            task.start_time_minutes = proposed_start
            pet_slots[pet_name].append((proposed_start, proposed_start + task.duration_minutes))
            today_scheduled.append(task)
            current_time = proposed_start + task.duration_minutes

        # Today's section = scheduled pending tasks first, then already-done tasks
        plan: dict[date, list[Task]] = {today: today_scheduled + done_today}

        # --- Future days: group by next_due_date() ---

        lookahead_end = today + timedelta(days=lookahead_days)

        for task in all_tasks:
            due = task.next_due_date()
            # Skip today (handled above) and anything beyond the lookahead window
            if due <= today or due > lookahead_end:
                continue
            if due not in plan:
                plan[due] = []
            plan[due].append(task)

        # Return sorted by date so the UI can iterate chronologically
        return dict(sorted(plan.items())), conflicts

# ---------------------------------------------------------------------------
# PetAssistant
# ---------------------------------------------------------------------------
@dataclass
class PetAssistant:
    """
    Bridges the Streamlit UI and Gemini API.
    Holds live app state (pets, plan, sick flags) and conversation history
    so every API call is grounded in the owner's actual schedule.
    """
    # api_key is a constructor parameter — when app.py creates PetAssistant(...),
    # it passes st.secrets["GEMINI_API_KEY"] here so this class never touches Streamlit.
    api_key: str
    all_pets: list[Pet] = field(default_factory=list)
    plan: dict[date, list[Task]] | None = None
    sick_pets: list[str] = field(default_factory=list)       # pet names flagged as unwell
    chat_history: list[dict] = field(default_factory=list)   # full conversation for multi-turn context

    def ask(self, user_message: str) -> str:
        """
        Main pipeline entry — called from app.py when the owner submits a message.
        Input:  user_message: str
        Output: reply: str  (displayed in st.chat_message)
        """
        # 1. Append user turn to internal history using "user"/"assistant" roles.
        #    We keep this format so app.py can pass msg["role"] to st.chat_message()
        #    without any translation — "assistant" renders the correct avatar there.
        self.chat_history.append({"role": "user", "content": user_message})

        # 2. Convert internal history to Gemini's format before the API call.
        #    Gemini requires role "model" where we store "assistant", and wraps
        #    the text in a "parts" list instead of a flat "content" string.
        gemini_contents = [
            {
                "role": "model" if msg["role"] == "assistant" else "user",
                "parts": [{"text": msg["content"]}],
            }
            for msg in self.chat_history
        ]

        # 3. Merge persona + live app data into one system_instruction string.
        #    Gemini reads this before any contents, so the model knows who it is
        #    AND what the owner's current schedule looks like on every call.
        system_instruction = (
            f"{self.build_system_prompt()}\n\n"
            f"{self.build_context_block()}"
        )

        # 4. Call Gemini API.
        #    - contents: list[dict] — the full conversation in Gemini's format
        #    - system_instruction: str — persona + context, injected before contents
        #    - max_output_tokens: caps the reply length
        # client = genai.Client(api_key=self.api_key)
        # response = client.models.generate_content(
        #     model="gemini-2.0-flash",
        #     contents=gemini_contents,
        #     config=types.GenerateContentConfig(
        #         system_instruction=system_instruction,
        #         max_output_tokens=1024,
        #     ),
        # )


        # genai.configure(api_key=self.api_key)
        # client = genai.GenerativeModel(
        #     model_name="gemini-1.5-flash",  
        #     system_instruction=self.build_system_prompt(),
        # )
        # response = client.generate_content(messages_with_context)
        # reply: str = response.text



        # client = genai.Client()

        # response = client.models.generate_content(
        #     model="gemini-3-flash-preview", contents="Explain how AI works in a few words"
        # )

        client = genai.Client(api_key=self.api_key)   # pass key — Client() alone uses env var, not self.api_key
        response = client.models.generate_content(
            model="gemini-3-flash-preview",                  # gemini-3-flash-preview doesn't exist yet
            config=types.GenerateContentConfig(
                system_instruction=system_instruction),
            contents=gemini_contents                   # use converted format, not self.chat_history
        )

        print(response.text)

        # 5. response.text is a str — Gemini flattens the reply for us
        reply: str = response.text

        # 6. Save assistant turn so the next question remembers this answer
        self.chat_history.append({"role": "assistant", "content": reply})

        return reply

    def clear_history(self) -> None:
        """Wipes conversation history — call when starting a fresh session."""
        self.chat_history.clear()

    def build_system_prompt(self) -> str:
        """
        Returns the static persona string passed to system_instruction= in every API call.
        Output: str — Gemini reads this before any contents.
        """
        return (
            "You are PawPal, a friendly and knowledgeable pet care assistant. "
            "You help owners stay on top of their pets' schedules and wellbeing. "
            "Answer concisely and warmly. Never make up medication names or dosages."
        )

    def build_context_block(self) -> str:
        """
        Assembles self.all_pets, self.plan, and self.sick_pets into a plain-text
        string injected into every API call so Claude knows the owner's live data.
        Output: str
        """
        lines = []

        # Pet profiles: "Pets: Mochi (3yo Shiba Inu), Biscuit (7yo Golden Retriever)"
        if self.all_pets:
            profiles = ", ".join(f"{p.name} ({p.age}yo {p.breed})" for p in self.all_pets)
            lines.append(f"Pets: {profiles}")

        # Sick flags: join names and choose singular/plural verb
        if self.sick_pets:
            names = ", ".join(self.sick_pets)
            verb  = "is" if len(self.sick_pets) == 1 else "are"
            lines.append(f"⚠️ {names} {verb} unwell.")

        # Today's schedule and upcoming tasks
        lines.append(self.format_today_summary())
        lines.append(self.format_upcoming_summary(days=7))

        return "\n".join(lines)

    def format_today_summary(self) -> str:
        """
        Formats today's tasks from self.plan into a readable string.
        Output: str
        """
        if not self.plan:
            return "No schedule generated yet."

        # .get() safely returns [] if today has no entry — avoids KeyError
        today_tasks: list[Task] = self.plan.get(date.today(), [])
        if not today_tasks:
            return "Today: no tasks scheduled."

        lines = ["Today's schedule:"]
        for t in today_tasks:
            time_str = minutes_to_time_str(t.start_time_minutes) if t.start_time_minutes else "—"
            status   = "✓" if t.completed else time_str
            lines.append(f"  {status} {t.title} ({t.duration_minutes} min, {t.priority.name})")
        return "\n".join(lines)

    def format_upcoming_summary(self, days: int) -> str:
        """
        Iterates self.plan for dates between tomorrow and today + `days`.
        Input: days: int   Output: str
        """
        if not self.plan:
            return ""

        today   = date.today()
        cutoff  = today + timedelta(days=days)
        lines   = ["Upcoming:"]
        found   = False

        for plan_date, tasks in self.plan.items():
            if plan_date <= today or plan_date > cutoff:
                continue                                  # skip today and out-of-window dates
            lines.append(f"  {plan_date.strftime('%a %b %-d')}:")
            for t in tasks:
                lines.append(f"    - {t.title} ({t.priority.name})")
            found = True

        return "\n".join(lines) if found else "No upcoming tasks this week."

