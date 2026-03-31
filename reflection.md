# PawPal+ Project Reflection

## 1. System Design

- The user should be able to add a pet and the relevant information about the pet.
- The user should be able to add and edit the task that they created with duration and priority.
- The user should be able to see all of their plans displayed.

**a. Initial design**

- Briefly describe your initial UML design.

    My initial UML had four classes: Owner, Pet, Task, and Scheduler. The idea was pretty straightforward — an owner has a pet, the scheduler holds a list of tasks, and tasks have a title, duration, type, and priority. I also included two enums, TaskType and Priority, to keep those values consistent across the system.

- What classes did you include, and what responsibilities did you assign to each?

    - **Owner** — holds the owner's name and a reference to their Pet. Responsible for adding and editing that info.
    - **Pet** — holds the pet's name, age, and breed. Basically a data container with getters and setters.
    - **Task** — represents a single care task. It knows its title, how long it takes (in minutes), what type it is (walk, feeding, meds, etc.), and how urgent it is (low, medium, high priority).
    - **Scheduler** — the brain of the system. It holds all the tasks and knows how much time is available in the day. It's responsible for adding/removing tasks, sorting them, and generating the daily plan.

**b. Design changes**

- Did your design change during implementation? 
- If yes, describe at least one change and why you made it.

    Yes, a few things were changed.
    
    - The biggest one was removing `Owner.age` — it is so normal and basic to me, but once I thought about it, the owner's age doesn't actually affect any scheduling logic. It was just extra data that didn't connect to anything. 
    - I removed the reference from Pet to Owner (originally `Pet` had an `owner` attribute). Having both classes point to each other created a circular logic that was unnecessary since the Owner already has the Pet, so the Pet doesn't need to know about the Owner too.
    - I also added in, and changed the name for, the duration attribute of the `Task` class to `total_available_minutes` to specify the unit to the Scheduler, which wasn't in the original plan. Without adding it as an argument, the scheduler would not have a constraint to fit the tasks in — it would just return everything, which defeats the whole purpose of a useful plan.

---

## 2. Scheduling Logic and Tradeoffs

**a. Constraints and priorities**

- What constraints does your scheduler consider (for example: time, priority, preferences)?
- How did you decide which constraints mattered most?

    The scheduler considers two main constraints: **time** and **priority**. Time is the hard ceiling — if there are 90 minutes available, the plan can't exceed 90 minutes, full stop. Priority is how the scheduler decides what to put in when not everything fits. Each task is ranked LOW, MEDIUM, or HIGH, and the scheduler uses those values as scores when picking the best combination.

    I also built in a secondary sorting factor called `daily_rate`, which is just how often a task repeats per day. So a task that happens twice a day naturally ranks higher than one that happens once a week, even if they share the same priority level. This felt right because frequency is a good signal for urgency — if it needs to happen twice today, it probably shouldn't get bumped.

    Time won out as the most important constraint because without it, the scheduler isn't actually making any decisions — it'd just return everything. Priority came second because it's the whole point of having a "smart" plan rather than just a checklist.

**b. Tradeoffs**

- Describe one tradeoff your scheduler makes.
- Why is that tradeoff reasonable for this scenario?

    The biggest tradeoff is that the scheduler uses **priority score as the only measure of value** in the knapsack algorithm. It doesn't weigh things like "Biscuit really needs her meds before anything else" beyond what's reflected in the priority field. If two tasks are both marked HIGH, the algorithm treats them as equally important — it doesn't know that one is a medication and one is a walk.

    That said, this tradeoff is totally reasonable for this scenario. The owner controls the priority levels, so if they set meds to HIGH and walk to MEDIUM, the scheduler will respect that. The responsibility for expressing "what matters most" sits with the owner, not the algorithm — and that's actually the right call for a personal pet care app where every household is different.

---

## 3. AI Collaboration

**a. How you used AI**

- How did you use AI tools during this project (for example: design brainstorming, debugging, refactoring)?
- What kinds of prompts or questions were most helpful?

    I used Claude Code pretty much throughout the whole project — design, implementation, debugging, and writing. In the early stages, I shared my initial UML and asked for feedback on the structure. That conversation is actually what led to some of the biggest design changes, like moving tasks from the Scheduler to the Pet and switching from a single pet to a list.

    Once the design was settled, I used AI to help flesh out the actual Python code, especially the scheduling algorithms. The knapsack implementation, the recurrence math, and the conflict detection all came out of prompts like "implement this logic" or "explain why this approach is better than a greedy sort." I also leaned on it heavily for the Streamlit UI — things like the `st.session_state` pattern, the `st.empty()` placeholder trick for fixing the task count display, and adding `st.rerun()` in the right places.

    The most useful prompts were the specific, narrow ones. "Why is the task count off by one?" got a much better answer than "fix my UI." Asking it to explain things before implementing them (like when I asked for reasoning before any code on the multi-pet edit buttons) also helped me understand what was going into the project rather than just copy-pasting.

**b. Judgment and verification**

