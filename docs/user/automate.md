# Automate

Make work run by itself: on a timetable, in order, and delivered where it is needed.

## Workflows

A workflow runs tasks in order: import a table, run a recipe, check the result, deliver it, send a message. If a check fails, the tasks after it stop, so bad data goes nowhere.

Build one on the canvas by adding tasks and joining them. Run it by hand, put it on a timetable, or run it for past dates (a backfill) when you need to reprocess history. A failed workflow tells the project's alert channels if they ask to hear about it.

**When a task fails.** A task can try again by itself: open it and set **If it fails** to a number of tries; each wait is twice the last. When a run fails anyway, fix what went wrong and choose **Pick up from where it failed**. Tasks that succeeded are not run again, unless you changed them; a task you changed, and every task after it, runs again. If the background worker stops part way through a run, the run is marked failed with that reason and you can pick it up the same way.

**How many at once.** A project has up to four runs going at the same time: recipe runs, imports, deliveries and workflow runs together (a project's admin can set its own number under **Settings**). Queued work waits its turn, and what a person started goes before scheduled work, which goes before a backfill, so one project's backfill cannot hold up the others. A run you start while the project already has its limit going is refused, saying so; start it again when one finishes. A due schedule in a busy project waits for a later pass rather than failing.

## Schedules

Run a recipe or a delivery by itself at the times you choose: every day at nine, every hour, or your own pattern. Pause a schedule without losing it. **Run now** tries it straight away without changing its timetable. A failed scheduled run is tried again a few times before it is reported.

## Runs

Everything that has run in the project, newest first. Open a run to see who started it, what it read, what it made and each step it went through. A recipe run can be **replayed**: run again with exactly the same inputs to check it still gives the same answer.

## Destinations

Where data goes: PostgreSQL or MySQL tables, an S3 bucket (or a compatible store), or a folder on the server.

Add a destination, then use **Test** to check it can be reached. Send a dataset from its **Send to** menu, choosing to:

- replace the table,
- add the rows, or
- update matching rows, by the columns that identify a row.

You see the table that will be written, with each column's kind, before anything is sent. Every delivery is a run you can look back at.

**Copy a database** copies tables from a connected database into a PostgreSQL or MySQL destination, with their keys and required columns. It first shows how each column will arrive and marks any that would lose something; afterwards it lists what it did not carry, such as foreign keys and indexes.

## BI tools

Connect Power BI or Tableau, then send a dataset to them from the dataset's **Send to** menu.
