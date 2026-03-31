import streamlit as st
from datetime import time, date, timedelta
from pawpal_system import Owner, Pet, Task, Scheduler, TaskType, Priority, FrequencyPeriod, minutes_to_time_str

st.set_page_config(page_title="PawPal+", page_icon="🐾", layout="wide")

st.title("🐾 PawPal+")

st.markdown(
    """
Welcome to the PawPal+ app!
"""
)

with st.expander("Scenario", expanded=True):
    st.markdown(
        """
**PawPal+** is a pet care planning assistant. It helps a pet owner plan care tasks
for their pet(s) based on constraints like time, priority, and preferences.

You will design and implement the scheduling logic and connect it to this Streamlit UI.
"""
    )

with st.expander("What you need to build", expanded=True):
    st.markdown(
        """
At minimum, your system should:
- Represent pet care tasks (what needs to happen, how long it takes, priority)
- Represent the pet and the owner (basic info and preferences)
- Build a plan/schedule for a day that chooses and orders tasks based on constraints
- Explain the plan (why each task was chosen and when it happens)
"""
    )

st.divider()

# ---------------------------------------------------------------------------
# Step 1 — Owner
# editing_owner flag in session_state toggles between display and edit mode.
# ---------------------------------------------------------------------------

# Initialize the edit flag the first time the app loads
if "editing_owner" not in st.session_state:
    st.session_state.editing_owner = False

st.subheader("Owner")

if st.session_state.editing_owner or "owner" not in st.session_state:
    # Edit/create mode — show the input form
    owner_name = st.text_input("Owner name", value=st.session_state.owner.name if "owner" in st.session_state else "Jordan")
    col_save, col_cancel = st.columns([1, 5])
    with col_save:
        if st.button("Save owner"):
            st.session_state.owner = Owner(name=owner_name)
            st.session_state.editing_owner = False   # exit edit mode after saving
            st.rerun()                               # force immediate rerun so display mode renders now
else:
    # Display mode — show current name with an Edit button beside it
    col_info, col_edit = st.columns([4, 1])
    with col_info:
        st.caption(f"Owner saved: **{st.session_state.owner.name}**")
    with col_edit:
        if st.button("Edit", key="edit_owner"):
            st.session_state.editing_owner = True    # enter edit mode on click
            st.rerun()                               # force immediate rerun so edit form renders now

st.divider()

# ---------------------------------------------------------------------------
# Step 2 — Pets
# editing_pet holds the index of the pet currently being edited, or None.
# Rendering each pet as its own row of columns allows a per-row Edit button.
# ---------------------------------------------------------------------------

if "editing_pet" not in st.session_state:
    st.session_state.editing_pet = None             # None means no pet is being edited

st.subheader("Pets")

if "owner" not in st.session_state:
    st.info("Save an owner first before adding pets.")
