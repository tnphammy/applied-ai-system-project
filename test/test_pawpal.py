import pytest
from datetime import date, timedelta
from pawpal_system import Owner, Pet, Task, Scheduler, TaskType, Priority, FrequencyPeriod


# ---------------------------------------------------------------------------
# Fixtures — reusable objects shared across tests
# ---------------------------------------------------------------------------

@pytest.fixture
def basic_task():
    """A standard incomplete task used as a baseline."""
    return Task(
        title="Morning Walk",
        duration_minutes=30,
        type=TaskType.WALK,
        priority=Priority.HIGH,
        times_per_period=1,
        period=FrequencyPeriod.DAILY,
    )

@pytest.fixture
def another_task():
    """A second distinct task for isolation checks."""
    return Task(
        title="Feeding",
        duration_minutes=10,
        type=TaskType.FEEDING,
        priority=Priority.HIGH,
        times_per_period=2,
        period=FrequencyPeriod.DAILY,
    )

@pytest.fixture
def low_priority_task():
    """A low priority task useful for scheduler edge cases."""
    return Task(
        title="Brushing",
        duration_minutes=45,
        type=TaskType.GROOMING,
        priority=Priority.LOW,
        times_per_period=2,
        period=FrequencyPeriod.WEEKLY,
    )

@pytest.fixture
def empty_pet():
    """A pet with no tasks."""
    return Pet(name="Amie", age=3, breed="Stray Mix")

@pytest.fixture
def scheduler_with_pet(empty_pet):
    return Scheduler(total_available_minutes=60, pets=[empty_pet])


# ===========================================================================
# mark_complete() tests
# ===========================================================================

class TestMarkComplete:

    def test_completed_is_false_by_default(self, basic_task):
        """Tasks should start incomplete — completed must never default to True."""
        assert basic_task.completed is False

    def test_mark_complete_sets_completed_true(self, basic_task):
        """Core behavior: calling mark_complete() flips completed to True."""
        basic_task.mark_complete()
        assert basic_task.completed is True

    def test_mark_complete_twice_is_idempotent(self, basic_task):
        """
        Calling mark_complete() on an already-completed task should not raise
        or reset the flag. Tammy might tap 'done' twice by accident.
        """
        basic_task.mark_complete()
        basic_task.mark_complete()
        assert basic_task.completed is True

    def test_mark_complete_only_affects_that_task(self, basic_task, another_task):
        """
        Completing one task must not touch others on the same pet.
        Realistic case: Tammy finishes the walk but feeding is still pending.
        """
        pet = Pet(name="Amie", age=3, breed="Stray Mix")
        pet.add_task(basic_task)
        pet.add_task(another_task)

        basic_task.mark_complete()

        assert basic_task.completed is True
        assert another_task.completed is False

    def test_task_created_already_completed(self):
        """
        Edge case: a task initialized with completed=True.
        mark_complete() should leave it True, not toggle it.
        """
        task = Task(
            title="Pre-done Task",
            duration_minutes=5,
            type=TaskType.MEDS,
            priority=Priority.HIGH,
            times_per_period=1,
            period=FrequencyPeriod.DAILY,
            completed=True,
        )
        task.mark_complete()
        assert task.completed is True

    def test_completed_task_excluded_from_plan(self, basic_task, another_task, empty_pet):
        """
        Integration: generate_plan() must skip completed tasks from scheduling
        even when there's plenty of time left. Completed tasks still appear in
        today's list (as done_today) but with no start_time_minutes.
        """
        empty_pet.add_task(basic_task)     # 30 min, HIGH
        empty_pet.add_task(another_task)   # 10 min, HIGH
        basic_task.mark_complete()

        scheduler = Scheduler(total_available_minutes=120, pets=[empty_pet])
        plan, _ = scheduler.generate_plan()
        today_tasks = plan[date.today()]

        # Completed task still appears in today_tasks but was NOT scheduled (no time slot)
        assert basic_task in today_tasks
        assert basic_task.start_time_minutes is None
        # Pending task was scheduled and has a real start time
        assert another_task in today_tasks
        assert another_task.start_time_minutes is not None

    def test_completing_all_tasks_produces_empty_pending(self, basic_task, another_task, empty_pet):
        """
        Edge case: if every task is already done, the pending section for today
        should be empty (done tasks still appear at the end of today's list).
        """
        empty_pet.add_task(basic_task)
        empty_pet.add_task(another_task)
        basic_task.mark_complete()
        another_task.mark_complete()

        scheduler = Scheduler(total_available_minutes=120, pets=[empty_pet])
        plan, _ = scheduler.generate_plan()
        today_tasks = plan[date.today()]

        # All tasks appear under today (as done), but none are pending
        pending = [t for t in today_tasks if not t.completed]
        assert pending == []

    def test_completed_task_still_in_pet_task_list(self, basic_task, empty_pet):
        """
        Completing a task should not remove it from pet.tasks.
        The record stays — only the scheduler ignores it when planning.
        """
        empty_pet.add_task(basic_task)
        basic_task.mark_complete()

        assert basic_task in empty_pet.tasks


