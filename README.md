# The live systems

The cross-system examples of [AgenticHarvest](https://github.com/IBM/agenticharvest)
run against real, unmodified open-source products, not mocks or recorded
responses. So do the web domain's tests. This folder brings those products up
on your machine and points AgenticHarvest at them.

| System | Product | Plays the part of | API description AgenticHarvest reads | Port |
|---|---|---|---|---|
| `directus` | [Directus](https://directus.io) 11.17.4 | a shipping portal, an onboarding tracker | OpenAPI 3, served live at `/server/specs/oas` | 8055 |
| `keycloak` | [Keycloak](https://www.keycloak.org) 26.4.7 | the identity server people sign in with | the vendor's published Admin REST API (OpenAPI 3) | 8080 |
| `odoo` | [Odoo](https://www.odoo.com) 19.0 Community, Employees + Recruitment | the HR system | Odoo's own `/doc/<model>.json` self-description | 8069 |
| `runner` | AgenticHarvest itself, in a container | runs the examples and tests | — | — |

All the images are published for both `amd64` and `arm64` (Apple silicon).
They are pulled from `mirror.gcr.io` and `quay.io`, which do not rate-limit
anonymous pulls the way Docker Hub does.

This folder is a git submodule of AgenticHarvest (`examples/systems`), backed by the
[`agenticharvest-systems`](https://github.com/aster-test-generation/agenticharvest-systems)
repository, and it also works on its own.

## Quick start: nothing installed but Podman or Docker

You need **one** container runtime, **git**, and about **4 GB** of free memory.
Python, uv, and AgenticHarvest all run inside a container.

1. **Install a container runtime**, if you don't have one:
   - macOS: [Podman](https://podman.io/docs/installation), then once:
     `podman machine init --cpus 4 --memory 8192 && podman machine start`
   - Windows: [Podman](https://podman.io/docs/installation) or Docker Desktop
   - Linux: `sudo apt install podman` or `sudo dnf install podman` (or Docker)

   An existing Podman machine on macOS may have only 2 GB. Raise it with
   `podman machine stop && podman machine set --cpus 4 --memory 8192 && podman machine start`.

2. **Get the code** (any one of these):

   ```bash
   git clone --recurse-submodules https://github.com/IBM/agenticharvest.git
   cd agenticharvest/examples/systems
   ```

   ```bash
   git clone https://github.com/aster-test-generation/agenticharvest-systems.git   # just this stack
   cd agenticharvest-systems
   ```

   Cloned on its own, `run.sh` fetches AgenticHarvest into `./.agenticharvest` on
   first use and reuses it afterward. Delete that folder to pick up a newer
   AgenticHarvest.

3. **Run an example:**

   ```bash
   ./run.sh hire_to_onboard          # macOS / Linux
   .\run.ps1 hire_to_onboard         # Windows PowerShell
   ```

The first run pulls about 2 GB of images and initializes Odoo, which takes a few
minutes. Later runs start in seconds.

| Command | What it does |
|---|---|
| `./run.sh hire_to_onboard` | The HR example: Odoo + Keycloak + Directus |
| `./run.sh order_fulfillment` | The orders example: a database + Directus |
| `./run.sh <example> --agent` | Adds the live-LLM stage (see below) |
| `./run.sh <example> --keep` | Leaves the run's records in the apps, so you can look at them |
| `./run.sh check` | Start and provision the apps, then report what each one exposes |
| `./run.sh test` | The live-system tests, inside the runner |
| `./run.sh shell` | A shell in the runner, with everything installed |
| `./run.sh stop` | Stop the apps; keep their data |
| `./run.sh reset` | Stop the apps and delete all their data |

`run.sh` uses Podman if it is installed and Docker otherwise. Each run starts
the apps, builds the runner image from the AgenticHarvest source, provisions the
apps (below), and runs the command in the runner, which reaches the apps over
the compose network.

### Where the output goes

Each example writes its event logs, the miner's output (`process_model.json`),
and the agent's prompt to **`out/<example>/` in the folder you ran `run.sh`
from** (an example's own `run.sh` uses its own folder).
The runner writes into that folder directly, so they are ordinary files on
your machine:

```
out/
├── order_fulfillment/   erp.db · observed.ocel.json · process_model.json · agent_prompt.txt
└── hire_to_onboard/     observed.ocel.json · imported.ocel.json · process_model.json ·
                         imported_model.json · agent_prompt.txt · agent.ocel.json · agent_calls.json
```

Set `AGENTICHARVEST_OUT=/some/folder` to put them elsewhere. Each example's
`WALKTHROUGH.md` explains every file.

### The agent stage

`--agent` hands the mined process to an LLM. It needs any OpenAI-compatible
endpoint (OpenAI, a LiteLLM proxy, vLLM, or a local server):

```bash
export API_BASE=https://your-endpoint/v1 API_KEY=your-key MODEL=your-model
./run.sh hire_to_onboard --agent
```

You can also put those three lines in a `.env` file in the folder you run
`run.sh` from, or in the AgenticHarvest repo root. Values already in your environment win.

### Look at the apps

The apps keep running after an example finishes. Open them in a browser:

| App | URL | Login |
|---|---|---|
| Odoo | http://127.0.0.1:8069 | `admin` / `admin` |
| Keycloak | http://127.0.0.1:8080/admin/ | `admin` / `agenticharvest-admin` (switch to the `agenticharvest` realm) |
| Directus | http://127.0.0.1:8055/admin | `admin@example.com` / `agenticharvest-admin` |

Each example deletes what it created when it ends. Run it with `--keep` to see
its applicants, employees, accounts, tasks, and shipments.

## Developers: with Python and uv

To work on AgenticHarvest itself, run everything from the host instead. From the
AgenticHarvest repo root:

```bash
uv sync --extra web --extra openai_compatible --extra dev
podman compose -f examples/systems/compose.yaml up -d
uv run python examples/systems/setup.py

uv run python examples/hire_to_onboard/run.py --agent
uv run pytest -m live
uv run agenticharvest call list_resources app=directus
```

The host and the runner keep separate settings: the host writes `.env` in the
repo root, and the runner keeps its own on a volume. Each has its own Directus
API user, so neither revokes the other's token.

## What provisioning does

`setup.py` runs before every command. It is idempotent: what already works is
kept, and what is missing is created.

1. **Directus.** Creates the `shipments` and `onboarding_tasks` collections,
   plus an API user with a static token, one user per environment.
2. **Keycloak.** Creates the `agenticharvest` realm with admin-event auditing on,
   and three roles. It also downloads the vendor's Admin REST API description
   to `specs/`.
3. **Odoo.** Creates an API key for the admin user. Odoo's JSON-2 API accepts
   only API keys.
4. **Settings.** Writes the `AGENTICHARVEST_WEB_*` settings for all three apps to
   `.env`. Every other line of the file is left as it was.
5. **Check.** Loads each app's API description through AgenticHarvest:

```
  directus   ok      Dynamic API Specification …: 2 resources, 14 operations (10 write)
  keycloak   ok      Keycloak Admin REST API 1.0: 50 resources, 369 operations (181 write)
  odoo       ok      Odoo 19.0-…: 5 resources, 51 operations (41 write)
```

## Security

The admin passwords in `compose.yaml` (`agenticharvest-admin`, and Odoo's default
`admin`) are for a **local, throwaway stack only**. Every port is bound to
`127.0.0.1`, so nothing is reachable from your network. Do not reuse this
compose file for anything that holds real data.

Tokens and keys are written only to `.env` files and the runner's volume, never
into an image: the build excludes `.env`. AgenticHarvest never logs them, and it
strips credential headers from every result it returns.

## Pointing AgenticHarvest at your own systems

None of this is required to use the web domain. Any app that describes itself
with OpenAPI 3, and any Odoo 17+ server, can be configured with environment
variables. For one app named `hris`:

```bash
AGENTICHARVEST_WEB_APPS=hris
AGENTICHARVEST_WEB_HRIS_URL=https://hr.example.com
AGENTICHARVEST_WEB_HRIS_SPEC=/openapi.json        # a path on the app, a URL, or a local file
AGENTICHARVEST_WEB_HRIS_AUTH=bearer               # bearer | header | oauth2-password | odoo | none
AGENTICHARVEST_WEB_HRIS_TOKEN=…
```

The full list of settings is in AgenticHarvest's
[`src/agenticharvest/domains/web/config.py`](https://github.com/IBM/agenticharvest/blob/main/src/agenticharvest/domains/web/config.py)
and in the
[web apps section](https://github.com/IBM/agenticharvest#web-apps-five-tools-over-any-described-api)
of its README. Point it at a sandbox or test
tenant first: write tools are gated, but a confirmed write is a real write.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `Neither Podman nor Docker is installed` | Install one (step 1 above). |
| `podman is installed but not running` | `podman machine start` (macOS/Windows). |
| `git is needed to fetch agenticharvest.` | Install git. Cloned on its own, this repo downloads AgenticHarvest into `.agenticharvest` on the first run. |
| `fatal: destination path '…/.agenticharvest' already exists` | An earlier fetch was interrupted. Delete the `.agenticharvest` folder and run again. |
| `Remote branch … not found in upstream origin` | `AGENTICHARVEST_REF` names a branch or tag that does not exist. Unset it to use `main`. |
| `toomanyrequests` / HTTP 429 while pulling | A registry is rate-limiting. The pinned images avoid Docker Hub; check you are using this `compose.yaml`. |
| `no image found … for architecture` | An image without your CPU's build. All pinned images publish `amd64` and `arm64`. |
| `… is not answering` | An app is still starting (Odoo's first start takes minutes). Run `podman compose -f compose.yaml logs -f odoo`, then try again. |
| `directus FAILED … HTTP 401` | A token from an older stack. Run the command again; provisioning reissues it. |
| Odoo exits immediately | Check `podman logs agenticharvest-systems-odoo-1`. |
| Out of memory, or containers killed | Give the Podman machine more memory (step 1). |
| `Web app '…' is not configured` from a host script | Run host scripts from the AgenticHarvest repo root, where `.env` is. |
