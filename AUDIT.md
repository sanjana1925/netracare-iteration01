# Iteration 1 audit: the Checker's report

Checked against `Iteration1/NetraCare-Iteration-1.html` and `Iteration1/data-pack-01`. Status as of this audit: **every item below is present and
verified**, except the items in "Not verified" at the end.

## What the audit FOUND missing, and what was done
| # | Finding | Action | Evidence |
|---|---|---|---|
| 1 | Stretch goal **Staff approval queue** was not in Iteration 1 | Built: `approvals` table, request saved on a late cancel/reschedule, Staff **Approve** (carried out as Staff) / **Reject**, status shown to the patient | `tests/test_stretch_goals.py` (6 tests) |
| 2 | Stretch goal **Staff add holidays / edit a doctor's weekly schedule** was missing | Built: `POST/DELETE /holidays`, `PUT /schedule`, **Clinic settings** panel. Changes apply at once; a change that would strand a booked appointment is refused | 5 tests + Docker end-to-end |
| 3 | Stretch goal **week view calendar** per doctor was missing | Built: `GET /calendar`, **Week view** for Staff (any doctor) and Doctor (own week), previous/next week, holidays, OPD/SX/off sessions | 2 tests + Docker end-to-end |
| 4 | Stretch goal **Docker Compose** was missing | Built and **run**: `docker-compose.yml`, backend and frontend Dockerfiles, nginx proxy, persistent volume, health check | 35 live checks against the running containers |
| 5 | Empty files: `backend/app/__init__.py`, `backend/tests/__init__.py` (and their docstring-only replacements) | **Removed.** Tests now use `tests/helpers.py` and `pytest.ini`; `app` works as a namespace package | 0 empty files, 0 `__init__.py`; 91 tests pass |
| 6 | Test-only invented values (`9111111111`, `9222222222`, `9333333333`) | Replaced by one value: `9000000099`, which cannot come from the pack because requirement R3 says a *new* mobile creates a new patient | `tests/test_handout_checklist.py` |
| 7 | No test mapped to the handout's own checklist | Added `tests/test_handout_checklist.py`: R1-R6, section 03 roles, all 13 section 09 rows, final bullets | 26 tests |
| 8 | A leftover demo database with a test booking of mine | Deleted; no `.db` file is on disk; the Docker volume was reset | 0 appointments on a fresh start |

## Bug found by the user after the audit, and fixed
| Symptom | Cause | Fix | Proof |
|---|---|---|---|
| A patient booked successfully, but "My appointments" said "No appointments to show" and booking again was refused ("You already have an upcoming Glaucoma appointment") | `sqlite3.ProgrammingError: SQLite objects created in a thread can only be used in that same thread`. FastAPI creates the per-request connection in one worker thread and may run the endpoint in another, so the list refresh right after a booking sometimes returned HTTP 500. Intermittent, so the earlier automated runs did not hit it. | `check_same_thread=False` in `db.connect()` (safe: one connection per request, used one step at a time). Applied to **Iterations 1-4**. Also: slot buttons are locked while a booking is in flight (no double-click double-booking). | Regression test added to all four iterations; **8 real Chrome users booking at the same time: all 8 bookings shown, 0 server errors**; double-click now books once; 120 concurrent requests per backend: 0 failures |
| (found while diagnosing) nginx could keep a stale backend address after the backend container was recreated | nginx resolves the upstream name once at start-up | nginx now re-resolves through Docker DNS every 5 s | Backend force-recreated: page still answers HTTP 200 |

## Live acceptance run (real Chrome + direct API)
Run after the audit, with browser automation (Chrome) against the running app, then direct HTTP calls. Data: data pack 1 only.

| Layer | Where | Required | Stretch | Result |
|---|---|---|---|---|
| Browser (real UI) | isolated copy of the app, fixed clock Mon 2 Nov 2026 10:00 + the data pack's stretch seed | 49 | 15 | 64 / 64 pass |
| Browser (real UI) | **the real app, http://localhost:5171**, real clock | 28 | 3 | 31 / 31 pass |
| Direct API | isolated copy | 79 | 16 | 95 / 95 pass |
| pytest | `backend/tests` | 39 | 53 | 92 / 92 pass |

Why two copies of the app: the handout's "inside 2 hours" rows need an appointment that starts within 2 hours of "now", and the real app runs on the real clock.
The real app was tested with the same flows (and a late cancellation using a Dr. Rao slot that started within 2 hours of the real clock).
Test records on the real app were removed afterwards by exact ID; the database was compared with a backup taken before testing: every table identical.

Found and fixed during this run:
| Finding | Fix |
|---|---|
| The Docker container ran on UTC, so the clinic clock was 5.5 hours behind local time (affects the 2-hour cut-off) | `docker-compose.yml` sets `TZ` from `CLINIC_TZ` (default `Asia/Kolkata`) |
| `backend/data/weekly_schedule.csv` had a stray trailing space on line 15 (not made by the app) | restored byte-identical to data pack 1 |
No application-behaviour bug was found by this run; the earlier thread bug (see above) was already fixed.

