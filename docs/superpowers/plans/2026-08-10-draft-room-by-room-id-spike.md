# Draft Room By Room ID — Research Spike Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Note on this plan's shape:** This is a research spike, not a software feature. Per the approved
> spec (`docs/superpowers/specs/2026-08-10-draft-room-by-id-spike-design.md`), there is no pytest
> suite — the "test" for each step is running the actual notebook cell against Yahoo's live API (or a
> live mock draft) and reading its output. Several steps require the user directly (creating
> credentials, joining a live mock draft, capturing a browser network request) — these are marked
> **[USER ACTION]** and cannot be completed by an agent alone. Because of that, **inline execution in
> this session is the recommended path**, not subagent-driven — the human needs to be present for
> Tasks 2–4.

**Goal:** Build a Jupyter notebook that proves whether Yahoo draft picks can be fetched given only a
draft room ID, for both real leagues and public Live Standard mock drafts, using NBA mock drafts as
the test surface.

**Architecture:** Single notebook, four sections run in the same kernel so state (OAuth session, game
key, whichever fetch method works) flows forward without re-authenticating. Section A tries the
documented Yahoo Fantasy Sports API; Section B falls back to a captured browser request if A doesn't
cover mock drafts; Section C normalizes whichever worked and validates it against a live, in-progress
draft.

**Tech Stack:** `yahoo_oauth` (OAuth2), `yahoo_fantasy_api` (Game/League/yhandler), `requests`
(fallback raw calls), Jupyter notebook, Python stdlib `time` for polling.

## Global Constraints

- Credentials live in `private.json` at the project root (`{"consumer_key": ..., "consumer_secret":
  ...}`); this file is already in `.gitignore` and must never be committed.
- NBA (basketball) Live Standard mock drafts are the test surface (originally NFL, while basketball was
  off-season).
- No `pytest` suite for this work; validation is reading notebook output cells directly.
- Error handling is diagnostic (print raw HTTP status/body on failure), not defensive.
- Deliverable is exploratory only — no module extraction / production code in this plan.

---

### Task 1: Notebook scaffold + authentication (Section 0)

**Files:**
- Create: `notebooks/draft_room_by_room_id.ipynb`
- (Manual, untracked) Create: `private.json`

**Interfaces:**
- Produces: an authenticated `sc` (`yahoo_oauth.OAuth2` instance) notebook variable, alive for the
  rest of the kernel session, that all later sections reuse.

- [ ] **Step 1 [USER ACTION]: Create `private.json`**

At the project root, create `private.json` with your Yahoo Developer app credentials:

```json
{
  "consumer_key": "<your client id>",
  "consumer_secret": "<your client secret>"
}
```

Confirm it's ignored: `git check-ignore -v private.json` should print a match against the
`.gitignore` `private.json` line.

- [ ] **Step 2: Create the notebook with a title + imports cell**

Use the NotebookEdit tool to create `notebooks/draft_room_by_room_id.ipynb`. First markdown cell:

```markdown
# Draft room data by room ID — research spike

Goal: given only a Yahoo draft room ID, fetch the picks made so far — for both real leagues and
public Live Standard mock drafts. NBA mock drafts are the test surface.
```

First code cell:

```python
import json
import time

import requests
from yahoo_oauth import OAuth2
from yahoo_fantasy_api import Game, League
```

- [ ] **Step 3: Add the auth cell**

```python
sc = OAuth2(None, None, from_file="private.json")
print("token valid:", sc.token_is_valid())
```

- [ ] **Step 4: Run both cells**

Run the imports cell, then the auth cell. The first run will drive you through the interactive OAuth2
flow (it prints an authorize URL — open it, approve, paste the verifier code back into the prompt).

Expected: `token valid: True` prints, and `private.json` on disk now also contains `access_token` /
`refresh_token` fields (confirms token persistence works).

- [ ] **Step 5: Commit**

```bash
git add notebooks/draft_room_by_room_id.ipynb
git status
```

Confirm `private.json` does NOT appear in `git status` output before committing.

```bash
git commit -m "Scaffold draft-room-by-room-id spike notebook with OAuth2 setup"
```

---

### Task 2: Section A — official API attempt

**Files:**
- Modify: `notebooks/draft_room_by_room_id.ipynb` (append cells)

