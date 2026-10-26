# Private sources

Give your application’s checks read access to any private Domain or Extension repositories.

## Private sources

If a source is private, CI needs read access to it: the setup repository's normal token may not read another private repository. Use a GitHub App (preferred) or a `SOURCE_READ_TOKEN` secret.

**GitHub App (preferred).** Each check run mints its own token, limited to reading the repositories the App is installed on. It expires within the hour and is revoked when the job ends, so no long-lived token is stored.

1. Create a GitHub App owned by the account that owns the sources: no webhook, repository permission **Contents: Read-only**, installable only on that account.
2. Install it on the private source repositories only.
3. In this repository's Actions settings, set the variable `SOURCE_APP_CLIENT_ID` to the App's client ID and the secret `SOURCE_APP_PRIVATE_KEY` to a private key generated for the App.

When `SOURCE_APP_CLIENT_ID` is set, the check uses the App; otherwise it falls back to the `SOURCE_READ_TOKEN` secret.

**`SOURCE_READ_TOKEN`.** A fine-grained token with read access to only the required source repositories, stored as an Actions secret.

**Pull requests.** By default pull requests receive no source token, so with a private source in the recipe their checks fail at "Materialize exact sources", and the check on `main` after the merge is the one that counts. To check pull requests fully, set the repository variable `SOURCE_READ_ON_PULL_REQUESTS` to `true`: pull requests from the repository's own branches then receive the token. Pull requests from forks never do. **Turn it on only if everyone who can push a branch here may read every private source**, because a pull request's code can print the token.

The materialization and remote-verification step passes the token through a password helper restricted to `https://github.com`. Unexpected hosts and prompts are refused. Sources on other hosts use your own host-specific credential helper. It saves no Git credentials and caches only Cargo downloads and build outputs. Never put a token in `setup.toml`, a Git URL, the lock, a cache or a release asset.

For local private-source access, use your own Git credential helper or `GIT_ASKPASS`. No server credentials belong in Actions.

## Where to go next

Return to [Releasing your application](releasing.md) to publish the checked application.