## Handout checklist: every item
### Section 04 requirements
| Item | Status | Where / evidence |
|---|---|---|
| R1 load the data pack; Asha (9000000001) sees all 5 doctors; appointments start empty | PRESENT | `db.py`; `test_R1_*`; Docker: 5 doctors, 25 patients, 60 schedule rows, holidays, 0 appointments |
| R2 completed visits; follow-up only with the doctor who completed the last visit | PRESENT | `test_R2_*`; Dr. Rao completes Cataract -> follow-up with Rao yes, Iyer no |
| R3 three logins, no passwords; new mobile creates a patient; role checked in the backend | PRESENT | `test_R3_*`; `main.require` on every route |
| R4 free slots on 10-minute marks, 20 / 10 minutes; Rao has no Thursday-morning slots; booked slot disappears | PRESENT | `test_R4_*`; Docker check |
| R5 one rules check; clear refusal naming the rule; patient cancel until 2 h before, then "Please contact Staff"; Staff can cancel; cancelled slot free again | PRESENT | `rules.py` is the only place with rules; `test_R5_*`; 38 of 38 `rule_tests.csv` |
| R6 screens for each role, refusals in plain words | PRESENT (code + build) | `frontend/src/App.jsx`; build passes. **Not click-tested in a browser** (see below) |

### Section 03 roles
| Role | Required | Status |
|---|---|---|
| Patient | login; see doctors + specialities; free slots, book, cancel; see only own appointments | PRESENT, tested |
| Staff | see every appointment by day and doctor; book for any patient incl. walk-ins; cancel even inside 2 hours | PRESENT, tested (+ register a new walk-in) |
| Doctor | pick name; own schedule for a chosen day; which patient is in each slot; mark completed | PRESENT, tested |

### Section 09 "Done when" (13 rows) and bullets
All 13 rows pass as `test_S09_row01` ... `row13`, plus the three final bullets (every check behaves; every role can do section 03; a patient cannot see or
change another's appointment even by calling the API). Reason codes match the data pack README.

### Section 11 stretch goals
| Stretch goal | Status |
|---|---|
| Reschedule (same rules and 2-hour cut-off; refused new booking keeps the original) | PRESENT: `service.reschedule`, Reschedule button, T36-T38 |
| Staff approval queue | PRESENT (built in this audit) |
| Automated rule tests: the 38 cases of `rule_tests.csv` on `appointments_seed.csv` with the fixed clock | PRESENT: 38 of 38 pass |
| Staff can add holidays and edit a doctor's weekly schedule | PRESENT (built in this audit) |
| Week view calendar for each doctor | PRESENT (built in this audit) |
| Run the app with Docker Compose | PRESENT and RUNNING (built in this audit) |

### Section 05 rules and safety, section 06 data, section 10 submission
| Item | Status |
|---|---|
| Every rule in the backend, in one place; frontend never relies on hiding options | PRESENT (`rules.py`) |
| Patients only see their own appointments and details | PRESENT, tested |
| **Data pack 1 only, no fake data** | VERIFIED: `backend/data` is byte-identical to `Iteration1/data-pack-01` (7 files); the Docker image contains only that; the only value not from the pack is the new-mobile number in tests (see finding 6) |
| README explaining how to run the app and the tests | PRESENT (`README.md`) |
| Demo video of 3 minutes or less | NOT DONE: you record it (see `Output/NetraCare-Explainer-Video-Script.md`) |

## Verification results
- **92 automated tests pass** (checklist 26, rule cases 39 = the 38 cases of `rule_tests.csv` + a load check, stretch goals 14, roles and flows 13).
- **Docker:** `docker compose up --build` builds both images, both containers healthy; **35 end-to-end checks passed** through nginx
  (data counts equal the CSVs, booking, 8 different refusals, week calendar, holiday and schedule edits, reschedule, completion + follow-up,
  database survives a container restart). The Docker volume was then reset: a fresh start has 0 appointments.
- **Frontend build** passes. **0 empty files.** **0 `__init__.py`.**

## Not verified (honest limits)
1. **The screens have not been clicked through in a browser.** The Chrome connection was lost earlier. The API, the build and the Docker serving are verified; the
   look and feel of the new screens (Approvals, Clinic settings, Week view) is not. Open http://localhost:5171 and try each once.
2. **Section 09 "by hand" and the demo video** are yours to do.
3. **The late-cancel approval flow** is verified by automated tests on the fixed clock (Mon 2 Nov 2026, 10:00), not in the Docker run, because it needs an appointment
   that starts in under 2 hours. To try it by hand: `NETRACARE_SEED_APPOINTMENTS=1 CLINIC_NOW=2026-11-02T10:00 docker compose up --build`, log in as
   Lakshmi Nair (9000000003) and cancel her 11:00 appointment, then approve it as Staff.
