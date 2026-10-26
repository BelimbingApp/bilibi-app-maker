# Settings

Your application keeps settings in three places: your machine, each server instance, and the app’s settings pages.

For example, you might run `sbg-bilibi` on your laptop and install the same release on Staging and Production. Each copy keeps its own address, database and business settings.

| Place | What belongs there | Where you change it |
| --- | --- | --- |
| Your machine | The local address, backend port and whether a browser opens | `.env` beside `./bilibi` |
| Each server instance | Its address, database, password, keys and initial role | The instance’s `env` file, written by `install-server.sh` |
| Inside the app | Business settings, such as an Extension’s connection or schedules | That instance’s settings pages |

## Your machine

To give your local copy another address, copy the example from your application root:

```sh
cp .env.example .env
```

Open `.env` and remove the `#` before the address line. For example:

```dotenv
BILIBI_DEV_HOST=my-sbg.localhost
```

Restart `./bilibi start` after saving. Your local address is now `https://my-sbg.localhost`, when local HTTPS is available.

**Keep `.env.example` in Git; keep your own `.env` out of Git.** The example lists the supported settings without secrets. Your `.env` belongs next to `./bilibi`, even when the Platform sources are stored elsewhere.

Without an override, your address is your application folder’s name under `.localhost`. For example, a clone in `acme-erp/` uses `https://acme-erp.localhost`. Names become lowercase, and spaces or other punctuation become hyphens. Each checkout also gets its own private database and database port. Copies can run beside one another.

> [!NOTE]
> Folder-based defaults are being updated separately in the Platform. With the saved Platform version, set `BILIBI_DEV_HOST` explicitly to choose your address.

If two checkouts have the same folder name, choose a different `BILIBI_DEV_HOST` for one. When another checkout owns the address, the launcher prints its own loopback HTTP address instead. Open the address it prints.

The launcher reads only these lines from `.env`:

| Line | What it changes | Default |
| --- | --- | --- |
| `BILIBI_DEV_HOST=my-sbg.localhost` | This copy’s HTTPS address; use a name under `.localhost` | Your application folder’s name |
| `BILIBI_DEV_PORT=4300` | The port Bilibi listens on behind Caddy, the local HTTPS server | The first free port from 4300 |
| `BILIBI_OPEN_BROWSER=0` | Whether the launcher opens the sign-in page: `1` opens it, `0` leaves it closed | `1` |

You can leave all three commented out to use the defaults. If you select a backend port, choose a free one and set `BILIBI_DEV_HOST` as well. Selecting a port does not take over another checkout’s HTTPS address.

A variable set in your shell wins over `.env`. Unknown lines are ignored with a message; invalid values stop the launcher. This file controls local startup. For the accepted values, HTTPS behavior and other shell settings, see the Platform’s [Local launcher reference](https://github.com/BelimbingApp/bilibi/blob/main/README.md#local-launcher). Its [application workspace reference](https://github.com/BelimbingApp/bilibi/blob/main/docs/application-workspaces.md) explains source and data locations.

## Server instances

Use a separate instance for Dev, Staging or Production. **Each instance has its own database, address, database password and keys.** Dev and Staging can share a server while keeping separate data.

The server installation script, `install-server.sh`, writes each instance’s settings to its own `env` file, such as `/opt/bilibi/staging/env`. Servers use that file rather than your laptop’s `.env`. You do not need committed `.env.development` and `.env.production` files.

The installation sets an initial role. After installation, change the role through **Instance settings** with a fresh 2FA code. Editing `BILIBI_ENV` in the server file does not change a role already saved in the app.

Follow the Platform’s [server installation reference](https://github.com/BelimbingApp/bilibi/blob/main/docs/server-install.md) to create an instance or change its address. It describes the files, permissions, database and service commands.

## Business settings

Change an Extension’s connection, schedules and other business choices in the app’s settings pages. Save them separately on each instance. For example, Staging can connect to a test service while Production connects to the live service.

Installing the same release on both instances gives them the same software. It does not make their business settings or data the same.

## Where to go next

[Running your application](running.md) covers daily use. [Installing a release](installing.md) explains how to install the same tested archive on Staging and Production.
