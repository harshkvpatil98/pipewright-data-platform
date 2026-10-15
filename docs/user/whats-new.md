# What's new

The changes people notice, newest first. The full record is in the repository's changelog.

## Faster, and planned from what the data holds

- **Every version knows its values.** A dataset's **Columns** show how each column's values spread, or its commonest values, and every version keeps these figures from when it was written.
- **Expected rows beside counted rows.** **Details → Where it runs** in the Studio shows the rows each step is expected to leave and how that was worked out, beside the rows the preview counted.
- **Changing a late step is quick.** What the earlier steps made is kept for a while, so changing step 14 of 15 on a million rows takes under a second.
- **Recipes that compute only what changed.** Choose **Only rows added since the last run** or **Only partitions whose rows changed**; the result is what a full run gives, and a run that cannot do less says why.
- **One query across databases and datasets.** **SQL → Across sources** joins tables from several connections and datasets in one SELECT; each database runs its own part, and the page shows what each one sent.
- **Fair shares.** A project runs up to four runs at once, a person's first; one busy project no longer holds up the others, and a run whose data outgrows the server stops at the step that did it.

## Live feeds

- **Live feeds have their own tab.** **Data → Live feeds** reads data as it arrives, every few seconds, and saves it to datasets every so often.
- **Tables kept current.** Follow a PostgreSQL, MySQL, MongoDB or SQL Server database's changes, and each table is a dataset as it is now: a first full copy, then every insert, update and delete.
- **Eight queues.** Kafka, Azure Event Hubs, Amazon Kinesis, Google Pub/Sub, Apache Pulsar, RabbitMQ, NATS and MQTT, each reading from where it last stopped.
- **Saved once, and said so.** Every feed says whether each event is saved once, or at least once, where you choose it and on its page.
- **Live recipes.** Count, sum or average events by minute, by sessions, or over the last so many minutes, with late events left out or counted in; look each one up in a dataset; run a recipe's steps on each batch.
- **A feed that fails** tries again later and tells its maker after five failures in a row; **Start again with a fresh copy** recovers a database feed that fell too far behind.

## Working together

- **Edit a recipe together.** Everyone with a recipe open in the Studio edits the same copy; others' changes appear within a couple of seconds, and nobody's work is written over. Undo takes back only your own changes.
- **See who is here.** The people with a recipe open show at the top of the Studio, with their initials on the step each has open.
- **Suggest instead of saving.** Viewers, operators, and anyone in a project whose changes need approval, suggest a change; editors accept or decline it, step by step, with a note.
- **Saves never replace someone else's.** A save from an older version is refused, saying who saved since.
- **Threads on a cell.** Click a cell on a dataset's page to ask about that value; threads take replies and resolve as a whole.
- **What happened to a dataset.** Its History lists each version and what made it, failed runs, checks, contracts, alerts and comments.
- **Changes need approval** can now be switched on in a project's Settings.

## Promises about data

- **Contracts.** Write down what a dataset promises: its columns and what is in them, how many rows, how often it gets new data. New data that breaks a promise is stopped before it replaces what people use, with the reasons on the run. Find them under **Trust → Contracts**, or **More → Write a contract** on any dataset.
- **Follow a contract.** Anyone in the project can follow one, a viewer included, and is told once when it breaks, again when it is kept, and when its promises change.
- **Warned first.** The Studio says when a recipe's result no longer has a promised column, before it runs; restoring an older version says first whether it keeps the contract.
- **Failed runs keep their story.** A failed recipe run or import now keeps every line of its log, up to the step where it stopped. Before, it kept only "Waiting to start."

## For partners, scripts and other sites

