# Ling Hackathon Mobile Apps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development for implementation. Tasks use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the Ling hackathon backend plus two separate installable mobile-first PWAs: the child app "灵灵的窗口" and the parent app "训练师手册".

**Architecture:** Keep the existing FastAPI/SQLite monolith and realtime doll console. Add an experience projection layer with four new tables and a deterministic timestamp-driven mock media provider. Serve the child and parent apps from separate directories and routes so their permissions, navigation, styling, and service workers remain isolated.

**Tech Stack:** Python 3.12, FastAPI, SQLite, pytest, vanilla ES modules, CSS, Web App Manifest, Service Worker, Node built-in tests, local MP4/PNG assets.

## Global Constraints

- This is a hackathon demo: no production ACL, queue, CMS, object storage, notification delivery, real Seedance/Veo call, or full account-erasure implementation.
- Existing L1-L4 memory, SRS, realtime providers, and private Canon remain the fact source.
- The global base world is shared and versioned; variants may change framing but not semantic facts.
- The private story advances only from meaningful child interaction. Offline life display comes from the global base world.
- Personal moments are limited to 0-3 per child local day. Three is a ceiling, not a target.
- Published moment semantics and `published_asset_id` are immutable during ordinary product operation.
- Keepsakes are story objects. Pocket membership is a mutable projection stored as `collected=true|false`; uncollect never deletes rows.
- No per-memory deletion exists in either mobile app. Account closure remains a separate future data-rights flow.
- Both apps are separate mobile apps implemented as installable PWAs. Child route: `/child`. Parent route: `/parent`.
- Child app is read-only against memory facts; its only write is pocket collection state.
- Parent APIs are allowlisted projections and never return transcripts, quotes, prompts, session IDs, provider/job details, private Canon, raw SRS counters, or deletion targets.
- Mobile acceptance sizes are 320x568 and 390x844. Desktop verification is 1440x900. Body text is at least 16px, secondary text at least 12px, touch targets at least 44px.
- All new behavior follows red-green-refactor. Frontend implementers must not edit `backend/**`; backend implementer must not edit `frontend/**`.

## Shared API Contract

`GET /api/child/world/now`

```json
{
  "mode": "day",
  "timezone": "Asia/Shanghai",
  "next_transition_at": "2026-07-11T18:00:00+08:00",
  "doll": {"id": "lingling", "name": "灵灵", "known_days": 12},
  "event": {
    "event_id": "hill-wind",
    "event_version": 1,
    "variant_id": "hill-wind-a",
    "title": "去山坡等风",
    "summary": "灵灵带着积木风筝去等今天第一阵风。",
    "media": {"kind": "video", "src": "/demo-media/hill-wind-a.mp4", "poster": "/demo-media/hill-wind-a.png", "mime_type": "video/mp4", "width": 720, "height": 900, "duration_ms": 4000, "alt": "灵灵在山坡上等风"}
  },
  "sleep_message": null,
  "memory_summary": {"moments": 8, "keepsakes": 3}
}
```

`GET /api/child/feed`

```json
{
  "items": [{"id": "public:hill-wind:1", "kind": "public", "status": "published", "title": "去山坡等风", "summary": "...", "occurred_at": "...", "media": {}}],
  "pending": [{"id": 9, "kind": "personal", "status": "rendering", "title": "我学会了新词", "poll_after_ms": 700}]
}
```

`GET /api/moments/{id}` returns `{id, kind, status}` and, when published, `{title, story, occurred_at, media, keepsake}`. It never exposes provider responses.

`GET /api/pocket` returns `{items:[{id,name,description,appearance,image_url,source_moment_id,collected_at}]}`.

`PUT /api/pocket/{keepsake_id}` accepts `{"collected": true}` or `{"collected": false}` and returns the final state.

Parent endpoints are `/api/parent/today`, `/api/parent/growth?period=week`, `/api/parent/memory?cursor=&limit=20`, and `/api/parent/guardian`. Their exact fields follow Task 2 tests and contain display-ready values only.