**Interfaces:**
- Consumes: `sc` (authenticated `OAuth2` instance) from Task 1.
- Produces: `game_key` (str, e.g. `"449"`) notebook variable, reused in Section B/C. Produces a
  recorded finding — in a markdown cell — of whether any candidate `league_key` format returned real
  draft data for a mock draft room, which determines whether Task 3 is strictly necessary or purely
  confirmatory.

- [ ] **Step 1: Add a markdown cell**

```markdown
## Section A — official API attempt

Try the documented `league/{league_key}/draftresults` endpoint using candidate league_key formats
built from a room ID.
```

- [ ] **Step 2: Add the game_key resolution cell**

```python
gm = Game(sc, 'nba')
game_key = gm.game_id()
print("game_key:", game_key)
```

- [ ] **Step 3: Add the room ID + candidate fetch cell**

```python
# Paste the room ID from a Live Standard NBA mock draft URL, e.g.
# https://basketball.fantasysports.yahoo.com/nba/mockdraft/12345 -> room_id = "12345"
room_id = "REPLACE_ME"

candidate_league_keys = [
    f"{game_key}.l.{room_id}",
    f"nba.l.{room_id}",
    room_id,
]

for candidate in candidate_league_keys:
    print(f"--- trying league_key={candidate!r} ---")
    try:
        lg = League(sc, candidate)
        raw = lg.yhandler.get_draftresults_raw(candidate)
        print("SUCCESS, raw response:")
        print(raw)
    except Exception as e:
        print(f"FAILED: {type(e).__name__}: {e}")
```

- [ ] **Step 4 [USER ACTION]: Run against a real mock draft room**

Join (or open) a Yahoo Live Standard NBA mock draft in a browser, copy its room ID from the URL into
the `room_id` variable above, and run the cell.

Expected: either one candidate prints a `SUCCESS` with a real draft-results payload (proceed to Task
3 as confirmation-only, or skip straight to Task 4 using this method), or all candidates print
`FAILED` with the diagnostic exception (proceed to Task 3 as the primary path).

- [ ] **Step 5: Add a markdown cell recording the finding**

Write one sentence stating which candidate (if any) worked, and paste the key error message if none
did. This is the deliverable of this task — a definitive answer, not just code.

- [ ] **Step 6: Commit**

```bash
git add notebooks/draft_room_by_room_id.ipynb
git commit -m "Add Section A: official API attempt at draft-room-by-room-id spike"
```

---

### Task 3: Section B — captured-request fallback

**Files:**
- Modify: `notebooks/draft_room_by_room_id.ipynb` (append cells)

**Interfaces:**
- Consumes: `sc` from Task 1 (for its `access_token`, in case the captured request reuses
  OAuth-bearer auth rather than session cookies).
- Produces: a recorded finding of whether the captured request returns draft-pick data, and (if so)
  the working `requests.get(...)` shape reused by Task 4.

- [ ] **Step 1: Add a markdown cell with capture instructions**

```markdown
## Section B — captured browser request (fallback)

If Section A didn't return mock draft data, capture the request Yahoo's own draft board uses:

1. Join a Live Standard NBA mock draft in a browser.
2. Open DevTools → Network, filter to Fetch/XHR.
3. Wait for a pick to happen (or make one), and find the request that carries new pick data in its
   response.
4. Right-click it → Copy → Copy as cURL, and use that to fill in the constants in the next cell.
```

- [ ] **Step 2: Add the captured-request cell**

```python
CAPTURED_URL = "REPLACE_ME"
CAPTURED_HEADERS = {
    # copy relevant headers from the captured request, e.g. "cookie", "authorization"
}
CAPTURED_PARAMS = {
    # copy any query params from the captured request
}

resp = requests.get(CAPTURED_URL, headers=CAPTURED_HEADERS, params=CAPTURED_PARAMS)
print("status:", resp.status_code)
print(resp.text[:2000])
```

- [ ] **Step 3 [USER ACTION]: Fill in the captured request and run**

Replace `CAPTURED_URL` / `CAPTURED_HEADERS` / `CAPTURED_PARAMS` with values copied from DevTools, and
run the cell.

Expected: `status: 200` and a response body containing recognizable pick data (player names, team
slots, pick order). If it 401s/403s, note in the next cell which header was likely missing
(commonly a session cookie that isn't reproducible from a plain OAuth token — record this as a
finding either way).

- [ ] **Step 4: Add a markdown cell recording the finding**

State whether the captured request returned usable pick data, and if so, which header(s) were
load-bearing (so Task 4 knows what must be present on every call, e.g. does the cookie expire).

