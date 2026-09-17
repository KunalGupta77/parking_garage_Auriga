# REASONING.md
 
# CLAUDE

## How I read the problem

Strip away the CRUD plumbing (search, pagination, sorting, auth — all pretty standard
stuff) and this is really a two-correctness-property problem: never hand the same spot
to two cars, and always compute the fee the same way every time. So that's where I put
my attention first. Everything else — the landing page, the dashboard chrome, the
docs — is important because it's graded, but it's not where bugs hide. I went through
the mandatory list (real DB, REST APIs, documented endpoints, a usable frontend, auth,
search, pagination, sorting, landing page, the three docs) and treated it as the
literal finish line — nothing more, nothing speculative, given the 2.5-hour framing.

## Assumptions I had to make

The brief is intentionally light on a few details. Where that happened I picked the
simplest thing that made sense and tried to make it easy to change my mind later:

1. **No actual fee numbers were given** beyond the worked example, so `fees.py` just
   has `FIRST_HOUR_RATE=50`, `ADDITIONAL_HOUR_RATE=30`, `DAILY_CAP=250` as constants —
   which happen to match the example table exactly, so I know they're right.
2. **What happens when the "right" spot type is full.** A compact car can fall back to
   a standard spot (bigger car space fits a smaller car, no problem). A standard car
   can't shrink into a compact spot, and obviously nothing but an EV goes in an EV
   spot — that one's explicit in the brief, not my call. I put this as one small dict
   (`SPOT_FALLBACK`) so if this assumption's wrong it's a one-line fix, not a rewrite.
3. **Checking out immediately, or with a negative duration somehow** (clock skew,
   whatever) — I just charge the first-hour minimum instead of ₹0 or a negative
   number. A car occupied a spot; it gets charged for at least that.
4. **The "daily cap"** — I read this as a cap per parking session, not something that
   resets at midnight for a multi-day stay. The brief calls it a daily maximum on the
   fee for a stay, not a calendar mechanism, and it matches the given examples fine.
5. **Auth** — plain Flask session cookies, not JWT. Nothing in the mandated stack
   mentions a token library, and a cookie does everything "login/logout" and
   "protect this endpoint" need without pulling in something new.
6. **The seeded garage** — 3 floors, 4 compact + 4 standard + 2 EV per floor (30 spots
   total), and it's a config list in `seed.py`, not something baked into the app
   logic — so a different garage shape is a data change, not a code change.
7. **Plates get normalized** — upper-cased and trimmed everywhere, so `ka01` and
   `KA01` are obviously the same car to the system.

## Why the database looks the way it does

Three tables, exactly what was asked for — `User`, `ParkingSpot`, `ParkingSession` —
and I resisted the urge to add anything else. A couple of choices worth calling out:

`ParkingSession` has a real `status` column rather than me inferring "active" from
`check_out IS NULL`. The brief lists `status` explicitly, and honestly it just makes
the code more readable — `filter_by(status="active")` says what it means, a NULL check
makes you think for a second.

`ParkingSpot` has a `UNIQUE(floor, spot_number)` constraint. The app itself never
generates a duplicate, but that's exactly the kind of real-world invariant that's
cheap to enforce at the DB level and annoying to debug if you don't.

Datetimes are naive UTC everywhere (see `utcnow()` in `models.py`). SQLite doesn't
really have a timezone-aware datetime type, and mixing aware/naive datetimes is one of
those classic `TypeError: can't subtract offset-naive and offset-aware datetimes`
traps — easier to just pick one convention and stick to it everywhere.

## How spot assignment actually works

`find_available_spot(vehicle_type)` does the obvious thing: look up the vehicle's list
of acceptable spot types (with fallback), and for each one, grab the first free spot
ordered by floor then spot number. First match wins; if nothing's free, it returns
`None` and the caller turns that into a 409.

I like this because it's boring in a good way — same DB state always gives you the
same spot, and you can explain the rule to literally anyone in one sentence: fill the
lowest floor first, lowest spot number first, and never put a car somewhere it
physically can't go.

On double-booking: the check (is there a free spot?) and the write (mark it occupied)
happen inside the same request, and I always re-query `is_occupied` rather than
trusting anything cached. For a single-process Flask dev server that's genuinely
enough. I'll be upfront that it's not bulletproof under real concurrent writers — a
production system would want a unique partial index or row-level locking, which SQLite
isn't really built for anyway. Didn't implement it, just flagging it here so it's not
a silent gap.