---

### Task 1: Backend Schema And Deterministic Media Provider

**Files:**
- Modify: `backend/db.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `backend/media.py`
- Create: `backend/demo/base_world.json`
- Create: `backend/demo/mock_assets.json`
- Create: `backend/demo_media/*.mp4`
- Create: `backend/demo_media/*.png`
- Create: `tests/conftest.py`
- Create: `tests/test_media.py`

**Interfaces:**
- Produces: `db.transaction(immediate=True)`, `media.load_manifests()`, `media.select_world_event(doll_id, now, timezone)`, and `MockMediaProvider.submit/poll/result`.
- The provider persists time in `generation_jobs.ready_at`; it never uses in-process timers.

- [ ] **Step 1: Install test tooling only**

Run: `uv add --dev pytest`
Expected: `pyproject.toml` and `uv.lock` contain pytest, with no production implementation changes.

- [ ] **Step 2: Write failing schema and media tests**

Tests must assert four tables exist, uniqueness constraints reject duplicates, malformed manifests fail, missing media fail, and identical `{doll_id,event_id,event_version}` selects the same variant.

```python
def test_variant_assignment_is_stable(media_catalog):
    first = media_catalog.select_variant("ling-1", "hill-wind", 1)
    second = media_catalog.select_variant("ling-1", "hill-wind", 1)
    assert first["asset_id"] == second["asset_id"]
```

- [ ] **Step 3: Run the focused tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_media.py -q`
Expected: failure because `backend.media` and the four tables do not exist.

- [ ] **Step 4: Add the four tables and transaction helper**

Implement `moments`, `generation_jobs`, `keepsakes`, and `pocket_entries` exactly as defined in the approved architecture. Add a context manager using `BEGIN IMMEDIATE`, commit on success, and rollback on exception.

- [ ] **Step 5: Implement manifest validation and mock provider**

Validate schema versions, stable IDs, semantic versions, MIME, dimensions, checksums, and local paths. `poll()` derives `queued`, `running`, or `succeeded` from persisted timestamps. `result()` raises typed `not_ready`, `generation_failed`, and `not_found` errors.

- [ ] **Step 6: Add five local media/poster pairs**

Provide at least two global variants and four meaningful event mappings across `word_taught`, `canon_choice`, `story_beat`, and `growth_change`. Assets must be local, playable, portrait-oriented, and valid without network access.

- [ ] **Step 7: Verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_media.py -q`
Expected: all media tests pass.

### Task 2: Experience State Machine And Projection APIs

**Files:**
- Modify: `backend/app.py`
- Modify: `backend/seed.py`
- Create: `backend/experience.py`
- Create: `tests/test_experience.py`
- Create: `tests/test_projections.py`
- Create: `tests/test_app_routes.py`

**Interfaces:**
- Consumes: Task 1 database and provider interfaces.
- Produces: all shared child/parent APIs, `/demo-media`, `/child`, `/parent`, and `experience.settle_candidate()`.

- [ ] **Step 1: Write failing moment state tests**

Cover insignificant candidates, exact asset matching, idempotent settlement, atomic daily quota, failure releasing quota, restart-safe polling, maximum two attempts, immutable publication, and feed filtering.

```python
def test_duplicate_settlement_returns_same_moment(experience):
    a = experience.settle_candidate(1, "session", "42", "canon_choice", {"choice": "橡果味"})
    b = experience.settle_candidate(1, "session", "42", "canon_choice", {"choice": "橡果味"})
    assert a["moment_id"] == b["moment_id"]
```

- [ ] **Step 2: Verify the tests fail for missing behavior**

Run: `.venv/bin/python -m pytest tests/test_experience.py -q`
Expected: failure because `backend.experience` does not exist.

- [ ] **Step 3: Implement candidate settlement and publication**

Run safety/meaning/asset checks before quota reservation. In one immediate transaction count `rendering + published`, insert `moment.rendering`, and insert the first queued job. Repeated idempotency keys return the existing row. Polling a ready job atomically writes `published_asset_id`, `published_at`, and `moment.published`.

- [ ] **Step 4: Write failing projection allowlist tests**

Assert child responses contain no mastery or parent insight. Assert parent responses recursively contain none of `transcript`, `quote`, `session_id`, `prompt`, `provider`, `job`, `successes`, `exposures`, `due_date`, `private_canon`, or deletion target URLs.

- [ ] **Step 5: Implement child and parent projections**

Create display-ready dictionaries for the contract above. Parent `today` exposes time/topic/new-word metrics plus non-diagnostic mood text. `growth` exposes three display levels and growth moments. `memory` merges safe diary/fact/moment summaries without raw records. `guardian` returns read-only demo policy values and fixed AI identity disclosure.

- [ ] **Step 6: Add routes and seed data**

Mount `/demo-media`, serve `frontend/child/index.html` at `/child` and `frontend/parent/index.html` at `/parent`, extend `POST /api/session/end` with idempotent settlement, and add `POST /api/admin/demo-moment` for rehearsed event keys. Seed published moments, one rendering moment, keepsakes, and pocket state without resetting unrelated memory during ordinary startup.

- [ ] **Step 7: Verify backend GREEN**

Run: `.venv/bin/python -m pytest tests/test_experience.py tests/test_projections.py tests/test_app_routes.py -q`
Expected: all tests pass and no network is used.

### Task 3: Child Mobile PWA

**Files:**
- Create: `frontend/child/index.html`
- Create: `frontend/child/styles.css`
- Create: `frontend/child/api.mjs`
- Create: `frontend/child/model.mjs`
- Create: `frontend/child/app.mjs`
- Create: `frontend/child/manifest.webmanifest`
- Create: `frontend/child/sw.js`
- Create: `frontend/child/icon-192.png`
- Create: `frontend/child/icon-512.png`
- Create: `frontend/child/tests/model.test.mjs`

**Interfaces:**
- Consumes only the shared child APIs. Must not request `/api/facts`, `/api/diary`, `/api/mastery`, `/api/report`, or provider endpoints.
- Produces a three-tab mobile app: 现在, 奇遇, 口袋.

- [ ] **Step 1: Write failing view-model tests**

Test day/night/sleeping mode, public/personal labels, pending poll discovery, published replacement, failed removal, and optimistic pocket rollback.

```javascript
test('sleeping mode uses the world-state message', () => {
  assert.equal(worldView({mode: 'sleeping', sleep_message: '灵灵要睡了'}).headline, '灵灵要睡了');
});
```

- [ ] **Step 2: Verify RED**

Run: `node --test frontend/child/tests/*.test.mjs`
Expected: failure because child modules do not exist.

- [ ] **Step 3: Build the app shell and day/night world**

Use the approved block-toy day palette and night-light indigo/gold palette. World mode is server-authoritative. Do not add chat, mastery, parent insight, admin controls, provider labels, or explanatory marketing copy.

- [ ] **Step 4: Build feed, detail, generation, and pocket flows**

Render semantic `article` lists, text labels for public/personal, local videos with poster and error state, cancellable polling with `aria-live`, focused detail navigation, idempotent collect/uncollect with rollback, and empty/error/retry states.

- [ ] **Step 5: Add PWA installation and accessibility behavior**

Add standalone manifest, icons, safe-area bottom navigation, service worker shell caching, visible focus, 44px targets, reduced motion, 200% text support, and no horizontal overflow at 320px.

- [ ] **Step 6: Verify GREEN**

Run: `node --test frontend/child/tests/*.test.mjs`
Expected: all child tests pass.

### Task 4: Parent Mobile PWA

**Files:**
- Create: `frontend/parent/index.html`
- Create: `frontend/parent/styles.css`
- Create: `frontend/parent/api.mjs`
- Create: `frontend/parent/model.mjs`
- Create: `frontend/parent/app.mjs`
- Create: `frontend/parent/manifest.webmanifest`
- Create: `frontend/parent/sw.js`
- Create: `frontend/parent/icon-192.png`
- Create: `frontend/parent/icon-512.png`
- Create: `frontend/parent/tests/model.test.mjs`

**Interfaces:**
- Consumes only `/api/parent/*` endpoints.
- Produces four mobile tabs: 今日, 成长, 记忆, 守护.

- [ ] **Step 1: Write failing projection-model tests**

Test metric formatting, mandatory mood disclaimer, three mastery levels, old-to-new fact display, red-line explanation, data-rights dialog copy, guardian policy summaries, and recursive forbidden-field rejection.

- [ ] **Step 2: Verify RED**

Run: `node --test frontend/parent/tests/*.test.mjs`
Expected: failure because parent modules do not exist.

- [ ] **Step 3: Build the mobile shell and four views**

Match the approved trainer-manual language. Use candle gold only for meaningful attention. Implement per-tab lazy loading with independent loading, empty, error, and retry states. Keep guardian settings read-only unless a write API exists.

- [ ] **Step 4: Implement accessible navigation and data-rights dialog**

Use a real tablist with arrow-key navigation and `aria-selected`. The dialog explains that red lines suppress future recall and account closure is the destructive flow; it offers no fake submit action and no per-item deletion.

- [ ] **Step 5: Add installable PWA behavior**

Add standalone manifest, icons, safe-area navigation, service worker shell caching, 320px single-column layout, visible focus, 44px targets, reduced motion, and text summaries for charts/status colors.

- [ ] **Step 6: Verify GREEN**

Run: `node --test frontend/parent/tests/*.test.mjs`
Expected: all parent tests pass.

### Task 5: Integration, Browser Verification, And Delivery

**Files:**
- Modify: `README.md`
- Create: `tests/test_static_apps.py`
- Modify only as required by verified integration findings in Task 1-4 files.

**Interfaces:**
- Consumes all prior tasks.
- Produces a fully offline-rehearsable demo and final verification evidence.

- [ ] **Step 1: Add failing static contract tests**

Assert `/child` and `/parent` return HTML, manifests and service workers return correct content types, every manifest icon and mock media URL exists, and neither app source contains forbidden legacy API paths.

- [ ] **Step 2: Run all automated tests**

Run:

```bash
.venv/bin/python -m pytest -q
node --test frontend/child/tests/*.test.mjs frontend/parent/tests/*.test.mjs
```

Expected: all tests pass with zero failures.

- [ ] **Step 3: Run the server and exercise the offline demo flow**

Start on port 8888, reseed, trigger `canon_choice`, call session settlement twice, verify one rendering moment, poll 2-4 seconds, verify feed publication, collect keepsake, refresh, and verify pocket persistence.

- [ ] **Step 4: Browser-verify child app**

Inspect 320x568, 390x844, 768x1024, and 1440x900. Verify nonblank local video/poster, day/night/sleeping states, mixed feed, rendering success/failure, detail focus, pocket toggling, safe-area navigation, 200% zoom, keyboard focus, reduced motion, console errors, and zero horizontal overflow.

- [ ] **Step 5: Browser-verify parent app**

Inspect 390x844 and 1440x900. Verify all four tabs, lazy loading, retry, mood disclaimer, growth text summary, old/new facts, red-line semantics, rights dialog focus/escape, read-only guardian settings, no deletion actions, no forbidden API requests, and zero horizontal overflow.

- [ ] **Step 6: Document the demo and complete delivery**

Update README with `/`, `/child`, `/parent`, `/design`, one command to run, test commands, the mock generation flow, and explicit deferred production work. Run a final diff review, commit all implementation files, and leave the server state requested by the user.
