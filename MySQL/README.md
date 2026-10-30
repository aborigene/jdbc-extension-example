# Dynatrace JDBC Extension Example (MySQL → Logs)

Demo extension (`custom:db.logspixbizevent.jdbc.extension`) showing how to connect to a database with the
**Extensions 2.0 JDBC datasource** (`jdbc:` in `extension.yaml`). It runs two queries against MySQL every minute and
ingests each row as a Dynatrace log record:

| Group | Table | Log `content` |
|---|---|---|
| `pix_started_events` | `send_pix` | `pix_started` |
| `pix_received_events` | `received_pix` | `pix_received` |

The queries are the same as in the original `extension-example.yaml` (which used the native `sqlMySql` datasource).

> The original file also referenced an OpenPipeline pipeline/source (`pix-to-bizevents.*.json`). Those files are not in
> this repo, so that section was left out. Add the `openpipeline:` block back, with the JSON files under
> `extension/openpipeline/`, if you need it.

---

## 1. How the JDBC datasource works

```yaml
jdbc:
  driverClassName: com.mysql.cj.jdbc.Driver   # driver class inside the JAR
  validationQuery: SELECT 1                   # connection test
  versionQuery: SELECT VERSION()              # DB version shown in the UI
  groups:
    - group: ...
      interval: { minutes: 1 }
      ingest: log                             # or metrics
      query: ...
      attributes: [...]                       # for logs; one must be `content`
```

- `ingest: log` requires `query` and `attributes` (with a `content` key). `ingest: metrics` (default) uses `dimensions` and `metrics`.
- `col:<name>` takes the value from the result-set column.
- Connection details are **not** in the YAML. They go in the monitoring configuration (section 4).
- The query runs on an **ActiveGate** from the group you select. Only **one** ActiveGate in the group runs the configuration.
  Use a dedicated group if you want a single ActiveGate. It must reach the DB.

## 2. JDBC driver (must be copied manually)

The driver is **not** part of the extension package and Dynatrace does not ship it. Upload a JDBC 4.0+ driver to each
ActiveGate in the group that runs the extension. For MySQL, use **MySQL Connector/J**
(<https://dev.mysql.com/downloads/connector/j/>, "Platform Independent", file `mysql-connector-j-<version>.jar`).

| OS | Folder |
|---|---|
| Linux | `/var/lib/dynatrace/remotepluginmodule/agent/conf/userdata/libs/` |
| Windows | `C:\ProgramData\dynatrace\remotepluginmodule\agent\conf\userdata\libs` |

```bash
sudo mkdir -p /var/lib/dynatrace/remotepluginmodule/agent/conf/userdata/libs
sudo cp mysql-connector-j-<version>.jar /var/lib/dynatrace/remotepluginmodule/agent/conf/userdata/libs/
sudo chmod 775 /var/lib/dynatrace/remotepluginmodule/agent/conf/userdata/libs/mysql-connector-j-<version>.jar
```

The `dtuserag` user (Linux) must have read access to the JAR. The docs do not say whether a restart is required. If the
driver is not found, restart the Extension Execution Controller / ActiveGate.

If the DB server certificate is not from a publicly trusted CA, create a PKCS12 truststore named `sqlds_truststore`
(password `sqlds_truststore`) in the `userdata` folder (`/var/lib/dynatrace/remotepluginmodule/agent/conf/userdata`,
or `%PROGRAMDATA%\dynatrace\remotepluginmodule\agent\conf\userdata` on Windows).
Client certificates are not supported. Use basic authentication, optionally with SSL.

## 3. Certificates: signing the extension

Every extension must be signed. Dynatrace verifies the signature with your **root (CA) certificate**, which must be in the
tenant's **Credential vault** and on **each ActiveGate host** that runs the extension.

### 3.1 Generate the certificates

**Option A: VS Code (Dynatrace Extensions)**

1. Install the *Dynatrace Extensions* VS Code extension (`dynatraceplatformextensions.dynatrace-extensions`) and open this folder.
2. Command Palette (`Cmd/Ctrl+Shift+P`) → **Dynatrace Extensions: Generate Certificates**. It creates a CA key pair and a developer key pair/certificate signed by that CA.
3. The files are created in VS Code **workspace storage**, and the paths are written to the settings (not to the repo).

**Option B: `dt-sdk` (`dt-extensions-sdk`)**

```bash
pip install dt-extensions-sdk
dt-sdk gencerts                      # default output: ~/.dynatrace/certificates
# options: --output <dir> --ca_subject "/CN=.../O=.../OU=..." --ca_pass <pw> --dev_subject ... --dev_pass <pw> --days_valid 1095 --force
```

It generates the CA key, the CA certificate and a developer fused key+certificate.
(The separate `dt-cli` tool uses different commands, e.g. `dt extension genca` and `dt extension generate-developer-pem`. Don't mix them.)

Use a unique developer certificate per developer. For production, sign each extension with its own leaf certificate.

### 3.2 Get the certificates from VS Code

The Generate Certificates command stores the paths in these VS Code settings (Settings → search "Dynatrace Extensions"):

| Setting | File |
|---|---|
| `dynatraceExtensions.rootOrCaCertificateLocation` | `ca.pem`: the **root certificate** that goes to the ActiveGate and the vault |
| `dynatraceExtensions.developerCertkeyLocation` | `developer.pem`: developer key + certificate, used to sign |

To find the files, open **Settings (JSON)** (`Dynatrace Extensions: …` or `Preferences: Open User Settings (JSON)`) and copy the paths. Example from a Mac install:
`~/Library/Application Support/Code/User/workspaceStorage/<id>/DynatracePlatformExtensions.dynatrace-extensions/certificates/ca.pem`.
You can also copy `ca.pem` from there to a normal folder. **Never share `ca.key` or the developer key.**

### 3.3 Distribute the root certificate

**a) Dynatrace Credential vault.** This is a required step and must be done in every environment (dev, prod...).

- VS Code: **Dynatrace Extensions: Distribute certificate**. It uploads the CA certificate from `rootOrCaCertificateLocation` to the Credential vault. It also copies it to locally installed OneAgents/ActiveGates it finds.
- Manually: *Credential vault → Add new credential* with type **Public certificate**, scope **Extension validation**, and upload `ca.pem`.

**b) Each ActiveGate host** that runs the extension. The file **must be named `root.pem`**:

