# What's new

The changes people notice, newest first. The full record is in the repository's changelog.

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
