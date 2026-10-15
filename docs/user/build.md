# Build

Clean and reshape data, step by step, seeing the result as you go.

## Studio

Pick a dataset and add steps. Your original data is never changed: the Studio shows what the steps would make, and saving keeps the steps as a recipe.

- **Add a step** (or press `/`) searches the common steps and the tool library: filter rows, fix text, split a column, join another dataset and more.
- **Right-click a column** for the steps that suit it, such as "Standardise an email" on an email column.
- **Click a step** to change its settings right under it. Each step says in a few words what it does.
- **Undo** and **redo** take any change back. Clicking a column header only sorts what is on screen; it does not add a step.

![The Studio: a recipe's steps on the left, and the rows they make on the right](images/studio.png)
- Unsaved work on a new recipe is kept in your browser and offered back next time.
- **Details** shows the columns, where each step runs (at the source or here), the recipe as a file, and comments.
- **Details → Where it runs** also shows the rows each step is expected to leave, worked out from the data's statistics, beside the rows the preview counted, and how each figure was worked out. A run against a database is planned from estimates like these, so how close they come here says how far to trust the plan there. A figure with nothing to work from says it is a guess.
- Changing a step near the end is quick: what the earlier steps made is kept for a while, so only the changed step and those after it run again. On a million rows, changing step 14 of 15 takes under a second.

### Editing together

Everyone who opens a saved recipe in the Studio edits the same copy of it. What someone else changes appears in your Studio within a couple of seconds, without reloading, and nobody's work is written over: two people can change different steps, or different settings of one step, at once. If two people change the same setting at the same moment, the later change is kept.

- The people with the recipe open show at the top, and each person's initials sit on the step they have open.
- **Undo** takes back only your own changes, and leaves alone anything someone else has changed since.
- Unsaved changes stay in the shared copy, for everyone, until someone saves them or chooses **More → Discard unsaved changes**.
- If someone changes the recipe outside the Studio (restores an older version, or accepts a suggestion), your Studio says so and shows the saved recipe; anything you had not saved is offered back.
- A save that started from an older version than the saved one is refused, saying who saved since and when, rather than replacing their changes.

### Suggesting a change

Someone who may look at a recipe but not change it (a viewer or an operator), or anyone in a project whose changes need approval, sees **Suggest** where Save would be. Change the steps as you would, then **Suggest**: give it a title and a reason, and it goes to the people who may edit the recipe. They see "1 suggestion waiting" in the Studio and under [Approvals](trust.md#approvals), compare it step by step, and accept it (it becomes the recipe's next version) or decline it with a note. You hear which.

**Start from a template** offers recipes for common jobs, such as tidying a customer list, matched to your columns.

When it looks right, **Save**, then **Run** to make the result a dataset. Run it again any time, or put it on a [schedule](automate.md#schedules).

### How each run computes

A saved recipe chooses, under **Details → Where it runs → Each run**, how its runs work:

- **Every row, every time.** The usual choice.
- **Only rows added since the last run.** For an input that grows at the end, as an import's does. The run checks that the rows the last run read are still there, unchanged, first; only then does it compute just the new rows and add them to the last result.
- **Only partitions whose rows changed.** Choose a column that divides the data, such as a region or a day. Only the partitions whose rows changed are computed again; the rest keep the last run's result. The rows can come back in a different order than a full run gives.

The result is always what a full run would give. When a recipe or its input does not allow less (a step that sorts or groups all the rows, reads today's date, or joins a dataset that changed; an input whose earlier rows changed), the run computes everything, and its log says which step or change stopped it. A run's log also says when it reused what a recent preview made.

**Too much data for one run.** A run stops at the step that makes its data larger than this server allows, naming the step and the size, and a join that would multiply into more rows than that is stopped before it is built. Filter or group the data before that step.

## Recipes

Every saved recipe. Open one to change its steps in the Studio, or run it to make a fresh result. Each run adds a version to the same result dataset.

## SQL

Write SQL against a connected database and see the results. It only reads unless an administrator allows writing; a statement that would change data asks you to confirm first. Save the queries you use often. You can also ask a dataset version a question in SQL from its version history.

### Across sources

Choose **Across sources** in the connection list to write one SELECT over tables in several of the project's databases and its datasets at once. Name a table as `connection.schema.table` (a connection's name in double quotes, or in lower case with underscores, such as `shop_db`) or a dataset as `datasets."Customers"`:

```sql
SELECT c.region, SUM(o.amount) AS sales
FROM shop_db.public.orders AS o
JOIN datasets."Customers" AS c ON o.customer_id = c.id
WHERE o.amount > 50
GROUP BY c.region
```

Each database runs the largest part of the query it can, in its own SQL, with the filters and columns that concern it; a dataset is read as you may see it; joins between them run here. When one side of a join has few keys, they are sent to the other database so it sends only the rows that match. Under the results, **How it ran** shows what each source ran, how many rows it sent beside what was expected, and where its statistics came from. If a figure turned out ten times out, the plan changes as it runs and says so.

It handles joins on equal columns, WHERE, GROUP BY, HAVING, ORDER BY, LIMIT and the common functions; a subquery, WITH or UNION is refused with the reason. A source that would send more than a million rows stops the query rather than join part of a table: filter it, or run the query in one connection.

## Notebooks

Mix SQL, recipe and text cells that run top to bottom; each cell can use the results of the cells above it. Python cells run only on servers where they can be kept within safe limits, and the page says when they are off.

## Table editor

Change rows in a connected database table directly. You see every change, and how many rows it affects, before anything is saved, and a change that would touch rows someone else just changed is stopped. Only tables with a clear way to identify each row can be edited.