| OS | Folder | Owner/permission |
|---|---|---|
| Linux | `/var/lib/dynatrace/remotepluginmodule/agent/conf/certificates/` | readable by `dtuserag` |
| Windows | `%PROGRAMDATA%\dynatrace\remotepluginmodule\agent\conf\certificates` | readable by `LOCAL_SERVICE` |

```bash
scp ca.pem user@activegate:/tmp/ca.pem
# on the ActiveGate:
sudo mkdir -p /var/lib/dynatrace/remotepluginmodule/agent/conf/certificates
sudo cp /tmp/ca.pem /var/lib/dynatrace/remotepluginmodule/agent/conf/certificates/root.pem
sudo chown dtuserag:dtuserag /var/lib/dynatrace/remotepluginmodule/agent/conf/certificates/root.pem
ls -l /var/lib/dynatrace/remotepluginmodule/agent/conf/certificates/root.pem
```

If the extension still fails with a signature error, check the permissions above and restart the Extension Execution Controller (EEC).

## 4. Build, upload and activate

1. **Dynatrace Extensions: Build** in VS Code. It signs with the developer certificate and writes the ZIP to `dist/`. Or with the SDK: `dt-sdk build`.
2. **Dynatrace Extensions: Upload** (uploads the latest package from `dist`), or upload the ZIP in the Extensions app. The root certificate must already be in the Credential vault.
3. Add a **monitoring configuration** (UI, VS Code **Activate**, or API) with:
   - **Scope**: the ActiveGate group with the driver, `root.pem` and DB network access (`ag_group-<name>` in the API).
   - **Endpoint**: host, port and `connectionString`, e.g. `jdbc:mysql://<host>:3306/<database>`. The connection string is not hashed, so don't put secrets in it.
   - **Authentication**: scheme `basic`, with username/password, or a Credential vault entry (type User and password, with the *Extension* scope enabled and owner-only access).
   - **SSL**: enable it to verify the server certificate (ActiveGate 1.295+).

   Use a read-only DB user with `SELECT` on `send_pix` and `received_pix`.

## 5. Verify

In Dynatrace Logs, or with DQL:

```dql
fetch logs
| filter content == "pix_started" or content == "pix_received"
| sort timestamp desc
```

If nothing shows up: check the extension status (it shows the `versionQuery` result when connected), then the EEC logs on the ActiveGate on the ActiveGate.

## 6. Troubleshooting

| Symptom | Likely cause |
|---|---|
| `ClassNotFoundException: com.mysql.cj.jdbc.Driver` | JAR missing from `userdata/libs`, not readable by `dtuserag`, or EEC not restarted |
| Upload fails: signature / certificate error | Root certificate not in the Credential vault, not named `root.pem` on the ActiveGate, not readable by `dtuserag`, or the extension was signed with another CA |
| Connection timeout | Firewall or security group between ActiveGate and DB (port 3306) |
| `Access denied` | Wrong credentials or the DB user lacks `SELECT` |
| No rows | The query only returns rows from the last minute (`INTERVAL 1 MINUTE`) |

## Files

```
extension/extension.yaml   # JDBC extension definition
README.md
extension-example.yaml     # original sqlMySql version (reference)
```

## Sources

- [JDBC monitoring configuration](https://docs.dynatrace.com/docs/ingest-from/extensions20/data-sources/sql/jdbc-monitoring)
- [Sign extensions](https://docs.dynatrace.com/docs/ingest-from/extensions20/sign-extension)
- [Dynatrace Extensions for VS Code: commands](https://developer.dynatrace.com/develop/extensions/dynatrace-extensions-vscode/commands/)
- [dt-sdk gencerts](https://dynatrace-extensions.github.io/dt-extensions-python-sdk/cli/gencerts.html)