# ===========================================================================
# add_task() / task_count tests
# ===========================================================================

class TestTaskCount:

    def test_task_count_starts_at_zero(self, empty_pet):
        """A freshly created pet with no tasks should have task_count of 0."""
        assert empty_pet.task_count == 0

    def test_add_one_task_increments_count(self, empty_pet, basic_task):
        """Core behavior: adding one task bumps task_count to 1."""
        empty_pet.add_task(basic_task)
        assert empty_pet.task_count == 1

    def test_add_multiple_tasks_increments_each_time(self, empty_pet, basic_task, another_task, low_priority_task):
        """task_count should reflect every addition, not just the first."""
        empty_pet.add_task(basic_task)
        assert empty_pet.task_count == 1
        empty_pet.add_task(another_task)
        assert empty_pet.task_count == 2
        empty_pet.add_task(low_priority_task)
        assert empty_pet.task_count == 3

    def test_task_count_matches_len_of_tasks_list(self, empty_pet, basic_task, another_task):
        """
        task_count must always equal len(pet.tasks).
        If these drift apart, something is updating one but not the other.
        """
        empty_pet.add_task(basic_task)
        empty_pet.add_task(another_task)
        assert empty_pet.task_count == len(empty_pet.tasks)

    def test_remove_task_decrements_count(self, empty_pet, basic_task, another_task):
        """Removing a task should lower task_count, not leave it stale."""
        empty_pet.add_task(basic_task)
        empty_pet.add_task(another_task)
        empty_pet.remove_task(basic_task)
        assert empty_pet.task_count == 1
        assert empty_pet.task_count == len(empty_pet.tasks)

    def test_adding_to_one_pet_does_not_affect_another(self, basic_task):
        """
        Realistic case: Tammy has two pets. Adding a task to Amie must not
        change Biscuit's task_count. Counts are per-pet, not global.
        """
        amie = Pet(name="Amie", age=3, breed="Stray Mix")
        biscuit = Pet(name="Biscuit", age=7, breed="Golden Retriever")

        amie.add_task(basic_task)

        assert amie.task_count == 1
        assert biscuit.task_count == 0

    def test_add_same_task_object_twice(self, empty_pet, basic_task):
        """
        Ambiguous case: adding the exact same Task instance to a pet twice.
        Python lists allow duplicates, so task_count will reach 2 and the task
        will appear twice in pet.tasks. This is a known side effect of not
        guarding against duplicates in add_task(). Test documents current behavior.
        """
        empty_pet.add_task(basic_task)
        empty_pet.add_task(basic_task)

        assert empty_pet.task_count == 2
        assert len(empty_pet.tasks) == 2

    def test_pet_initialized_with_tasks_bypasses_count(self):
        """
        Tricky edge case: if you build a Pet with tasks=[...] directly in the
        constructor instead of using add_task(), task_count starts at 0 even
        though tasks already has items. Always use add_task() to stay consistent.
        """
        task = Task(
            title="Walk",
            duration_minutes=30,
            type=TaskType.WALK,
            priority=Priority.HIGH,
            times_per_period=1,
            period=FrequencyPeriod.DAILY,
        )
        pet = Pet(name="Amie", age=3, breed="Stray Mix", tasks=[task])

        # Documents the inconsistency — task_count is 0 but one task exists
        assert len(pet.tasks) == 1
        assert pet.task_count == 0  # task_count was never incremented via add_task()