else:
    # Add pet form
    col1, col2, col3 = st.columns(3)
    with col1:
        pet_name = st.text_input("Pet name", value="Mochi")
    with col2:
        pet_age = st.number_input("Age (years)", min_value=0, max_value=30, value=2)
    with col3:
        pet_breed = st.text_input("Breed", value="Mixed")

    if st.button("Add pet"):
        new_pet = Pet(name=pet_name, age=int(pet_age), breed=pet_breed)
        st.session_state.owner.add_pet(new_pet)

    # Render each pet as its own row instead of st.table so action buttons fit inline
    if st.session_state.owner.pets:
        st.write("Your pets:")

        # Header row for alignment — matches the column widths of display rows below
        h1, h2, h3, h4, h5, h6 = st.columns([2, 1, 2, 1, 1, 1])
        h1.markdown("**Name**"); h2.markdown("**Age**")
        h3.markdown("**Breed**"); h4.markdown("**Tasks**")

        for i, pet in enumerate(st.session_state.owner.pets):
            if st.session_state.editing_pet == i:
                # Inline edit form for this specific pet row
                e1, e2, e3, e4 = st.columns([2, 1, 2, 2])
                new_pet_name  = e1.text_input("Name",  value=pet.name,  key=f"pet_name_{i}")
                new_pet_age   = e2.number_input("Age", value=pet.age,   key=f"pet_age_{i}", min_value=0, max_value=30)
                new_pet_breed = e3.text_input("Breed", value=pet.breed, key=f"pet_breed_{i}")
                with e4:
                    if st.button("Save", key=f"save_pet_{i}"):
                        # Write edits back to the actual Pet object in session_state
                        pet.set_name(new_pet_name)
                        pet.set_age(int(new_pet_age))
                        pet.set_breed(new_pet_breed)
                        st.session_state.editing_pet = None  # exit edit mode
                        st.rerun()                           # force immediate rerun so display row renders now
            else:
                # Display row for this pet with Edit and Delete buttons on the right
                r1, r2, r3, r4, r5, r6 = st.columns([2, 1, 2, 1, 1, 1])
                r1.write(pet.name); r2.write(pet.age)
                r3.write(pet.breed); r4.write(pet.task_count)
                with r5:
                    if st.button("Edit", key=f"edit_pet_{i}"):
                        st.session_state.editing_pet = i     # mark this row as being edited
                        st.rerun()                           # force immediate rerun so edit form renders now
                with r6:
                    if st.button("Delete", key=f"delete_pet_{i}"):
                        # Drop all display-list tasks that belong to this pet before removing it
                        st.session_state.tasks = [
                            t for t in st.session_state.tasks if t["pet_name"] != pet.name
                        ]
                        st.session_state.owner.remove_pet(pet)   # remove from owner.pets
                        st.session_state.editing_pet = None      # clear any active edit state
                        st.rerun()

st.divider()

# ---------------------------------------------------------------------------
# Step 3 — Tasks
# editing_task holds the index into st.session_state.tasks being edited, or None.
# Each task row is rendered manually so it can carry its own Edit button.
# ---------------------------------------------------------------------------

if "editing_task" not in st.session_state:
    st.session_state.editing_task = None            # None means no task is being edited

if "tasks" not in st.session_state:
    st.session_state.tasks = []

st.subheader("Tasks")

if "owner" not in st.session_state or not st.session_state.owner.pets:
    st.info("Add at least one pet before adding tasks.")