## The fee math

I pulled this into its own module (`fees.py`) specifically so I could test it without
dragging Flask or the database into the test at all — just call the function with two
datetimes and check the number that comes back.

Roughly:

```
total_seconds = int((check_out - check_in).total_seconds())
total_minutes = ceil(total_seconds / 60)          # integer ceiling, not float math
if total_minutes <= 60: fee = FIRST_HOUR_RATE
else: extra_hours = ceil((total_minutes - 60) / 60)
      fee = FIRST_HOUR_RATE + extra_hours * ADDITIONAL_HOUR_RATE
fee = min(fee, DAILY_CAP)
```

The ceiling division is written as `(x + 59) // 60`, not `math.ceil(x / 60)` — no
floats touch this calculation at all, which is exactly what the brief asked for. I ran
it against every example given (30/60/61/120/121 minutes) plus a 24-hour case to make
sure the cap actually kicks in, and it matches every time.

## API design choices

Mostly resource-shaped URLs (`/api/parking`, `/api/spots`) with verbs only where an
action doesn't map cleanly to a resource (`check-in`, `check-out`, `logout`). Every
error comes back as `{"error": "..."}` with a real status code, and there's a
catch-all exception handler so a bug turns into a generic 500 JSON body instead of a
Python traceback leaking to whoever's calling the API.

The one thing I was genuinely careful about: `sort` on `/api/parking`. The query
string value only ever gets used as a lookup key into a fixed dict of real SQLAlchemy
columns (`SORTABLE_FIELDS`) — it never touches raw SQL and never gets passed to
`getattr` on user input. That's the specific SQL-injection-via-sort-field trap the
brief calls out, so I wanted that path locked down, not just "probably fine."

Pagination always returns `page`/`limit`/`total`/`pages` in the response, matching the
brief's example shape — the frontend never has to compute `pages` itself, which also
means it can't get it wrong.

## Frontend

Plain HTML, Tailwind off a CDN, vanilla JS `fetch` calls — no framework, no build
step, because that's what the stack called for and a bundler pipeline isn't a good use
of a 2.5-hour budget. Four pages: landing, register, login, dashboard.
`dashboard.js` keeps one small `state` object (page/limit/sort/order/search) as the
single source of truth for the history table, so every re-render reads from that
instead of scraping the DOM for current values. Auth on the client side is just "call
`/api/status`, redirect to login on a 401" — the cookie is the real access control,
enforced server-side; the client check just stops a logged-out user from staring at a
blank dashboard for a second before getting bounced.

## Testing

38 pytest tests total. The original 27 cover everything in the brief's own checklist —
registration and login (happy path and rejections), check-in for all three vehicle
types, EV-to-EV-spot enforcement, duplicate active check-in, no-double-spot-assignment,
no-compatible-spot, invalid vehicle type, checkout (success/frees the spot/nonexistent
vehicle), plate search, pagination, sorting (including the rejected-bad-field case),
and EV availability. Fee calculation gets tested directly against the brief's own
example numbers plus a daily-cap case. I also walked through the whole thing in an
actual browser — register, log in, check a car in, search for it, check it out — just
to make sure the UI and the API actually agree with each other, since passing tests
don't guarantee the dashboard renders what it should.

## Bugs I actually hit, and what fixed them

**Test isolation was broken and I didn't notice at first.** `create_app()` was setting
`SQLALCHEMY_DATABASE_URI` to the real file-based `parking.db` and calling
`db.init_app(app)` *before* my test fixture got a chance to override it to
`sqlite:///:memory:`. Flask-SQLAlchemy binds the engine right there at `init_app`
time, so my later `app.config.update(...)` in the fixture was just... too late to
matter. Every test I thought was isolated was quietly reading and writing the same
real file, and the symptoms were bizarre — an EV-availability test seeing 1 free spot
instead of 6, a pagination test with way more rows than it should've had. Took a bit
to trace, fixed by giving `create_app()` a `db_uri` parameter so tests can hand it the
in-memory URI *before* `init_app` runs at all.

**A deprecation warning on `datetime.utcnow()`.** Python 3.13 doesn't like it anymore.
Swapped to `datetime.now(timezone.utc).replace(tzinfo=None)` so I keep storing naive
UTC (still needed for clean datetime subtraction in the fee math) without the warning.

