# Dynatrace JDBC Extension Example: Amazon DocumentDB (MongoDB-compatible)

Demo extension (`custom:db.docdb.orders.jdbc.extension`) that reads an Amazon DocumentDB collection with the
**Extensions 2.0 JDBC datasource** (`jdbc:` in `extension.yaml`). It also includes a script that keeps inserting fake
documents, so you can see data flowing into Dynatrace.

| Group | Collection | Ingested as |
|---|---|---|
| `order_events` | `orders` (new docs of the last minute) | Logs, `content = order_created` |
| `order_stats` | `orders` (last 5 minutes, grouped by `status`) | Metrics `docdb.orders.count`, `docdb.orders.amount.total`, `docdb.orders.amount.avg` by `order.status` |

The collection and field names are examples. Change the queries to fit your own data (see section 6).

```
MongoDB/
├── extension/extension.yaml      # extension definition (JDBC datasource)
├── scripts/generate_data.py      # keeps feeding the collection
├── scripts/requirements.txt
└── README.md
```

## 0. Read this first: which JDBC driver?

MongoDB is not a SQL database, so a **JDBC driver that translates SQL to MongoDB queries** is needed.

| Your database | Driver | Class |
|---|---|---|
| **Amazon DocumentDB** (this example) | [Amazon DocumentDB JDBC driver](https://github.com/aws/amazon-documentdb-jdbc-driver) (open source, JDBC URL `jdbc:documentdb://`) | `software.amazon.documentdb.jdbc.DocumentDbDriver` |
| MongoDB Atlas | [Official MongoDB Atlas SQL JDBC driver](https://github.com/mongodb/mongo-jdbc-driver). It only works with Atlas (SQL interface / Data Federation), not with a plain `mongod`. | `com.mongodb.jdbc.MongoDriver` |
| Self-hosted `mongod` | A third-party driver (e.g. UnityJDBC) | see the vendor docs |

This example uses the DocumentDB driver, which also runs against a MongoDB-compatible server. For other drivers, change
`driverClassName`, `connectionStringPattern`, and the queries in `extension.yaml`.
There is no MongoDB-specific example in the Dynatrace docs, so test the extension in your environment.

How the driver maps documents to SQL (this affects how you write queries):

- A **collection is a SQL table**. A simple field is a column. The primary key column is named `<collection>__id` (here `orders__id`).
- A sub-document or an array becomes an extra **virtual table** named `<collection>_<field>`, joined by the key. This example uses flat documents on purpose.
- Only `SELECT` is supported, **a `FROM` clause is mandatory** (no `SELECT 1`) and identifiers are **case-sensitive**.
- Joins across collections are not supported. `ORDER BY` columns must also be in the `SELECT` list.
- BSON `Date` maps to `TIMESTAMP`, so `createdAt >= TIMESTAMPADD(MINUTE, -1, CURRENT_TIMESTAMP)` works.
  Store dates as real BSON dates (not strings). The script does this.

## 1. Prerequisites

- An **Amazon DocumentDB cluster** and a user/password. DocumentDB runs **inside a VPC** and has no public endpoint.
- An **ActiveGate** (Extensions 2.0 enabled) that can reach the cluster on port `27017`, e.g. an ActiveGate on an EC2 instance in the same VPC (or a peered VPC). The security group of the cluster must allow it.
- A machine to run the data generator. It must also reach the cluster (an EC2 instance in the VPC, or through an SSH tunnel, see 2.2).
- Python 3.9+ for the script, and VS Code with the *Dynatrace Extensions* extension to build the extension.

## 2. Create the data (the database is empty)

### 2.1 Download the TLS bundle

DocumentDB uses TLS by default:

```bash
curl -o global-bundle.pem https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
```

### 2.2 Network access

- **From an EC2 instance in the VPC**: nothing else to do.
- **From your laptop**: open an SSH tunnel through an EC2 instance in the VPC (see [AWS: connect from outside a VPC](https://docs.aws.amazon.com/documentdb/latest/developerguide/connect-from-outside-a-vpc.html)):
  ```bash
  ssh -i ~/.ssh/<key>.pem -N -L 27117:<cluster-endpoint>:27017 ec2-user@<ec2-public-dns>
  ```
  Then use `localhost:27117` in the URI and add `tlsAllowInvalidHostnames=true` (the certificate does not match `localhost`), and remove `replicaSet=rs0`.

### 2.3 Run the generator

```bash
cd MongoDB/scripts
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export DOCDB_URI='mongodb://<user>:<password>@<cluster-endpoint>:27017/?tls=true&replicaSet=rs0&readPreference=secondaryPreferred&retryWrites=false'
export DOCDB_TLS_CA_FILE=../global-bundle.pem
export DOCDB_DATABASE=shop            # default: shop (created on the first insert)

python generate_data.py --backfill 200 --once   # 1) seed 200 orders from the last 10 minutes
python generate_data.py                          # 2) keep inserting 1-5 orders every 5 seconds (Ctrl+C to stop)
```

Options: `--interval` (seconds), `--min-batch/--max-batch`, `--collection`, `--db`. URL-encode special characters in the password.

Each document looks like this:

```json
{
  "orderId": "3f9a1c2b7d10", "customer": "alice", "country": "BR", "status": "PAID",
  "paymentMethod": "pix", "items": 3, "amount": 142.5, "createdAt": { "$date": "2026-10-30T15:04:05Z" }
}
```

Check it in `mongosh`:

```bash
mongosh --tls --tlsCAFile global-bundle.pem --host <cluster-endpoint>:27017 --username <user> --password <password> shop
> db.orders.countDocuments()
> db.orders.find().sort({createdAt:-1}).limit(3)
```

> **Create the data before the first connection of the extension.** The JDBC driver builds the SQL schema by sampling the
> collection and caches it. If `orders` is empty when the driver first connects, the table does not exist, and later it
> will not pick up new collections or fields. To rebuild, add `refreshSchema=true` to the connection string once, then remove it (it hurts performance).

## 3. DocumentDB user permissions (read-only is possible)

The extension queries are `SELECT` only, so the Dynatrace user does **not** need write access to your data.
The only write need comes from the driver: it caches its SQL schema mapping in two collections of the same database
(`_sqlSchemas`, `_sqlTableSchemas`). There are three ways to deal with it:

**Option A (recommended for customers): pre-generate the schema once, then use a read-only user.**
A DBA (or you, with a temporary admin user) generates the schema one time with the driver's command line tool. After that
the Dynatrace user only needs the `read` role, which also covers reading the cache collections:

```bash
java -jar documentdb-jdbc-1.4.5-all.jar --generate-new \
    --server <cluster-endpoint>:27017 --database shop -u <admin-user> --tls
# prompts for the password. Add -a (--tls-allow-invalid-hostnames) when using an SSH tunnel
```

```javascript
// mongosh, as the admin user: read-only user for Dynatrace
use admin
db.createUser({ user: "dynatrace", pwd: "<password>", roles: [ { role: "read", db: "shop" } ] })
```

Run `--generate-new` again (it adds a new schema version) when you add collections or fields you want to query.
Other commands: `--list-schema`, `--remove`, `--export`/`--import` (see the [CLI docs](https://github.com/aws/amazon-documentdb-jdbc-driver/blob/develop/src/markdown/schema/manage-schema-cli.md)).

**Option B: `readWrite` only for the first connection.** Create the user with `readWrite` on `shop`, activate the extension
once so the driver creates the cache, then change the role to `read`.

**Option C: read-only and no cache at all.** According to the driver docs, if the schema cannot be saved it is still used
in memory, but discovery then runs on **every connection**, which can hurt performance. Not recommended for a 1-minute interval.

If the customer uses collection-level access control, `find`, `insert` and `update` are needed on the two cache collections only while creating or updating the schema (Options A/B).

## 4. JDBC driver (must be copied manually)

The driver is **not** part of the extension. Upload it to each ActiveGate in the group that runs the extension
(JDBC 4.0+ drivers are supported).

1. Download `documentdb-jdbc-<version>-all.jar` (v1.4.5 at the time of writing, Java 8+) from the
   [releases page](https://github.com/aws/amazon-documentdb-jdbc-driver/releases). Use the `-all` JAR (dependencies included).
2. Copy it to the ActiveGate:

   | OS | Folder |
   |---|---|
   | Linux | `/var/lib/dynatrace/remotepluginmodule/agent/conf/userdata/libs/` |
   | Windows | `C:\ProgramData\dynatrace\remotepluginmodule\agent\conf\userdata\libs` |

   ```bash
   sudo mkdir -p /var/lib/dynatrace/remotepluginmodule/agent/conf/userdata/libs
   sudo cp documentdb-jdbc-1.4.5-all.jar /var/lib/dynatrace/remotepluginmodule/agent/conf/userdata/libs/
   sudo chmod 775 /var/lib/dynatrace/remotepluginmodule/agent/conf/userdata/libs/documentdb-jdbc-1.4.5-all.jar
   ```
   The `dtuserag` user must be able to read it. The Dynatrace docs don't say if a restart is needed. If the driver is not
   found, restart the Extension Execution Controller / ActiveGate.
3. The driver embeds the Amazon RDS root CA, so the `global-bundle.pem` is optional for the extension. If you want to
   use it, add `tlsCAFile=<path on the ActiveGate>/global-bundle.pem` to the connection string.

## 5. Sign, build, upload and activate

### 5.1 Certificates

Extensions must be signed. The **root (CA) certificate** has to be in the tenant's **Credential vault** and on **each ActiveGate** that runs the extension.

1. **Generate** (VS Code): Command Palette → **Dynatrace Extensions: Generate Certificates**. It creates the CA and developer certificates in the workspace storage and stores the paths in the settings. (Or with the SDK: `pip install dt-extensions-sdk && dt-sdk gencerts`, default output `~/.dynatrace/certificates`.)
2. **Find them**: VS Code settings `dynatraceExtensions.rootOrCaCertificateLocation` (`ca.pem`, goes to the vault and the ActiveGate) and `dynatraceExtensions.developerCertkeyLocation` (`developer.pem`, used to sign). Never share `ca.key` or the developer key.
3. **Credential vault**: **Dynatrace Extensions: Distribute certificate** (or *Credential vault → Add new credential*, type *Public certificate*, scope *Extension validation*). Repeat for every environment.
4. **ActiveGate**: copy `ca.pem` to the host as **`root.pem`**:

   | OS | Folder |
   |---|---|
   | Linux | `/var/lib/dynatrace/remotepluginmodule/agent/conf/certificates/` (readable by `dtuserag`) |
   | Windows | `%PROGRAMDATA%\dynatrace\remotepluginmodule\agent\conf\certificates` (readable by `LOCAL_SERVICE`) |

   ```bash
   scp ca.pem ec2-user@<activegate>:/tmp/ca.pem
   sudo mkdir -p /var/lib/dynatrace/remotepluginmodule/agent/conf/certificates
   sudo cp /tmp/ca.pem /var/lib/dynatrace/remotepluginmodule/agent/conf/certificates/root.pem
   sudo chown dtuserag:dtuserag /var/lib/dynatrace/remotepluginmodule/agent/conf/certificates/root.pem
   ```
   If a signature error persists, check the permissions and restart the EEC.

### 5.2 Build and upload

1. Open the `MongoDB` folder as the workspace in VS Code. **Dynatrace Extensions: Build** (signs the package and writes it to `dist/`).
2. **Dynatrace Extensions: Upload** (or upload the ZIP in the Extensions app).

### 5.3 Monitoring configuration

Extensions app → **custom:db.docdb.orders.jdbc.extension** → **Add monitoring configuration**:

- **Scope**: the ActiveGate group with the driver, `root.pem` and network access to the cluster. Only one ActiveGate of the group runs the configuration.
- **Endpoint**: host, port `27017` and connection string:
  ```
  jdbc:documentdb://<cluster-endpoint>:27017/shop?tls=true&replicaSet=rs0&readPreference=secondaryPreferred
  ```
- **Authentication**: `basic` with the DB user/password (or a Credential vault entry). Don't put the password in the connection string, because it is not hashed.

Make sure the generator has inserted data before you save (section 2.3).

## 6. Verify in Dynatrace

Logs (within ~1-2 minutes, and only while the generator is running):

```dql
fetch logs
| filter content == "order_created"
| sort timestamp desc
```

Metrics (the metric keys are the ones from `extension.yaml`):

```dql
timeseries { orders = max(docdb.orders.count), revenue = max(docdb.orders.amount.total) }, by: { order.status }
```

If nothing shows up:

1. Extension status in the monitoring configuration (shows the `versionQuery` result when connected) and the EEC logs on the ActiveGate.
2. Run the same SQL in a SQL client (DBeaver / DbVisualizer with the driver JAR) to check that the queries work against the driver.

### Adapting to your own data

Replace `orders` and its fields in both queries and in `attributes` / `dimensions`.
Use a BSON date field in the `WHERE` clause. Remember that a nested field becomes a virtual table `<collection>_<field>`.
Use only `SELECT` and no SQL comments in the queries (Dynatrace rejects them).

## 7. Troubleshooting

| Symptom | Likely cause |
|---|---|
| `ClassNotFoundException: software.amazon.documentdb.jdbc.DocumentDbDriver` | JAR not in `userdata/libs`, not readable by `dtuserag`, or the EEC was not restarted |
| Connection timeout | The ActiveGate cannot reach the cluster (VPC, route, security group port 27017) |
| `Table 'orders' not found` / unknown column | Schema cached while the collection was empty, or the field names are wrong (case-sensitive). Use `refreshSchema=true` once |
| Authentication failed | Wrong user/password, or the user lives in another auth DB (`defaultAuthDb`; DocumentDB uses `admin`) |
| Permission error creating `_sqlSchemas`, or slow queries | The schema cache doesn't exist and the user is read-only. Pre-generate the schema (section 3, Option A) |
| TLS / hostname errors via a tunnel | Add `tlsAllowInvalidHostnames=true`, and remove `replicaSet` |
| Upload fails with a signature error | Root certificate missing in the vault, or not named `root.pem` / not readable on the ActiveGate |
| No logs | The generator is stopped, so no new documents exist in the last minute (the queries use a 1-minute window) |

## Sources

- [Amazon DocumentDB JDBC driver: connection string](https://github.com/aws/amazon-documentdb-jdbc-driver/blob/develop/src/markdown/setup/connection-string.md), [schema caching](https://github.com/aws/amazon-documentdb-jdbc-driver/blob/develop/src/markdown/schema/schema-caching.md), [SQL limitations](https://github.com/aws/amazon-documentdb-jdbc-driver/blob/develop/src/markdown/sql/sql-limitations.md)
- [MongoDB Atlas SQL JDBC driver](https://github.com/mongodb/mongo-jdbc-driver)
- [Dynatrace: JDBC monitoring configuration](https://docs.dynatrace.com/docs/ingest-from/extensions20/data-sources/sql/jdbc-monitoring)
- [Dynatrace: Sign extensions](https://docs.dynatrace.com/docs/ingest-from/extensions20/sign-extension)
- [Dynatrace Extensions for VS Code: commands](https://developer.dynatrace.com/develop/extensions/dynatrace-extensions-vscode/commands/)