else:
    # Build a name → Pet object lookup so the dropdown selection is useful
    pet_map = {p.name: p for p in st.session_state.owner.pets}

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        target_pet_name = st.selectbox("For pet", list(pet_map.keys()))
    with col2:
        task_title = st.text_input("Task title", value="Morning walk")
    with col3:
        duration = st.number_input("Duration (min)", min_value=1, max_value=240, value=20)
    with col4:
        priority = st.selectbox("Priority", ["low", "medium", "high"], index=2)
    with col5:
        task_type = st.selectbox("Type", [t.value for t in TaskType])

    # Second row — frequency fields kept together since they only make sense as a pair
    col6, col7, col8 = st.columns([1, 1, 1])
    with col6:
        times_per_period = st.number_input("Times per period", min_value=1, max_value=30, value=1)
    with col7:
        period = st.selectbox("Period", [p.name.capitalize() for p in FrequencyPeriod])
    with col8:
        # Reserve layout spot — filled after button logic so count is accurate
        count_placeholder = st.empty()

    selected_pet = pet_map[target_pet_name]

    if st.button("Add task"):
        # Build the Task object first so we can capture its id before adding it
        new_task = Task(
            title=task_title,
            duration_minutes=int(duration),
            type=TaskType(task_type),
            priority=Priority[priority.upper()],
            times_per_period=int(times_per_period),
            period=FrequencyPeriod[period.upper()],
        )
        selected_pet.add_task(new_task)
        st.session_state.tasks.append({
            "pet_name": target_pet_name,    # used to find the Pet object during edits/deletes
            "_task_id": id(new_task),       # object id — lets us find the exact Task in pet.tasks
            "Task": task_title,
            "Duration (min)": int(duration),
            "Priority": priority,
            "Type": task_type,
            "Frequency": f"{int(times_per_period)}x / {period.lower()}",
        })

    # Fill count after button logic so it always reflects the post-add state
    count_placeholder.metric(label=f"{target_pet_name}'s task count", value=selected_pet.task_count)

    if st.session_state.tasks:
        st.write("All tasks:")

        # Header row — Status and Done columns removed; completion lives in the schedule now
        th1, th2, th3, th4, th5, th6, th7, th8 = st.columns([1, 2, 3, 2, 2, 2, 2, 1])
        th1.markdown("**#**");        th2.markdown("**Pet**")
        th3.markdown("**Task**");     th4.markdown("**Duration**")
        th5.markdown("**Priority**"); th6.markdown("**Frequency**")
        th7.markdown("**Due**")

        for i, task_dict in enumerate(st.session_state.tasks):
            # Look up the actual Task object using stored object id — avoids index mismatch
            # when tasks from multiple pets are mixed in the display list
            pet_obj     = pet_map[task_dict["pet_name"]]
            actual_task = next(t for t in pet_obj.tasks if id(t) == task_dict["_task_id"])

            if st.session_state.editing_task == i:
                # Inline edit form for this specific task row
                te1, te2, te3, te4, te5 = st.columns([3, 2, 2, 2, 2])
                new_title    = te1.text_input("Title",   value=task_dict["Task"],          key=f"t_title_{i}")
                new_duration = te2.number_input("Min",   value=task_dict["Duration (min)"], key=f"t_dur_{i}",  min_value=1, max_value=240)
                new_priority = te3.selectbox("Priority", ["low", "medium", "high"],         key=f"t_pri_{i}",  index=["low","medium","high"].index(task_dict["Priority"]))
                new_type     = te4.selectbox("Type",     [t.value for t in TaskType],       key=f"t_type_{i}", index=[t.value for t in TaskType].index(task_dict["Type"]))
                with te5:
                    if st.button("Save", key=f"save_task_{i}"):
                        # Update the display dict so the table reflects the new values
                        task_dict["Task"]           = new_title
                        task_dict["Duration (min)"] = int(new_duration)
                        task_dict["Priority"]       = new_priority
                        task_dict["Type"]           = new_type

                        # Update the actual Task object so the scheduler sees the changes
                        actual_task.set_title(new_title)
                        actual_task.set_duration(int(new_duration))
                        actual_task.set_priority(Priority[new_priority.upper()])

                        st.session_state.editing_task = None    # exit edit mode
                        st.rerun()                              # force immediate rerun so display row renders now
            else:
                # Compute due label — reads from the live Task object so it updates after mark_complete()
                due_label = "Today" if actual_task.is_due_today() else str(actual_task.next_due_date())

                # Display row — Done button removed; use the schedule section to mark tasks complete
                r1, r2, r3, r4, r5, r6, r7, r8 = st.columns([1, 2, 3, 2, 2, 2, 2, 1])
                r1.write(i + 1)
                r2.write(task_dict["pet_name"])
                r3.write(task_dict["Task"])
                r4.write(f"{task_dict['Duration (min)']} min")
                r5.write(task_dict["Priority"])
                r6.write(task_dict["Frequency"])
                r7.write(due_label)
                with r8:
                    if st.button("Delete", key=f"delete_task_{i}"):
                        pet_obj.remove_task(actual_task)     # remove Task from pet.tasks, decrements task_count
                        st.session_state.tasks.pop(i)        # remove from display list
                        st.session_state.editing_task = None # clear any active edit state
                        st.rerun()
    else:
        st.info("No tasks yet. Add one above.")

st.divider()

# ---------------------------------------------------------------------------
# Step 4 — Generate Schedule
# Passes owner.pets directly to Scheduler — all pets and their tasks are
# included automatically. No changes needed here as more pets are added.
# ---------------------------------------------------------------------------