# ===========================================================================
# Knapsack algorithm tests
# ===========================================================================

class TestKnapsack:

    def _make_task(self, title, duration, priority):
        return Task(
            title=title,
            duration_minutes=duration,
            type=TaskType.WALK,
            priority=priority,
            times_per_period=1,
            period=FrequencyPeriod.DAILY,
        )

    def test_knapsack_picks_optimal_over_greedy(self):
        """
        Classic knapsack win: two MEDIUM tasks (50+50=100 min, score=4) beat
        one HIGH task (90 min, score=3) when the budget is 100 min.
        A greedy-by-priority approach would pick the HIGH task first and leave
        no room for the two MEDIUMs. Knapsack finds the better combination.
        """
        high_task   = self._make_task("High",    90, Priority.HIGH)    # score=3
        medium_a    = self._make_task("MedA",    50, Priority.MEDIUM)  # score=2
        medium_b    = self._make_task("MedB",    50, Priority.MEDIUM)  # score=2

        scheduler = Scheduler(total_available_minutes=100, pets=[])
        selected = scheduler.knapsack_select([high_task, medium_a, medium_b])

        assert medium_a in selected
        assert medium_b in selected
        assert high_task not in selected

    def test_knapsack_fits_single_task_exactly(self):
        """A task whose duration equals the budget exactly should always be picked."""
        task = self._make_task("ExactFit", 60, Priority.HIGH)
        scheduler = Scheduler(total_available_minutes=60, pets=[])
        selected = scheduler.knapsack_select([task])
        assert task in selected

    def test_knapsack_excludes_task_that_doesnt_fit(self):
        """A task longer than the budget must never appear in the result."""
        task = self._make_task("TooLong", 90, Priority.HIGH)
        scheduler = Scheduler(total_available_minutes=60, pets=[])
        selected = scheduler.knapsack_select([task])
        assert task not in selected

    def test_knapsack_empty_input_returns_empty(self):
        """No tasks in → empty list out, no crash."""
        scheduler = Scheduler(total_available_minutes=60, pets=[])
        assert scheduler.knapsack_select([]) == []

    def test_knapsack_respects_total_time_budget(self):
        """The combined duration of selected tasks must never exceed the budget."""
        tasks = [
            self._make_task("A", 20, Priority.HIGH),
            self._make_task("B", 20, Priority.MEDIUM),
            self._make_task("C", 20, Priority.LOW),
            self._make_task("D", 30, Priority.HIGH),
        ]
        scheduler = Scheduler(total_available_minutes=50, pets=[])
        selected = scheduler.knapsack_select(tasks)
        total = sum(t.duration_minutes for t in selected)
        assert total <= 50


# ===========================================================================
# Conflict detection tests
# ===========================================================================