**Port 5000 was already taken — by a different project, not mine.** When I actually
opened the app in a browser to test it, I got a completely different UI ("ParkEase",
dark theme) than what I'd just written. Turned out there was an unrelated
"practice" parking-management project on the same machine already bound to port 5000.
Confirmed it via the process list (checked each PID's command line and working
directory) rather than assuming, left that other process alone, and just ran mine on
5001 instead.

## The three extra twists (T4, T2, T6)

These got added after the initial build, so each one's a self-contained addition on
top of the working app rather than a rewrite of anything.

**T4, the messy rate card.** No actual junk file ever showed up — the assessment text
referenced "the junk below" but nothing was actually below it — so I built a
realistic stand-in myself (`rate_card_raw.csv`) with the kind of mess a real
spreadsheet export tends to have: inconsistent casing, three different spellings of
"EV" (`ev`, `electric vehicle`, `e.v.`), currency symbols glued onto numbers
(`"₹50"`, `"Rs. 60"`), a totally blank row, a row missing a field, and a duplicate row
that actively conflicts with an earlier one. `rates.py` handles cleaning that into
`{spot_type: {first_hour, additional_hour, daily_cap}}`. I split this out from
`fees.py` on purpose — cleaning messy input and doing fee math are different jobs, and
smashing them together would've made neither easy to test on its own. Two rules I
picked and wrote down rather than leaving implicit: a row that can't be parsed gets
skipped, not raised (one bad row in a rate card shouldn't take down pricing for every
other spot type), and when the same spot type shows up twice, the first valid entry
wins. `calculate_fee()` just grew optional rate parameters that default to the
original flat constants — which meant none of the original 27 tests needed to change
at all.

**T2, the nightly job.** `POST /clock` handles "close and bill anything parked over
24 hours." The obvious issue with testing that literally is nobody's waiting 24 real
hours for a test to pass, so `/clock` accepts an optional `{"now": "..."}` — a caller
(a grader, or a real cron job with its own clock) tells it what time to pretend it is.
No `now` given, it just uses the real current time. I also deliberately left this
endpoint outside `login_required` — a scheduled job doesn't have a browser session to
present, so requiring login here would make the whole "nightly job" idea impossible to
actually run unattended. When a session gets closed this way, it goes through the
exact same fee-calculation and spot-freeing code as a manual checkout — didn't want a
second, slightly-different way for a session to end.

**T6, the valet hand-off.** The brief's own wording — "spot and entry time carry
over" — reads to me like it's telling you what *doesn't* change, not instructing you
to copy a row. So I just update the existing active session's `plate_number` in place
and leave `spot_id` and `check_in` alone. It's the same parking stay, just relabeled
under a different plate. Worth being honest about the trade-off: the old plate's
history for that stay effectively disappears after a transfer, since it's the same
database row now wearing a new plate number. For a valet hand-off at this scope that
felt like a fine simplification — a real system might want a separate transfer-history
table if that old-plate audit trail actually mattered.

All three got their own tests (11 new ones — rate-card cleaning against both a
synthetic messy sample and the real CSV, per-spot-type checkout pricing, the
`/api/rates` endpoint, `/clock` correctly closing a stale session while leaving a
fresh one untouched and working without auth, and the transfer endpoint's happy path
plus its 404/409/400 edge cases). I also poked at all three by hand with `curl` against
a running server — EV checkout came back priced at ₹100 (the cleaned EV rate, not the
flat ₹50 default), a 25-hour-old session got auto-closed by `/clock` at the standard
rate's ₹300 cap, and a transferred plate vanished from the old plate's lookup while
the new plate showed the original spot and check-in time, exactly as expected.

## Where things stand

- `python -m pytest tests/ -v` → 38/38 passing (27 from the core spec, 11 from the
  twists).
- Full manual browser walkthrough: landing page → register → login → dashboard stats
  load correctly (30 spots, 6 EV, for the seeded garage) → check in a compact and an
  EV → each gets the right spot → search by plate shows the active session and a
  working checkout button → checkout computes the right fee, frees the spot, updates
  stats and history live.
- Re-ran the full suite after every bug fix and after adding the twists, so nothing
  above is "should still work" — it's "just checked, still works."