st.subheader("Build Schedule")

col_time, col_mins = st.columns(2)
with col_time:
    # st.time_input returns a datetime.time object — we convert it to minutes-from-midnight
    # so the scheduler can do plain integer arithmetic (e.g. 9:30 AM → 570)
    start_time = st.time_input("Schedule start time", value=time(8, 0))
    day_start_minutes = start_time.hour * 60 + start_time.minute
with col_mins:
    available_minutes = st.number_input(
        "Time available today (minutes)", min_value=1, max_value=480, value=90
    )

if st.button("Generate schedule"):
    if "owner" not in st.session_state or not st.session_state.owner.pets:
        st.warning("Save your owner and add at least one pet with tasks first.")
    elif not any(p.tasks for p in st.session_state.owner.pets):
        st.warning("Add at least one task to a pet before generating a schedule.")
    else:
        scheduler = Scheduler(
            total_available_minutes=int(available_minutes),
            pets=st.session_state.owner.pets,
        )
        plan, conflicts = scheduler.generate_plan(day_start_minutes=day_start_minutes, lookahead_days=30)

        # Persist so sort/filter controls and Done/Undo handlers can access them on subsequent reruns
        st.session_state.plan               = plan
        st.session_state.scheduler          = scheduler
        st.session_state.conflicts          = conflicts
        # Store day_start_minutes so Done/Undo can regenerate the plan without re-clicking the button
        st.session_state.day_start_minutes  = day_start_minutes

# ---------------------------------------------------------------------------
# Plan display — rendered from session_state so sort/filter survive reruns.
# plan is now dict[date, list[Task]] — iterated as date-labelled sections.
# ---------------------------------------------------------------------------

