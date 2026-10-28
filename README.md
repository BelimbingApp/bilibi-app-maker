# Bilibi app maker

The Bilibi app maker is the starting copy for your own application built on Bilibi. For example, a company can combine the Bilibi Platform, Finance and its own private Extension in one application. The application records the exact versions of these parts, so the company can release it to its servers and take Bilibi updates later.

## When to use it

To develop Bilibi itself, use the [Platform repository](https://github.com/BelimbingApp/bilibi). To run your own Bilibi on your servers, use this app maker.

> [!NOTE]
> In your application, replace this introduction and **Start here** with your own introduction. The linked guides describe your application as they are.

## Start here

1. Clone the maker into a folder named after your product, and start it:

```sh
git clone https://github.com/BelimbingApp/bilibi-app-maker my-bilibi
cd my-bilibi
./bilibi start
```

Your copy opens at `https://bilibi.localhost`. If you run more than one Bilibi on this computer, give each its own name with `BILIBI_DEV_HOST=<name>.localhost` in `.env` beside `./bilibi`; see [Settings](docs/guides/settings.md).

The first start installs what is missing, such as Rust, PostgreSQL and Node, and builds Bilibi, so it takes a while. Then Bilibi opens in your browser at the sign-in page. Sign in as `ai@agent.my` / `bilibi-dev`. You now have the Platform on its own: sign-in, companies, people, users, permissions and audit.

2. Add the business features you want. A Domain is one business area, such as Finance:

```sh
./bilibi add finance
./bilibi start
```

The **Software** page in Bilibi lists what is available, and shows the exact `add` command for each one.

3. Make it yours. Create an empty private repository on GitHub, for example `your-company/my-bilibi`, then run:

```sh
git remote rename origin upstream
git remote add origin https://github.com/your-company/my-bilibi.git
gh repo set-default your-company/my-bilibi
git push -u origin main
```

Your folder now has two remotes. `origin` is your application, where you push. `upstream` is the maker, so you can take its later improvements: see [Take maker updates](docs/guides/maker-updates.md#take-maker-updates).

> [!WARNING]
> Clone the maker as shown. A copy made any other way, such as a downloaded ZIP file, has none of the maker's history, and maker updates can then no longer merge.

4. Save the versions you use, then release. When the Domains you added work, record their exact versions and commit them. This step needs Docker:

```sh
./bilibi pin
git add setup.toml composition/
git commit -m "Add Finance"
git push
```

To install it on a server, follow [Release your setup](docs/guides/releasing.md#release-your-setup) and [Install a release](docs/guides/installing.md#install-a-release).

## Guides

- [Settings](docs/guides/settings.md): local addresses, databases and settings for each instance.
- [Running your application](docs/guides/running.md): requirements, workspace, commands and commit safeguards.
- [Releasing your application](docs/guides/releasing.md): save versions, check, build and publish a release.
- [Installing a release](docs/guides/installing.md): put a tested release on Staging and Production.
- [Private sources](docs/guides/private-sources.md): give checks access to private repositories.
- [Taking maker updates](docs/guides/maker-updates.md): merge maker improvements and update older workspaces.
- [Application repositories](docs/guides/about.md): where changes belong and what the maker provides.
