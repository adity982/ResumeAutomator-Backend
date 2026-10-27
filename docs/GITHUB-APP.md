# Activate selected private GitHub imports

The implementation uses GitHub App user authorization with PKCE. It does not request the broad OAuth `repo` scope. GitHub limits a user token to resources both that user and the installed App can access. Register an App with **Contents: read-only** and metadata read access only. Disable unneeded webhook delivery. Install it on selected repositories, not every repository, unless the user deliberately chooses otherwise.

Create the App in the owner's GitHub developer settings. Set the homepage to the frontend URL and the user authorization callback to exactly `https://resume-automator-frontend.vercel.app/` (no query or fragment). Use a separate App/callback for local development. Keep expiring user tokens enabled; this release reconnects after at most eight hours and does not retain refresh tokens.

Set `GITHUB_APP_CLIENT_ID`, `GITHUB_APP_CLIENT_SECRET`, `GITHUB_APP_SLUG`, `GITHUB_REDIRECT_URI` and `CONNECTION_ENCRYPTION_KEY` in the API's encrypted environment group. Generate the latter with `Fernet.generate_key()` from Python's cryptography package in a trusted operator environment; never commit or paste the result into a chat. Back up the key separately in the secret manager. A lost/changed key requires users to reconnect. No GitHub App private signing key is needed for this user-token flow.

The UI offers Choose repositories → Connect GitHub → Finish GitHub connection. The frontend sends code/state to an authenticated API endpoint and immediately removes them from the URL; bearer credentials are never stored in browser storage. Authorization state is owner-bound, expires after ten minutes, is single-use atomically, and carries an encrypted PKCE verifier. Tokens are encrypted in the database and excluded from account exports. GitHub permission failures stop imports rather than falling back to another user's or operator's token.

After connection, check **Use my connected GitHub account** when previewing a private URL. Review excerpts before import. Private source citations require access on GitHub; exporting a document can disclose its selected text, so the user should review employer/organization restrictions first. Disconnect deletes the stored credential and pending authorization; it deliberately preserves previously imported excerpts. Remove those sources or delete the account to erase them from active application storage. Revoking the App in GitHub settings provides provider-side revocation as well.

## Activation acceptance test

Use a disposable private repository installed on the App. Complete authorization, import a bounded file, review a statement and open its commit citation. Try a private repository not installed on the App and verify denial. Verify a second app account sees no connection or source. Disconnect/revoke and verify future imports fail, then remove the source and confirm retrieval invalidates it. Repeat after eight-hour expiry. Never use the operator's broad personal access token as a substitute for user consent.

Automated tests mock the provider and verify PKCE, owner binding, state expiry/replay rejection, encryption, disconnect, private-source labeling and account deletion. These tests do not constitute a live GitHub App consent test; the latter requires the owner's registered App and selected test repository.

References: https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-user-access-token-for-a-github-app