if "plan" in st.session_state:
    for conflict_msg in st.session_state.conflicts:
        st.warning(f"⚠️ {conflict_msg}")

    plan_dict = st.session_state.plan
    scheduler = st.session_state.scheduler
    today     = date.today()

    all_plan_tasks = [t for tasks in plan_dict.values() for t in tasks]

    if not all_plan_tasks:
        st.info("No tasks fit in the available time, or all tasks are already complete.")
    else:
        # Filter and sort controls — apply across all sections
        ctrl1, ctrl2, ctrl3 = st.columns(3)
        with ctrl1:
            # Sort by time only makes sense for today (future tasks have no start_time_minutes)
            time_order = st.selectbox("Sort today by time", ["Earliest first", "Latest first"])
        with ctrl2:
            status_filter = st.selectbox("Filter by status", ["All", "Pending only", "Done only"])
        with ctrl3:
            pet_options = ["All pets"] + [p.name for p in st.session_state.owner.pets]
            pet_filter  = st.selectbox("Filter by pet", pet_options)

        # Reverse lookup: task object id → pet name, used for display and Done button
        task_to_pet = {id(task): pet.name for pet in st.session_state.owner.pets for task in pet.tasks}

        # --- Today section ---

        today_tasks = plan_dict.get(today, [])

        if status_filter == "Pending only":
            today_tasks = scheduler.filter_tasks(today_tasks, completed=False)
        elif status_filter == "Done only":
            today_tasks = scheduler.filter_tasks(today_tasks, completed=True)
        if pet_filter != "All pets":
            today_tasks = scheduler.filter_tasks(today_tasks, pet_name=pet_filter)

        today_tasks = scheduler.sort_by_time(today_tasks, reverse=(time_order == "Latest first"))

        st.markdown("### Today")

        if not today_tasks:
            st.info("No tasks match the current filters for today.")
        else:
            # Summary metrics — counts and time at a glance
            pending_count = sum(1 for t in today_tasks if not t.completed)
            done_count    = sum(1 for t in today_tasks if t.completed)
            time_used     = sum(t.duration_minutes for t in today_tasks if t.start_time_minutes is not None)
            m1, m2, m3 = st.columns(3)
            m1.metric("Pending today",   pending_count)
            m2.metric("Completed today", done_count)
            m3.metric("Time scheduled",  f"{time_used} min")

            if pending_count == 0:
                st.success("All tasks for today are done! Great job. 🎉")
            else:
                PRIORITY_BADGE = {"HIGH": "🔴 HIGH", "MEDIUM": "🟡 MEDIUM", "LOW": "🟢 LOW"}

                h1, h2, h3, h4, h5, h6 = st.columns([2, 3, 2, 2, 2, 1])
                h1.markdown("**Start**"); h2.markdown("**Task**")
                h3.markdown("**Pet**");   h4.markdown("**Duration**")
                h5.markdown("**Priority**")

                for t in today_tasks:
                    r1, r2, r3, r4, r5, r6 = st.columns([2, 3, 2, 2, 2, 1])
                    r1.write("✓ Done" if t.completed else minutes_to_time_str(t.start_time_minutes))
                    r2.write(t.title)
                    r3.write(task_to_pet.get(id(t), "—"))
                    r4.write(f"{t.duration_minutes} min")
                    r5.write(PRIORITY_BADGE.get(t.priority.name, t.priority.name))
                    with r6:
                        if t.completed:
                            if st.button("Undo", key=f"sched_undo_{id(t)}"):
                                t.unmark_complete()
                                # Regenerate so the task moves back into Today as pending
                                _plan, _conflicts = st.session_state.scheduler.generate_plan(
                                    day_start_minutes=st.session_state.day_start_minutes,
                                    lookahead_days=30,
                                )
                                st.session_state.plan      = _plan
                                st.session_state.conflicts = _conflicts
                                st.rerun()
                        else:
                            if st.button("Done", key=f"sched_done_{id(t)}"):
                                t.mark_complete()
                                # Regenerate so the task's next occurrence appears in Upcoming
                                _plan, _conflicts = st.session_state.scheduler.generate_plan(
                                    day_start_minutes=st.session_state.day_start_minutes,
                                    lookahead_days=30,
                                )
                                st.session_state.plan      = _plan
                                st.session_state.conflicts = _conflicts
                                st.rerun()

        st.divider()

        # --- Upcoming section ---

        # Collect all future dates from the plan (everything except today)
        future_dates = {d: tasks for d, tasks in plan_dict.items() if d > today}

        # Only show the Upcoming section if there are future tasks at all
        st.markdown("### Upcoming")

        # Toggle between This Week (7 days) and This Month (30 days)
        # Default to "This Month" so tasks like 2x/month (due in ~15 days) are visible immediately
        window = st.radio(
            "Show upcoming tasks for",
            ["This Week", "This Month"],
            index=1,
            horizontal=True,
        )
        cutoff = today + timedelta(days=7 if window == "This Week" else 30)

        # Upcoming tasks only appear after tasks are marked complete —
        # until then, all tasks are due today and show in the Today section above
        PRIORITY_BADGE = {"HIGH": "🔴 HIGH", "MEDIUM": "🟡 MEDIUM", "LOW": "🟢 LOW"}
        with st.expander("View upcoming tasks", expanded=True):
            upcoming_rows = []
            for plan_date, tasks in future_dates.items():
                if plan_date > cutoff:
                    continue    # outside the selected window
                if pet_filter != "All pets":
                    tasks = scheduler.filter_tasks(tasks, pet_name=pet_filter)
                for t in tasks:
                    upcoming_rows.append({
                        "Date":     plan_date.strftime("%A, %b %-d"),
                        "Task":     t.title,
                        "Pet":      task_to_pet.get(id(t), "—"),
                        "Duration": f"{t.duration_minutes} min",
                        "Priority": PRIORITY_BADGE.get(t.priority.name, t.priority.name),
                    })

            if upcoming_rows:
                st.dataframe(upcoming_rows, use_container_width=True, hide_index=True)
            else:
                st.info("No upcoming tasks yet — tasks appear here after being marked Done.")