- **Dashboards inside other sites.** **Embed** on a dashboard makes a link for a page on your site or a partner's, lasting from a day to a year. Your site's server can make short links of its own that show each customer only their rows. Turn an embed off and every link to it stops.
- **Alerts on numbers.** On a dataset's **Data health** page, choose a measure and a line: the row count above a number, a column's empty values above a share, or anything changing by more than a share. You hear when it crosses and when it comes back.
- **Activity.** **Overview → Activity** lists what happened in the project, newest first: changes, runs, incidents, comments and alerts, each with who and when.
- **Webhooks.** An alert channel can send each event to your own systems as signed JSON, tried three times, with every attempt listed.
- **Move a project's work.** **Settings → Move this project's work** downloads its recipes, checks, charts, dashboards, workflows and schedules as one file, to import into another project.
- **A command line.** `pipewright` uploads, downloads and runs recipes and workflows from a script; see [Using the API](api.md#the-python-client-and-command-line).
- **Bigger files.** Uploads up to 200MB, read in half the memory, and checks on large datasets in about a second.
- **Dates the British way.** Every date and number is written one way across the product: "15 Oct 2026", "1,200".

## Scale and reliability

- **Big files and big copies.** Files up to 100MB upload, and anything over 25MB is read in the background with the page showing how far it has got. Copying a database, and delivering a dataset of more than 50,000 rows, also run in the background, so a long job never times out.
- **Workflows that recover.** A task can try again by itself, waiting longer each time. A failed run can be picked up from where it failed, reusing what already succeeded.
- **Limits in the open.** System status lists the limits this server enforces: upload size, rows copied, runs at once, sign-in attempts and more.
- **Sign-in protection.** Repeated sign-in attempts, one-time codes, public dashboards and webhooks are limited, and the answer says when to try again.
- **Files in a bucket.** Stored files can live in S3 or an S3-compatible store, so several servers can share them.

## Trust, help and support

- **Help inside the product.** These pages, with a glossary, an admin guide, a security page and an API guide. **About this page** links here, and the Help menu has Documentation, What's new and Contact support.
- **Policies everywhere.** A row or column policy now applies wherever rows reach a person: the dataset page, charts and dashboards (public links too), the Studio, SQL, the assistant, comparisons, downloads and deliveries. Before, it applied only to downloads.
- **Network access.** An organisation can be limited to its own networks, for sign-in, sessions and API tokens alike.
- **Encrypted files.** With a key set, every stored file is encrypted, and one command encrypts the files already there.
- **Sessions you can see.** Your settings shows how long a session lasts without use and at most.
- **Failures reach people.** Incidents and failed workflows can go to email and Slack, and everyone who can act on an incident hears about it in the app. A weekly summary joins "each" and "daily summary".
- **An API guide that works.** Signing in with a token and three worked examples, all run by a test so they stay right.

## Copy and consistency

- Every screen in the same words: recipe, import, check, schema change, deliver.
- Runs, datasets and the audit trail read as sentences, with identifiers behind **Technical details**.
- Nothing smaller than 12 pixels, no capital-letter labels, and one set of tables, badges, dialogs and tabs everywhere.

## Sources and destinations

- Running an import or a recipe again adds a version to the same dataset instead of making a new one.
- Import from apps, APIs and storage, not only databases, with "only new rows" where the source allows.
- Deliver any dataset to PostgreSQL, MySQL, S3 or a server folder, and see the table that will be written first.
- **Copy a database** into PostgreSQL or MySQL, with a report of anything it could not carry.
- Download any version as CSV or Parquet.

## The Studio

- The preview takes most of the page; steps sit in a timeline beside it.
- A step's settings open right under it, and each step says what it does in a few words.
- One search finds any step; right-click a column for steps that suit it.
- Undo and redo, and unsaved work is kept and offered back next time.

## Getting started

- Sample files and recipe templates to start from.
- A checklist on each project's Overview that lights the next step.
- **About this page** on every page.
- Notifications one by one, as a summary, or not at all.

## Finding your way

- Seven areas in the rail, each with tabs, instead of 31 links.
- Search (⌘K or Ctrl+K) finds any page, dataset or dashboard.
- Old addresses still work: they move you to the new page.
