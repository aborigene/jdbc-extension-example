# Dynatrace JDBC Extension Examples

Two working examples of how to build a **Dynatrace Extensions 2.0 extension that uses the JDBC datasource**. Such an
extension runs SQL queries on a schedule from an ActiveGate and ingests the results into Dynatrace as logs or metrics,
with no custom code. You describe the queries and the field mappings in an `extension.yaml` file.

| Example | Database | Driver | Ingests | Folder |
|---|---|---|---|---|
| **MySQL** | MySQL | MySQL Connector/J (`com.mysql.cj.jdbc.Driver`) | Table rows as logs | [MySQL/](MySQL/) |
| **MongoDB** | Amazon DocumentDB (MongoDB-compatible) | Amazon DocumentDB JDBC driver (`software.amazon.documentdb.jdbc.DocumentDbDriver`) | Documents as logs, aggregates as metrics | [MongoDB/](MongoDB/) |

Each folder has its own README with the full step-by-step instructions. Start with MySQL, which is the simpler case, then
read MongoDB for what changes with a non-SQL database.

## How a JDBC extension works

```
Database  <--SQL over JDBC--  ActiveGate (runs the extension)  --logs/metrics-->  Dynatrace
```

1. **`extension.yaml`** defines the JDBC driver class, a validation query, and one or more *groups*. Each group has a SQL
   query, an interval, and a mapping from result columns (`col:<name>`) to log attributes, or to metric dimensions and values.
2. **The JDBC driver JAR** is not part of the extension. Copy it by hand to each ActiveGate in the group that runs the
   extension (`.../remotepluginmodule/agent/conf/userdata/libs/`).
3. **The extension is signed** with a developer certificate. The root (CA) certificate must be in the tenant's
   Credential vault and on the ActiveGate as `root.pem`.
4. **Build and upload** the extension (VS Code *Dynatrace Extensions* plugin or `dt-sdk`).
5. **A monitoring configuration** supplies the connection string, credentials and the ActiveGate group. These are kept
   out of the YAML on purpose.

## Example 1: MySQL (`MySQL/`)

A simple relational case. Two groups query the `send_pix` and `received_pix` tables every minute and ingest each row of
the last minute as a log record (`pix_started` / `pix_received`).

It shows:
- the structure of the `jdbc:` block and how `ingest: log` and `attributes` work
- installing MySQL Connector/J on the ActiveGate
- generating, distributing and installing the signing certificates
- building, uploading, activating, and checking the result with DQL

`MySQL/extension-example.yaml` is the original version that used the native `sqlMySql` datasource, kept for reference.

## Example 2: MongoDB (`MongoDB/`)

Shows what is different when the database is not SQL. JDBC needs a driver that translates SQL into MongoDB queries. This
example uses the Amazon DocumentDB JDBC driver and an `orders` collection. It has two groups:

- `order_events`: new orders of the last minute, ingested as **logs**
- `order_stats`: orders of the last 5 minutes grouped by `status`, ingested as **metrics**
  (`docdb.orders.count`, `docdb.orders.amount.total`, `docdb.orders.amount.avg`)

It also covers:
- how the driver maps collections and fields to SQL tables and columns, and its limitations
- the driver's schema cache and how to run with a read-only database user
- `scripts/generate_data.py`, a generator that keeps inserting fake orders so you can see data flowing
- a troubleshooting table for the common driver, network, and signing problems

Notes on which driver to use for MongoDB Atlas or a self-hosted `mongod` are in the MongoDB README.

## Repository layout

```
.
├── MySQL/
│   ├── extension/extension.yaml        # JDBC extension definition (MySQL)
│   ├── extension-example.yaml          # original native sqlMySql version
│   └── README.md
└── MongoDB/
    ├── extension/extension.yaml        # JDBC extension definition (DocumentDB)
    ├── scripts/generate_data.py        # test data generator
    ├── scripts/requirements.txt
    ├── dist/                           # built and signed extension packages
    └── README.md
```

## Prerequisites

- A Dynatrace environment with Extensions 2.0, and an ActiveGate that can reach the database
- VS Code with the *Dynatrace Extensions* plugin, or `dt-extensions-sdk` (`pip install dt-extensions-sdk`)
- The JDBC driver JAR for your database
- Python 3.9+ (MongoDB example only, for the data generator)

## References

- [JDBC monitoring configuration](https://docs.dynatrace.com/docs/ingest-from/extensions20/data-sources/sql/jdbc-monitoring)
- [Sign extensions](https://docs.dynatrace.com/docs/ingest-from/extensions20/sign-extension)
- [Dynatrace Extensions for VS Code](https://developer.dynatrace.com/develop/extensions/dynatrace-extensions-vscode/commands/)
