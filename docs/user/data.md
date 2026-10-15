# Data

Where tables arrive: uploaded files, databases, apps, APIs, storage and live feeds.

## Sources

### Upload a file

Choose **Upload a file**. Spreadsheets, delimited text, JSON, XML, Parquet and more are read, plain or compressed. Before anything is saved, Pipewright shows how it will read the file: the columns, their kinds and a preview. If a date could be read two ways, it asks rather than guessing.

Large files upload in parts, so a dropped connection resumes rather than starts over.

### Connect a source

Choose **Connect a source** and pick from the catalogue: databases, apps such as GitHub or HubSpot, APIs and storage buckets. Each shows how well it is tested:

- **Tested** connectors run against a real server in every build.
- **Available on request** connectors are written from the vendor's documentation and have not yet been run against a real account. They usually work; tell your administrator if one does not, and it can be validated with you.

Keys and passwords are encrypted when saved and never shown again.

### Import from a source

On a connection, choose **See what it holds** (or **Browse tables** for a database), pick a table or a stream, preview it, and import it. An import can:

- replace everything each time,
- add only new rows, using a column that only goes up, such as an update time, or
- update matching rows, using the columns that identify a row.

Each run of an import adds a version to the same dataset, so you keep one dataset with a history rather than a new one per run.

## Live feeds

Data that arrives by itself, in **Data → Live feeds**. Pipewright reads each feed every few seconds (every 5 by default) and saves it to datasets every so often (every minute by default), each save a new version.

### Kinds of feed

- **Database changes.** Follow tables in PostgreSQL, MySQL, MongoDB or SQL Server through the database's own change log. Each table is kept as a dataset **as it is now**: a first full copy, then every insert, update and delete applied to the row with that key. A table without a primary key keeps only its changes. Your database administrator may need to switch change tracking on; **Try these settings** says exactly what to change.
- **Message queues.** Kafka, Azure Event Hubs, Amazon Kinesis, Google Pub/Sub, Apache Pulsar, RabbitMQ, NATS JetStream and MQTT. A feed reads from where it last stopped; the first time, from everything still kept or only from now.
- **Webhook.** A private address a partner's system posts events to, shown once when you make it.

Every feed also keeps **every event** that arrived as a dataset of its own, added to at each save.

### Is each event saved once?

Each feed says, where you choose it and on its page:

- **Saved once.** The feed's place in the source is saved with the events, so after a restart it carries on from exactly there. Kafka, Event Hubs, Kinesis, Pulsar, NATS, and the MySQL, MongoDB and SQL Server change logs.
- **Saved once, by its id.** Events are acknowledged after they are saved; one sent again is recognised by its id. PostgreSQL changes and Pub/Sub.
- **Saved at least once.** If Pipewright stops between saving and acknowledging, an event can be saved twice. MQTT, and RabbitMQ messages and webhook posts without an id; a webhook post with an `Idempotency-Key` header is saved once.

### Live recipes

On a feed's page, **Add a live recipe** runs on every batch as it arrives:

- **Steps from a recipe** that work row by row: filters, new columns, renames and clean-ups. Build the recipe in the Studio on the feed's **every event** dataset.
- **Look up** each event in a dataset, to bring along columns such as a customer's region.
- **Summarise by time**, in back-to-back windows, overlapping windows, the last so many minutes at every change, or sessions that end after a quiet gap, grouped by columns, with counts, sums, averages, lowest, highest, first and last.

A window is final once events a set time later than its end have arrived (**Wait for late events**). An event later still is counted and left out, or updates the window it belongs to if that closed recently. Results are saved with the place in the feed they reached, so a restart never counts an event twice. A live recipe's dataset holds the last 30 days of windows; older ones stay in its earlier versions.

### When a feed fails

A failing feed tries again later, up to every five minutes, and its maker is told after five failures in a row. If the database no longer has the changes since the feed last read, **Start again with a fresh copy** takes each table's first copy again; what was kept stays as earlier versions.

## Datasets

Every table in the project, one row per name. Filter by where it came from (uploaded, imported, made by a recipe) or find one by name.

On a dataset's page:

- **Rows** shows a preview, and **Columns** shows each column's kind, how often it is empty and how varied it is.
- **Comment on a cell**: click any cell in Rows (or use **Comment on a cell**) to start a thread about it. A cell with a thread is marked with how many it has. Threads take replies and @mentions, and resolve as a whole; replying to a resolved one opens it again. A row is named by its identifier column (such as an order number) when the dataset has one, so the thread stays with that row in later versions; otherwise by its number in that version.
- **History** (under **More**) shows what happened to it, newest first: each version and what made it, runs that failed to make one, checks, schema changes, contract problems, alerts and comments.
- **Clean in Studio** opens it in the [Studio](build.md#studio).
- **Send to** delivers it to a [destination](automate.md#destinations), Power BI or Tableau, or downloads it as CSV or Parquet.
- **Version history** lists every saved version. Open, query, compare or restore any of them; restoring adds a new version, so nothing is lost.

![A dataset's page: its rows, with Clean in Studio and Send to above them](images/dataset.png)

If a [policy](trust.md#policies) limits what your role can see, the page says so, and the same limit applies in charts, downloads and everywhere else.

## Catalog

Search datasets by name, by column or by what someone wrote about them. Mark owners and certify datasets that others can rely on, and keep a glossary so a word like "active customer" means one thing.
