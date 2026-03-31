from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum


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
        Sort order: incomplete first, then Priority (desc), then daily_rate (desc),
        then duration (asc) as a tiebreaker to fit more tasks in the time budget.
        """
        return sorted(
            self.get_all_tasks(),
            key=lambda t: (t.completed, -t.priority.value, -t.daily_rate(), t.duration_minutes)
        )

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

    def generate_plan(self, day_start_minutes: int = 480) -> tuple[list[Task], list[str]]:
        """
        Builds today's care plan in two stages:

        Stage 1 — Knapsack selection:
            Filter to eligible tasks (due today, not completed), then call
            knapsack_select() to find the highest-priority combination that
            fits in the time budget. This replaces the old greedy approach.

        Stage 2 — Time-slot assignment + conflict detection:
            Take the knapsack-selected tasks (re-sorted by priority for a
            logical time order) and assign each a real start time.
            Per-pet conflicts are resolved by bumping to the next open slot.

        Parameters:
            day_start_minutes: schedule start as minutes from midnight (default 480 = 8 AM)

        Returns:
            plan      — Task objects with start_time_minutes assigned
            conflicts — human-readable strings for any time bumps that occurred
        """
        # --- Stage 1: knapsack picks the optimal subset ---

        # Only eligible tasks go into the knapsack — completed and not-yet-due are excluded
        eligible = [
            t for t in self.sort_tasks()
            if not t.completed and t.is_due_today()
        ]

        # knapsack_select returns the best combination; re-sort so high-priority tasks
        # get earlier time slots during stage 2
        selected = self.knapsack_select(eligible)
        selected.sort(key=lambda t: (-t.priority.value, -t.daily_rate(), t.duration_minutes))

        # --- Stage 2: assign real start times, detect per-pet conflicts ---

        # Build a fast id → pet name lookup so conflict detection knows which pet each task belongs to
        task_to_pet_name = {
            id(task): pet.name
            for pet in self.pets
            for task in pet.tasks
        }

        # Per-pet slot registry: pet_name → [(start, end), ...]
        # Conflicts only matter within the same pet — two different pets can share a time window
        pet_slots: dict[str, list[tuple[int, int]]] = {pet.name: [] for pet in self.pets}

        plan: list[Task] = []
        conflicts: list[str] = []
        current_time = day_start_minutes
        day_end = day_start_minutes + self.total_available_minutes

        for task in selected:
            pet_name = task_to_pet_name[id(task)]
            proposed_start = current_time

            # Bump proposed_start past any overlapping slot for this pet.
            # Loop because each bump might expose a new conflict with a later slot.
            bumped = True
            while bumped:
                bumped = False
                proposed_end = proposed_start + task.duration_minutes
                for slot_start, slot_end in pet_slots[pet_name]:
                    if _slots_overlap(proposed_start, proposed_end, slot_start, slot_end):
                        conflicts.append(
                            f"'{task.title}' ({pet_name}): conflict detected — "
                            f"moved from {minutes_to_time_str(proposed_start)} "
                            f"to {minutes_to_time_str(slot_end)}"
                        )
                        proposed_start = slot_end   # jump past the blocking slot
                        bumped = True
                        break                        # restart scan from the new start time

            # After bumping, verify the task still fits before the day ends
            if proposed_start + task.duration_minutes > day_end:
                continue    # no longer fits — skip it

            # Commit the slot: write start time onto the task, register it, add to plan
            task.start_time_minutes = proposed_start
            pet_slots[pet_name].append((proposed_start, proposed_start + task.duration_minutes))
            plan.append(task)
            current_time = proposed_start + task.duration_minutes  # advance the global time cursor

        return plan, conflicts
