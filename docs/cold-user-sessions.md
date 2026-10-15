# Cold-user sessions

How to watch five people who have never seen Pipewright do four ordinary
jobs, and what to write down. The launch gate (A9) asks for these sessions
with people outside the team. **They have not been run yet**: they need
people the team does not work with, which only the product's owner can
arrange. This page is ready for whoever runs them.

The four jobs are the ones the redesign (A1–A3) set targets for. The browser
tests run the same jobs from a script on every change
(`apps/web/e2e/golden-path.spec.ts`), so they are known to be possible; these
sessions find out whether a person can do them without help.

## Who

Five people outside the team, none of whom has used Pipewright:

- two who work with spreadsheets but have never used a data tool;
- two analysts who have used another data or BI tool;
- one person who looks after servers or business applications.

Each session takes about 45 minutes, one person at a time, with one person
running it and, if possible, one taking notes.

## Before each session

1. A fresh deployment, or a fresh account on a shared one, with no projects.
   Make the example once from Home (**Explore a finished example**) for task 1.
2. A browser profile with no history, at a laptop's size (1280×800 or wider).
3. The two files in `docs/cold-user-files/` on the desktop: `orders.csv` and
   `signups.csv`.
4. For task 2, a PostgreSQL database the person may connect to, with its
   host, port, database name, user and password written on a card.
5. Ask whether the screen and voice may be recorded; record nothing without a
   yes.

## What to say

"We are testing the product, not you. Please think aloud: say what you are
looking for and what you expect to happen. I will not help unless you are
stuck for a while, because I want to see where it is unclear. There are no
wrong answers."

Give each task on its own card. Start the clock when they have read it. Do
not point, hint or name buttons. If they are stuck for two minutes, ask
"What would you try next?"; if still stuck after four, mark the task as not
done, show the way, and go on.

## The tasks

| # | The card says | Done when | Target |
| --- | --- | --- | --- |
| 1 | "There is a project called Acme Retail. Find its dashboards and open one." | The dashboard "Acme Retail overview" is open | 3 clicks or fewer, no wrong turns |
| 2 | "Connect the database on this card, and find it among the project's sources." | The connection shows under **Data → Sources** | 3 clicks to the right page, then filling in the card; no error left unexplained |
| 3 | "Starting from nothing, put the orders in `orders.csv` on a dashboard as a chart." | A dashboard shows a chart of the orders | Under 5 minutes, 15 clicks or fewer, no error banner |
| 4 | "In `signups.csv`, remove the empty rows, make the emails consistent, sort by sign-up date, and save that as a recipe." | A saved recipe with those three steps | Under 2 minutes, 12 clicks or fewer |

## What to write down, for each task

- the time from reading the card to done;
- the number of clicks;
- wrong turns: each page opened that was not on the way;
- whether they opened the help, and which page;
- any error they saw, word for word;
- done, done with a hint, or not done;
- what they said, especially "I expected…" and "where is…".

At the end ask, for each task: "How easy was that, from 1 (very hard) to 5
(very easy)?", and "What was the most confusing moment?"

## What passes

A task passes when at least four of the five people finish it within its
target without a hint. A task that does not pass is a defect to fix before
launch: write it in the plan's A9 section with what people did, fix it, and
run that task again with two new people.

## Results

Copy this table into `docs/plans/adoption-readiness-workflow.md` (A9) and
the session log in `docs/HANDOFF.md`, one row per person and task.

| Person | Task | Time | Clicks | Wrong turns | Help | Errors | Result | Ease (1–5) | What they said |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P1 | 1 | | | | | | | | |
