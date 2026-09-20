# Running Estock on your machine

For trying the product by hand: click through the web app, the shop floor
screens on a phone-sized browser, and the public storefront, against a realistic
demo business.

## The short version

```bash
git clone https://github.com/teddyabe6/Estock.git
cd Estock
git checkout claude/vigilant-cerf-nfse7y
./scripts/demo.sh
```

Then open **http://localhost:3000** and sign in as
`owner@merkato-demo.et` / `demo-password-123`.

Press Ctrl-C to stop. Your data stays in `backend/var/demo.db`; delete that file
to start over.

## What you need first

| | Version | Check with | If missing |
| --- | --- | --- | --- |
| Python | 3.11 or newer | `python3 --version` | [python.org/downloads](https://www.python.org/downloads/) — or `brew install python@3.11` |
| Node.js | 20 or newer | `node --version` | [nodejs.org](https://nodejs.org/) — or `brew install node` |

That is all `./scripts/demo.sh` needs. It uses SQLite, so **there is no database
to install**. It creates the Python environment, installs dependencies, prepares
the database and starts both servers.

Two things are optional:

- **Flutter** — only for the mobile app. [flutter.dev/docs/get-started/install](https://docs.flutter.dev/get-started/install)
- **Docker** — an alternative way to run everything, described below.

## Signing in

The demo business is **Merkato Wholesale**: two branches, four staff, twelve
products (two with Amharic names), stock, sales, a supplier payable, an overdue
receivable, a published storefront and a proforma.

Every password is `demo-password-123`.

| Sign in as | To see |
| --- | --- |
| `owner@merkato-demo.et` | Everything, including cost and profit |
| `manager@merkato-demo.et` | Operations for the Bole branch only |
| `cashier@merkato-demo.et` | Sales only — no cost, no profit, no reports |
| `store@merkato-demo.et` | Stock only — cannot record a sale |
| `admin@estock.et` | Platform admin, at `/docs` (password `admin-password-123`) |

Signing in as the cashier and then the owner is the quickest way to see the
permission rules working: the cashier has no Reports tab and no profit figures
anywhere.

## Worth trying by hand

**A sale on credit.** Sales → New sale, add a product, lower *Received* below
the total. A customer becomes required, and you get due-date choices. Leave the
due date as *No due date* and watch the credit list: the balance is outstanding
but never marked overdue, however long it sits. That is deliberate — elapsed
time alone does not make a debt late.

**Cost and profit visibility.** Sign in as the cashier and look at Products.
There is no cost column, and the dashboard shows no profit. The server is what
enforces this, not the interface.

**The storefront, with no sign-in.** Open
http://localhost:3000/shop/merkato-wholesale in a private window. Submit an
enquiry, then check Shop → Enquiries as the owner. Note that stock did not move:
an enquiry never reserves anything.

**A proforma.** Create one, send it, open the share link in a private window.
It says plainly that it is not a receipt. Accepting it records intent — it does
not post a sale or reduce stock until you convert it explicitly.

**Recording a payment.** Credit → Record payment on the overdue balance. Try
paying more than is owed: it is refused, and the error tells you the exact
balance.

**Amharic.** Products → search `ቡና`. The name, its category `መጠጦች`, and search
all work.

## The mobile app

You do not need Android tooling to look at it. With `./scripts/demo.sh` running,
in a second terminal:

```bash
make mobile-web       # http://localhost:8090
```

Open it and switch your browser to a phone size (F12 → device toolbar).

**Try offline capture**, which is the interesting part: sign in, go to Sales,
then in DevTools set the network to *Offline*. Record a sale. A banner says the
work is held on the device. Go back online and it syncs by itself; More →
Waiting to sync shows what happened.

On a real device or emulator, with Flutter installed:

```bash
make mobile           # uses http://localhost:8000/api/v1
```

On an Android emulator the host is `10.0.2.2`, not `localhost`:

```bash
cd mobile && flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000/api/v1
```

For a physical phone, use your machine's LAN address and add it to
`CORS_ORIGINS` in `backend/.env`.

## The fuller setup

`./scripts/demo.sh` uses SQLite and skips the background worker. For the real
shape of the system — PostgreSQL, the reminder worker, hot reload — use:

```bash
make setup                       # one-off
# start PostgreSQL, then:
make migrate seed
make api                         # terminal 1
make web                         # terminal 2
make worker                      # terminal 3, optional
```

`make help` lists everything. PostgreSQL is expected at
`postgresql+psycopg://estock:estock@localhost:5432/estock`; override with
`DATABASE_URL` or edit `backend/.env`.

### With Docker

```bash
make docker      # builds and starts everything, with demo data
```

This runs PostgreSQL, Redis, the API, the worker and the web app together, which
is closest to a deployment.

> **Note:** unlike everything else on this page, the Docker path has not been
> run end to end — the sandbox this was built in blocks Docker Hub, so the
> images could never be pulled. The Compose file validates, and two real bugs
> were fixed by reviewing it (a named volume nested inside a bind mount would
> have been root-owned and broken uploads; the image's non-root user could not
> write to bind-mounted files on Linux). If it fails for you, the SQLite path
> above is fully tested and the faster way to start.

## If something goes wrong

### On WSL: the API works but the web app says ERR_CONNECTION_REFUSED

Windows forwards `localhost` into the WSL VM, but not reliably for every port.
When one port works and another does not, the usual cause is that the port falls
in a range Windows has reserved (Hyper-V, Docker Desktop and WSL itself claim
blocks of ports), so nothing can forward it.

The script prints the VM's own address when it detects WSL — use that, and it
works regardless:

```
http://172.x.x.x:3000
```

Find it yourself with `hostname -I` in WSL. Opening the app by that address
works fully — the web app calls the API on whatever host served the page, and
the demo script allows the machine's own addresses through CORS. The same is
true for testing from a phone on your network.

You will see one harmless console error, `webpack-hmr WebSocket failed`. That is
Next's hot-reload channel, which only speaks to `localhost`. Edits will not
refresh the page by themselves; reload manually. Nothing else is affected.

To confirm the cause, in **Windows** PowerShell:

```powershell
netsh interface ipv4 show excludedportrange protocol=tcp   # is 3000 in a reserved range?
netstat -ano | findstr :3000                               # is something else holding it?
```

To move off the reserved range instead:

```bash
WEB_PORT=3100 ./scripts/demo.sh
```

Note that the WSL VM's address changes when WSL restarts, so prefer a free port
if you are going to be working for a while.

**"Port 8000 is in use"** — something else is on that port.

```bash
API_PORT=8001 WEB_PORT=3001 ./scripts/demo.sh
```

**The web app loads but nothing appears, or sign-in says "Could not reach the
server"** — the API is not running, or the browser is calling the wrong place.
Check http://localhost:8000/health returns `{"status":"ok"}`. If you changed
`API_PORT`, the web app needs `NEXT_PUBLIC_API_BASE_URL` to match.

**A CORS error in the browser console** — the page's origin is not in the
allowed list. Add it to `CORS_ORIGINS` in `backend/.env` and restart the API.
Ports 3000 and 8090 are allowed by default.

**"Python 3.11 or newer is required"** — an older `python3` is first on your
PATH. `python3.11 -m venv .venv` and re-run, or use Docker.

**Start completely fresh:**

```bash
rm -rf .venv web/node_modules backend/var/demo.db backend/.env
./scripts/demo.sh
```

**Run the tests:**

```bash
make test                # 219 backend + 31 mobile
make test-backend-pg     # backend against PostgreSQL
make lint
```

## What is running

| | Address | |
| --- | --- | --- |
| Web app | http://localhost:3000 | Owner, manager and cashier screens |
| API | http://localhost:8000 | |
| API docs | http://localhost:8000/docs | Every endpoint, try them in the browser |
| Storefront | http://localhost:3000/shop/merkato-wholesale | No sign-in |
| Mobile app | http://localhost:8090 | After `make mobile-web` |