class TestConflictDetection:

    def _make_task(self, title, duration, priority=Priority.HIGH):
        return Task(
            title=title,
            duration_minutes=duration,
            type=TaskType.WALK,
            priority=priority,
            times_per_period=1,
            period=FrequencyPeriod.DAILY,
        )

    def test_same_pet_tasks_get_sequential_non_overlapping_slots(self):
        """
        Two tasks for the same pet are placed back-to-back — the second starts
        exactly when the first ends. They must never overlap.
        """
        pet = Pet(name="Amie", age=3, breed="Stray Mix")
        task_a = self._make_task("Walk",  60)
        task_b = self._make_task("Feed",  30)
        pet.add_task(task_a)
        pet.add_task(task_b)

        scheduler = Scheduler(total_available_minutes=120, pets=[pet])
        plan, conflicts = scheduler.generate_plan(day_start_minutes=480)
        today_tasks = plan[date.today()]

        # Both tasks fit within 120 min and should be scheduled
        assert task_a in today_tasks
        assert task_b in today_tasks
        # Sequential placement means no conflicts fire
        assert conflicts == []
        # Slots must not overlap regardless of which task was placed first
        a_start = task_a.start_time_minutes
        a_end   = a_start + task_a.duration_minutes
        b_start = task_b.start_time_minutes
        b_end   = b_start + task_b.duration_minutes
        overlapping = a_start < b_end and b_start < a_end
        assert not overlapping

    def test_no_conflict_for_different_pets(self):
        """
        Two tasks for different pets that share the same time window should NOT
        produce a conflict — the constraint is per-pet, not global.
        """
        amie    = Pet(name="Amie",    age=3, breed="Stray Mix")
        biscuit = Pet(name="Biscuit", age=7, breed="Golden Retriever")
        task_a  = self._make_task("Walk",    30)
        task_b  = self._make_task("Feeding", 30)
        amie.add_task(task_a)
        biscuit.add_task(task_b)

        scheduler = Scheduler(total_available_minutes=60, pets=[amie, biscuit])
        _, conflicts = scheduler.generate_plan(day_start_minutes=480)

        assert conflicts == []

    def test_task_exceeding_combined_budget_excluded_by_knapsack(self):
        """
        When two tasks can't both fit within the time budget, knapsack picks
        the one with the better score (or the shorter one on a tie) and leaves
        the other out of today's plan entirely.
        """
        pet    = Pet(name="Amie", age=3, breed="Stray Mix")
        task_a = self._make_task("LongTask",  55)   # 55 min
        task_b = self._make_task("ShortTask", 30)   # 30 min — 55+30=85 > 60 min budget
        pet.add_task(task_a)
        pet.add_task(task_b)

        scheduler = Scheduler(total_available_minutes=60, pets=[pet])
        plan, _ = scheduler.generate_plan(day_start_minutes=480)
        today_tasks = plan[date.today()]

        # Exactly one task should be scheduled — they can't both fit
        scheduled = [t for t in today_tasks if t.start_time_minutes is not None]
        assert len(scheduled) == 1


# ===========================================================================
# Recurrence / next_due_date tests
# ===========================================================================

class TestRecurrence:

    def test_never_completed_is_due_today(self):
        """A task that has never been completed is always due today."""
        task = Task(
            title="Walk",
            duration_minutes=30,
            type=TaskType.WALK,
            priority=Priority.HIGH,
            times_per_period=1,
            period=FrequencyPeriod.DAILY,
        )
        assert task.next_due_date() == date.today()
        assert task.is_due_today() is True

    def test_next_due_date_after_daily_completion(self):
        """A 1x/day task completed today should be due tomorrow."""
        task = Task(
            title="Feed",
            duration_minutes=10,
            type=TaskType.FEEDING,
            priority=Priority.HIGH,
            times_per_period=1,
            period=FrequencyPeriod.DAILY,
        )
        task.mark_complete()
        assert task.next_due_date() == date.today() + timedelta(days=1)
        assert task.is_due_today() is False

    def test_next_due_date_twice_weekly(self):
        """2x/week → interval = 7/2 = 3.5 days → next due = today + 3.5 days."""
        task = Task(
            title="Brushing",
            duration_minutes=20,
            type=TaskType.GROOMING,
            priority=Priority.MEDIUM,
            times_per_period=2,
            period=FrequencyPeriod.WEEKLY,
        )
        task.mark_complete()
        expected = date.today() + timedelta(days=3.5)
        assert task.next_due_date() == expected

    def test_overdue_task_is_due_today(self):
        """A task whose next_due_date is in the past is still considered due today."""
        task = Task(
            title="Meds",
            duration_minutes=5,
            type=TaskType.MEDS,
            priority=Priority.HIGH,
            times_per_period=1,
            period=FrequencyPeriod.DAILY,
        )
        # Simulate last completed 5 days ago — interval=1 day → overdue by 4 days
        task.last_completed_date = date.today() - timedelta(days=5)
        assert task.is_due_today() is True

    def test_unmark_complete_resets_to_never_done(self):
        """unmark_complete() should clear both completed and last_completed_date."""
        task = Task(
            title="Walk",
            duration_minutes=30,
            type=TaskType.WALK,
            priority=Priority.HIGH,
            times_per_period=1,
            period=FrequencyPeriod.DAILY,
        )
        task.mark_complete()
        task.unmark_complete()

        assert task.completed is False
        assert task.last_completed_date is None
        assert task.next_due_date() == date.today()


# ===========================================================================
# sort_by_time / filter_tasks tests
# ===========================================================================