- Describe one moment where you did not accept an AI suggestion as-is.
- How did you evaluate or verify what the AI suggested?

    The conflict detection tests are a good example. The AI wrote a test called `test_conflict_bumps_same_pet_task` that assumed two same-pet tasks placed in the schedule would trigger a conflict warning. When the tests ran, it failed — the conflict message list was empty.

    Rather than just deleting the test, I asked what was going on, and it turned out the conflict detection code can actually never fire with the current sequential time-slot algorithm. Because `current_time` always moves forward and each task starts exactly where the last one ended, two tasks from the same pet can never overlap — the algorithm prevents the problem before the conflict-checking code even gets a chance to run.

    The AI rewrote the test to match actual behavior (verifying that slots don't overlap rather than that a warning appears), but the more important thing was catching that the conflict detection code is essentially dead code right now. That's a real design insight — and it only came out because the test failed and we actually dug into why.

---

## 4. Testing and Verification

**a. What you tested**

- What behaviors did you test?
- Why were these tests important?

    There are 34 tests total, split across four main areas:

    - **`mark_complete()` and task state** — these were the first tests written, covering the basics: does a new task start incomplete, does `mark_complete()` flip the flag, does completing one task leave others alone? These matter because completion state drives almost everything — what shows up in the schedule, what appears in Upcoming, and what the task count reflects.

    - **`task_count` and `add_task()` / `remove_task()`** — verifying that `task_count` stays in sync with the actual task list. There's even a documented edge case where building a Pet with `tasks=[...]` in the constructor bypasses the count entirely, which is a known inconsistency that the test captures on purpose.

    - **Knapsack optimality** — the most important algorithm test. The key case is: two MEDIUM tasks (50 + 50 min, combined score 4) should beat one HIGH task (90 min, score 3) when the budget is 100 minutes. A greedy approach would grab the HIGH task first and leave no room for the two MEDIUMs. This test confirms the knapsack finds the actually better combination.

    - **Recurrence math** — checking that `next_due_date()` calculates correctly for daily, weekly, and monthly tasks, that overdue tasks still show as due today, and that `unmark_complete()` properly resets a task back to "never done" so the recurrence chain restarts cleanly.

    - **Sort and filter** — making sure `sort_by_time()` returns tasks in the right order (both directions), and that `filter_tasks()` correctly narrows results by completion status, by pet name, and by both at once.

**b. Confidence**

- How confident are you that your scheduler works correctly?
- What edge cases would you test next if you had more time?

    Pretty confident in the core logic — 4 out of 5 stars. The knapsack, recurrence math, and sort/filter are all covered and passing. The one honest gap is the conflict detection code, which can't be triggered under the current sequential time-slot assignment. It's not broken, it's just unreachable — and that means it goes untested.

    If I had more time, the next edge cases I'd want to cover are: what happens when a pet has zero tasks and the scheduler runs anyway, what happens when `total_available_minutes` is set to something tiny like 1 minute, and whether the multi-day plan correctly handles tasks that are due on the exact boundary of the lookahead window (e.g., due exactly 30 days from today).

---

## 5. Reflection

**a. What went well**

- What part of this project are you most satisfied with?

    I'm most satisfied with how the Streamlit UI came together. It's responsive, the layout feels clean, and the pieces I was most worried about — like the inline edit rows for pets and tasks, the task count updating in real time, and the Done/Undo buttons regenerating the Upcoming section automatically — all ended up working smoothly. I didn't run into many visual bugs, and the ones I did hit (like the task count being off by one, or having to click Edit twice) were specific enough that they were easy to diagnose and fix.

    The scheduling logic also ended up in a better place than I expected. The knapsack algorithm especially — it went from being something I'd heard of but never really implemented to something I can actually explain and trace through a DP table. Seeing it pass the "two MEDIUMs beat one HIGH" test case was genuinely satisfying, because that's the exact scenario where a simpler approach would fail.

**b. What you would improve**

- If you had another iteration, what would you improve or redesign?

    I'd want to stress-test it against more realistic use patterns before calling it done. Right now it works well for a clean, controlled setup — you add your pets, add your tasks, hit generate — but real users would probably do things like add a task mid-session, change a pet's name after already generating a plan, or open the app at 11 PM with 10 minutes left in the day. I'd want to map out those kinds of scenarios and see where things break or feel awkward.

    On the feature side, I'd look at adding task notes or reminders (like "give Biscuit the joint supplement hidden in peanut butter"), the ability to set a specific time for a task rather than letting the scheduler assign it, and maybe a simple streak tracker so the owner can see how consistent they've been with something like daily walks. Those feel like natural next steps for making the app actually useful day-to-day, not just as a project demo.

**c. Key takeaway**

- What is one important thing you learned about designing systems or working with AI on this project?

    You have to be very intentional about your input — and that applies both to the system design and to working with AI. On the design side, the clearest example is the decision to move task ownership from the Scheduler to the Pet. That one change made everything else cleaner: the Scheduler no longer needs to know which tasks belong to which pet, and the Pet becomes the actual source of truth for its own care. It sounds small, but it cascaded through almost every method in the codebase.

    On the AI side, the same principle applies. Vague prompts got vague results. "Fix my UI" didn't go anywhere useful. But "the task count is off by one — here's what I see happening" got a precise fix with an explanation of why. The more context I gave — which file to read, what behavior I expected, what I was actually observing — the more useful the output was. Treating it like a conversation with a collaborator who needs to be oriented, not a search engine that just figures it out, made a real difference.