- [ ] **Step 5: Commit**

```bash
git add notebooks/draft_room_by_room_id.ipynb
git commit -m "Add Section B: captured-request fallback at draft-room-by-room-id spike"
```

---

### Task 4: Section C — normalize + live-poll validation

**Files:**
- Modify: `notebooks/draft_room_by_room_id.ipynb` (append cells)

**Interfaces:**
- Consumes: whichever of Task 2's `lg.yhandler.get_draftresults_raw(...)` call or Task 3's
  `requests.get(CAPTURED_URL, ...)` call succeeded, plus the `raw`/`resp` shape observed there.
- Produces: `get_current_picks() -> list[dict]`, each dict shaped
  `{"round": int, "pick": int, "team": str, "player": str}`. This is the spike's terminal
  deliverable — proof the two success criteria from the spec are met.

- [ ] **Step 1: Add a markdown cell**

```markdown
## Section C — normalize + live-poll validation

Wrap whichever method worked in one function returning a normalized pick list, then confirm it picks
up new data while a draft is actively running.
```

- [ ] **Step 2: Add the normalizing function cell**

Write this using the actual field names observed in Task 2 or Task 3's raw output (the payload's real
structure won't be known until those tasks run — inspect the printed `raw`/`resp.json()` from
whichever succeeded and map its fields here):

```python
def get_current_picks():
    """Fetch and normalize current draft picks into [{round, pick, team, player}, ...]."""
    # Implementation depends on which of Section A / Section B succeeded.
    # Pull the exact field names from that section's printed raw output.
    raise NotImplementedError("fill in using the working method's raw response shape")
```

- [ ] **Step 3: Implement `get_current_picks()` against the working method's real response shape**

Replace the `raise NotImplementedError` body with real parsing code once you can see the actual
raw payload from whichever of Task 2/3 succeeded (e.g. iterating an XML-derived dict from
`yhandler`, or a JSON body from the captured request). Run the cell.

Expected: no exception on definition.

- [ ] **Step 4: Add a single-call check cell**

```python
picks = get_current_picks()
print(f"{len(picks)} picks so far")
for p in picks[:5]:
    print(p)
```

Run it. Expected: a non-empty list of dicts each with `round`, `pick`, `team`, `player` keys,
matching picks you can see on the actual mock draft board.

- [ ] **Step 5 [USER ACTION]: Add and run the live-poll cell during an active draft**

```python
seen_picks = 0
for _ in range(6):  # ~90s at 15s intervals
    picks = get_current_picks()
    if len(picks) > seen_picks:
        print(f"{len(picks) - seen_picks} new pick(s):")
        for p in picks[seen_picks:]:
            print(p)
        seen_picks = len(picks)
    else:
        print("no new picks yet")
    time.sleep(15)
```

While a Live Standard NBA mock draft is actively picking, run this cell. Expected: at least one
iteration prints new picks that weren't present in an earlier iteration, confirming the fetch reflects
live draft state rather than a cached/static snapshot.

- [ ] **Step 6: Add a markdown cell summarizing the spike's outcome**

State plainly: which method (A or B) works, whether it works for mock drafts specifically, and
whether live polling confirmed fresh data. This closes out both success criteria from the spec.

- [ ] **Step 7: Commit**

```bash
git add notebooks/draft_room_by_room_id.ipynb
git commit -m "Add Section C: normalize picks and validate against a live mock draft"
```

---

## Self-Review Notes

- **Spec coverage:** Credentials/setup → Task 1. Approach A → Task 2. Approach B fallback → Task 3.
  Normalize + live-poll success criteria → Task 4. Diagnostic (non-defensive) error handling → Task
  2 Step 3's try/except print, Task 3 Step 4. Out-of-scope items (module extraction, auth
  hardening) are not present in any task, consistent with the spec excluding them.
- **Placeholder scan:** Task 4's `get_current_picks()` body is deliberately left as
  `NotImplementedError` in Step 2 because the real payload shape is genuinely unknown until Tasks 2–3
  run against live data — this is called out explicitly as depending on runtime discovery, not left
  vague. Step 3 is the concrete follow-through once that shape is known.
- **Type consistency:** `sc` (Task 1) is reused by name in Tasks 2 and 3. `game_key` (Task 2) is
  defined once and only referenced, not redefined, in later candidate-key construction. The
  `{round, pick, team, player}` dict shape is introduced once (Task 4) and used consistently in the
  live-poll cell.
