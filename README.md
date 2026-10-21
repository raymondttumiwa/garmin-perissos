# Perissos
A personal Spirit, Soul & Body dashboard with private username/password accounts.

## Enable website accounts (required before deployment)

1. Back up the Supabase table. Run `supabase/garmin_daily_metrics.sql`, then
   `supabase/accounts.sql` in the Supabase SQL editor, in that order.
   The second script removes the old public policies and date-only unique key,
   adds an account/date unique key and private goal storage, and enforces account
   ownership using Supabase Auth. Run the account migration once.
   Do not rerun the legacy policy scripts or the single-user schema script afterward.
2. In Supabase Authentication, enable email/password signups and disable
   **Confirm email**. The website maps lowercase usernames to internal addresses
   like `raymond@accounts.perissos.invalid`. These are not mailboxes. Users enter
   only a username and password; there is no email verification or self-service
   email password recovery. The owner can reset passwords through Supabase's
   secure admin tooling. Configure a minimum password length of 10 or more.
   For a public launch, configure Supabase Auth rate limits and bot protection
   appropriate to your site; the current form does not integrate a CAPTCHA.
3. Fill in `site-config.js` with the project's HTTPS URL and publishable/anon key.
   These settings are public by design. Never publish the service-role key,
   Garmin credentials, or GitHub tokens. All visitors use the same Auth project;
   use a dedicated project for this website to keep its accounts separate.
4. Deploy `index.html`, `accounts.js`, and `site-config.js` together. Create your
   account, then open account settings (cloud icon) to copy its UUID.
5. Update GitHub Actions variable `SUPABASE_USER_ID` to that UUID. The importer
   now requires a real account UUID and upserts using `(user_id, date)`.

No live database or Auth settings are changed by editing this repository.
Missing project configuration leaves the site on the login/setup screen.

## Preserve your existing progress

Legacy database rows are kept by the migration, but no account can read them
until the owner assigns them. After creating your account, use the Supabase SQL
editor to inspect the old `user_id` values and replace only your own legacy ID:

```sql
-- Replace BOTH placeholders. Do this before importing fresh Garmin data for
-- the same dates, to avoid duplicate account/date conflicts.
update public.garmin_daily_metrics
set user_id = 'YOUR-AUTH-ACCOUNT-UUID'
where user_id = 'YOUR-OLD-PERSONAL-SYNC-KEY';
```

Legacy browser goals/check-ins are not automatically assigned to a new user:
that would expose the previous person's data on shared devices. Their original
localStorage keys remain untouched. Back them up before clearing browser data.
Custom goals can be transferred by the owner into `dashboard_goals` as a JSON
array, using the old `rooted_built_hybrid_goals_v3` value and the destination UUID.
Existing manual logs continue to reference the same goal IDs when goals are
transferred. New accounts get default goal definitions with empty progress.

## Data and account behavior

Goals and manual check-ins sync to Supabase with the signed-in user's access
token. Row-level security prevents another user from reading or writing those
rows, including requests made outside the website. The browser keeps a cache
under keys scoped to the account UUID; logout hides the dashboard and clears
in-memory progress. Browser caches remain on the device. Use a private browser
session on shared devices. Passwords are handled by Supabase Auth, never saved
in dashboard data or application-managed localStorage. The Auth SDK manages
its session in browser storage. Legacy cloud configuration is no longer used.

Goals save to the cloud on edits. Cloud-save failures display a notice and keep
local edits; automatic conflict resolution/offline retries are not implemented.
Current goal definitions are used when calculating historical completion.

## Garmin → Supabase

The included workflow is for **one configured Garmin account**. Other website
users can log manual habits immediately, but will not automatically get Garmin
imports. Each additional Garmin account needs its own secure server-side
credential/session setup, targeting that user's Auth UUID. Never share the
owner's Garmin credentials with website visitors.

Set Actions secrets `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, and either
`GARMIN_TOKEN_BASE64` (base64 JSON mapping OAuth filenames to token objects)
or `GARMIN_EMAIL` / `GARMIN_PASSWORD`. The service key stays in Actions only.
Set `SUPABASE_USER_ID` as described above and optionally `GARMIN_TIMEZONE`
(default `Asia/Shanghai`). Run the workflow, then click Sync Cloud to refresh
imported measurements. The website no longer stores a GitHub personal token or
triggers the owner's workflow from another user's session.

Garmin writes an `activities` JSON array, preserves browser-owned manual logs
and hydration, and omits absent measurements. Training readiness is imported
when available; it is not currently displayed by the dashboard.

## Verification

Run `python3 -m unittest discover -s tests` and `node --test tests/accounts.test.cjs`.
For live verification after configuring Supabase: create two accounts, record a
habit and a custom goal in account A, and verify B starts empty. Test both users
on the same date and verify A still has its data after switching back. Verify an
unauthenticated REST request cannot read rows, and an authenticated B request
cannot select/update A's rows. Live policy checks require the migrated database.

## Preview and local development

The public landing page is viewable without an account and displays sample-only
content. To preview it locally, from the project folder run
`python3 -m http.server 8000` and open `http://localhost:8000`. To test account
registration/login locally, first apply the Supabase migration and configure
Auth as above; use a unique test username. Stop the local server with Ctrl+C.

If GitHub Pages is configured to publish this repository's root branch, pushing
`index.html`, `accounts.js`, `site-config.js`, and the other changed files will
publish the landing page and login. The SQL migration is a separate manual step
in Supabase and is never applied by a Git push.