class TestSortAndFilter:

    def _pet_with_tasks(self):
        pet = Pet(name="Amie", age=3, breed="Stray Mix")
        walk = Task(
            title="Walk",
            duration_minutes=30,
            type=TaskType.WALK,
            priority=Priority.HIGH,
            times_per_period=1,
            period=FrequencyPeriod.DAILY,
        )
        feed = Task(
            title="Feed",
            duration_minutes=10,
            type=TaskType.FEEDING,
            priority=Priority.HIGH,
            times_per_period=2,
            period=FrequencyPeriod.DAILY,
        )
        pet.add_task(walk)
        pet.add_task(feed)
        return pet, walk, feed

    def test_sort_by_time_ascending(self):
        """sort_by_time() should return tasks in earliest-first order."""
        pet, _, _ = self._pet_with_tasks()
        scheduler = Scheduler(total_available_minutes=60, pets=[pet])
        plan, _ = scheduler.generate_plan()
        today = plan[date.today()]
        sorted_tasks = scheduler.sort_by_time(today)
        times = [t.start_time_minutes for t in sorted_tasks if t.start_time_minutes is not None]
        assert times == sorted(times)

    def test_sort_by_time_descending(self):
        """sort_by_time(reverse=True) should return tasks in latest-first order."""
        pet, _, _ = self._pet_with_tasks()
        scheduler = Scheduler(total_available_minutes=60, pets=[pet])
        plan, _ = scheduler.generate_plan()
        today = plan[date.today()]
        sorted_tasks = scheduler.sort_by_time(today, reverse=True)
        times = [t.start_time_minutes for t in sorted_tasks if t.start_time_minutes is not None]
        assert times == sorted(times, reverse=True)

    def test_filter_by_completed_false(self):
        """filter_tasks(completed=False) should return only incomplete tasks."""
        pet, walk, _ = self._pet_with_tasks()
        walk.mark_complete()
        scheduler = Scheduler(total_available_minutes=120, pets=[pet])
        plan, _ = scheduler.generate_plan()
        today = plan[date.today()]
        pending = scheduler.filter_tasks(today, completed=False)
        assert all(not t.completed for t in pending)
        assert walk not in pending

    def test_filter_by_pet_name(self):
        """filter_tasks(pet_name=...) should return only tasks belonging to that pet."""
        amie    = Pet(name="Amie",    age=3, breed="Stray Mix")
        biscuit = Pet(name="Biscuit", age=7, breed="Golden Retriever")
        task_a  = Task("Walk",  30, TaskType.WALK,    Priority.HIGH,   1, FrequencyPeriod.DAILY)
        task_b  = Task("Meds",   5, TaskType.MEDS,    Priority.HIGH,   1, FrequencyPeriod.DAILY)
        amie.add_task(task_a)
        biscuit.add_task(task_b)

        scheduler = Scheduler(total_available_minutes=60, pets=[amie, biscuit])
        plan, _ = scheduler.generate_plan()
        today = plan[date.today()]
        amie_tasks = scheduler.filter_tasks(today, pet_name="Amie")
        assert task_a in amie_tasks
        assert task_b not in amie_tasks

    def test_filter_combined_completed_and_pet(self):
        """AND logic: filter_tasks(completed=False, pet_name=...) respects both filters."""
        amie    = Pet(name="Amie",    age=3, breed="Stray Mix")
        biscuit = Pet(name="Biscuit", age=7, breed="Golden Retriever")
        walk    = Task("Walk",  30, TaskType.WALK,    Priority.HIGH,   1, FrequencyPeriod.DAILY)
        meds    = Task("Meds",   5, TaskType.MEDS,    Priority.HIGH,   1, FrequencyPeriod.DAILY)
        feed    = Task("Feed",  10, TaskType.FEEDING, Priority.HIGH,   2, FrequencyPeriod.DAILY)
        amie.add_task(walk)
        amie.add_task(feed)
        biscuit.add_task(meds)
        walk.mark_complete()

        scheduler = Scheduler(total_available_minutes=120, pets=[amie, biscuit])
        plan, _ = scheduler.generate_plan()
        today = plan[date.today()]
        result = scheduler.filter_tasks(today, completed=False, pet_name="Amie")

        assert feed in result
        assert walk not in result   # completed
        assert meds not in result   # wrong pet
