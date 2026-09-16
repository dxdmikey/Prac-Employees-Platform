# Project roadmap and progress

Overall progress across the 16 planned stages. This is the **project-level**
tracker. Progress within a single Claude Code prompt is tracked by the task
checklist in that reply - see the "Task tracking" section of `CLAUDE.md`.

A stage is marked complete only when its functionality has been **run and
verified**, not merely written.

## Stages

- [x] **Stage 1 - Project foundation**
  React + Vite frontend, FastAPI backend, git repository, local folder
  structure. No Docker, no cloud.
  *Verified:* Vite dev server serves the placeholder page; `GET /api/health`
  returns `{"status":"ok","service":"employee-platform-backend"}`.

- [x] **Stage 2 - Database layer**
  PostgreSQL, SQLAlchemy, Alembic, and the first 12 metadata/domain tables:
  `users`, `roles`, `permissions`, `applications`, `screens`, `dashboards`,
  `business_unit_types`, `business_units` (self-referencing), plus the four
  association tables `user_roles`, `role_permissions`, `role_applications`,
  `user_business_units`.
  *Verified:* migration applied; `alembic check` reports no drift; all foreign
  keys and indexes inspected in PostgreSQL; the Headquarters -> Company ->
  Branch -> Department hierarchy built and read back through the ORM;
  `GET /api/health/db` returns `{"status":"ok","database":"employee_platform"}`.

- [x] **Stage 3 - Authentication**
  bcrypt password hashing, bearer tokens stored in `auth_tokens`,
  `POST /api/auth/login`, `GET /api/auth/me`, `POST /api/auth/logout`, React
  login page and authenticated landing page, CORS restricted to the local Vite
  origin.
  *Verified:* 18 backend tests pass; live flow checked end to end - correct
  credentials return 200 with a token, wrong credentials and unknown users both
  return the same 401, `/api/auth/me` returns the user without `password_hash`,
  logout revokes the token and reusing it returns 401.
  *Note:* the browser login form itself has not been clicked through by an
  automated test; the API path it uses is verified.

- [x] **Stage 4 - Users / Roles / Permissions, RBAC**
  `role_screens` association table; metadata seed (5 roles, 7 permissions, the
  8 applications, 13 screens); reusable `rbac_service` plus `require_permission`
  / `require_application` dependencies; `/api/access/me`,
  `/api/access/applications/{code}/screens`, RBAC management APIs and the
  `/api/rbac/test-edit` demonstration endpoint; React app shell with a
  metadata-driven launcher, dynamic screens and a role-assignment admin page.
  *Verified:* 37 backend tests pass; live checks against three real users -
  admin (SUPER_ADMIN) sees 8 applications, priya (HR) sees 5, jane (EMPLOYEE)
  sees 4 and none of the platform-admin ones; `/api/rbac/test-edit` gives 200
  for admin and HR, 403 for the employee; `GET /api/users` gives 200 for admin
  and 403 for both others; the Expense Approval screen is returned to admin and
  HR but not to the employee.
  *Corrected afterwards:* LMS was wrongly built as Learning Management. It is
  **Leave Management System** (`LEAVE_MANAGEMENT`), with Leave Dashboard, My
  Leave, Leave Requests and Leave Approval screens; the Course List and My
  Learning screens were deleted. The role-to-application matrix was corrected -
  Employee Management removed from EMPLOYEE, Payroll added to EMPLOYEE and
  MANAGER - and the seed now reconciles links rather than only adding them, so
  access can be taken away as well as granted. The "of 8" denominator now comes
  from `total_applications` in the access response.
  *Verified:* 83 backend tests pass; live counts are SUPER_ADMIN 8/8, HR 5/8,
  MANAGER 5/8, EMPLOYEE 4/8, with the full per-application 200/403 matrix
  checked for all four roles.
  *Note:* the React pages are verified by build and by the API they consume;
  no automated browser test clicks through them.
- [x] **Stage 5 - Business Unit hierarchy and business-unit access**
  Seeded business unit types (Headquarters/Company/Branch/Department) and a
  12-node development organisation in the existing self-referencing
  `business_units` table; `business_unit_service` resolving descendants with a
  recursive CTE, plus validation against self-parenting, cycles and deleting a
  unit that still has children; business-unit CRUD, tree, user-assignment and
  self-service scope APIs; `/api/business-units/{id}/access-check` requiring
  **both** the VIEW permission and business-unit scope; React organisation tree
  and business-unit assignment in the admin screen.
  *Verified:* 116 backend tests pass (33 new). Live scope - admin assigned HQ
  sees all 12 units, HR at Company 1 sees 7, Manager at Branch 1 sees 3,
  Employee at Department 1 sees 1. The 12x4 access-check matrix is a clean
  staircase: inheritance flows down, never up. Application RBAC unchanged at
  8/5/5/4. No schema change was needed - `alembic check` reports no drift.
  *Note:* the React tree is verified by build and by the API it consumes; no
  automated browser test clicks through it.
- [x] **Stage 6 - Applications / Screens / Dashboards, metadata-driven launcher**
  New `dashboard_widgets` table (migration `1c4b1324dd39`); the full screen set
  for all 8 applications (19 screens, `Expense List` renamed to `My Expenses`),
  6 dashboards and 16 widgets in the seed; `metadata_service` performing
  access-filtered lookups by delegating to `rbac_service`; access-scoped
  metadata endpoints for applications, screens, dashboards and widgets; a React
  application shell rendering any application's navigation and screens from
  metadata, with a widget renderer and an ECharts wrapper.
  *Verified:* 137 backend tests pass (21 new). Live - SUPER_ADMIN 8/8, HR 5/8,
  EMPLOYEE 4/8; Payroll navigation is 3 screens for admin/HR but only My Salary
  for an employee; the Payroll Dashboard screen returns 2 dashboards with 6
  widgets across stat/line/pie/table; an employee guessing
  `PAYROLL_SUMMARY`/`EMPLOYEE_LIST` by code gets 404. Business-unit scope
  unchanged. No hardcoded application, screen or role name anywhere in React.
  *Note:* the React pages are verified by build and by the API they consume; no
  automated browser test clicks through them, so ECharts rendering in a real
  browser is unconfirmed.
- [x] **Stage 7 - Generic workflow engine (states / transitions / actions)**
  Six new tables (migration `3f0f32d0eba7`); `app/workflows/engine.py` plus
  typed exceptions; the seeded `EXPENSE_APPROVAL_DEMO` workflow with 4 states
  and 3 transitions authorised by RBAC role; workflow definition and demo
  execution APIs; React workflow admin screen (diagram generated from
  metadata) and a demo screen whose action buttons come from the backend.
  *Verified:* 164 backend tests pass (27 new). Live - an employee is offered
  only Submit and a manager only Approve/Reject, each in the right state;
  DRAFT to APPROVED is refused with 409 because no such transition exists;
  an employee approving gets 403; history records all three steps with the
  acting user. RBAC and business-unit behaviour unchanged.
  *Bug found and fixed during verification:* the API returned the state from
  *before* a transition, because the application session uses
  `expire_on_commit=False` and the entity kept its previously loaded
  relationship. The engine now refreshes the entity after commit, and the test
  session was changed to match production so this class of bug is visible in
  tests.
  *Note:* the React screens are verified by build and by the API they consume;
  no automated browser test clicks through them.
- [x] **Stage 8 - Employee Management**
  `employees` table (migration `8af9430c31c4`) with a self-referencing
  `manager_id`, a `business_unit_id` that scope filters on, and a nullable
  `user_id` keeping HR data separate from authentication;
  `employee_service` whose every read goes through a scoped base query built
  from the Stage 5 service; paginated/filtered/searchable CRUD APIs with no
  delete; 22 seeded employees across the org tree; an employee dashboard whose
  Stage 6 widgets now declare `data_source` and are filled from PostgreSQL by
  `dashboard_data_service`; React list, profile, add/edit and ECharts screens
  reached through the metadata screen registry.
  *Verified:* 195 backend tests pass (31 new). Live - admin sees 22 employees,
  HR at Company 1 sees 15, a manager at Branch 1 sees 7, and an EMPLOYEE is
  refused the application entirely; dashboard totals match each user's list
  exactly; a manager searching for a Company 2 name gets 0 results; creating
  an employee in an out-of-scope unit is rejected with 400; pagination, search
  and status/business-unit filters all confirmed.
  *Note:* the React screens are verified by build and by the API they consume;
  there is still no frontend test framework, so no automated browser test.
- [x] **Stage 9 - Leave Management System**
  The first business process driven end to end by the Stage 7 engine. Two new
  tables (migration `6c89d0992c9b`): `leave_types` as configuration rows, and
  `leave_requests` carrying `workflow_id` / `current_state_id` instead of a
  status column. The seeded `LEAVE_APPROVAL` workflow - 5 states, 4
  transitions - plus 4 leave types and 25 fictional requests with a complete
  workflow history each; `leave_service` whose every read starts from one
  visibility query and whose every state change goes through the engine;
  `/api/leave/*`; eight `LEAVE_OVERVIEW` widgets switched from sample values to
  live scoped data; and three React screens (My Leave, Leave Requests, Leave
  Approval) registered through the existing screen registry, with the Leave
  Dashboard still rendered from metadata alone.
  **The engine was not modified.** Leave satisfies its four-field contract and
  is driven by rows.
  *Verified:* 261 backend tests pass (66 new, 195 pre-existing unchanged);
  `alembic check` clean; `npm run build` clean; the seed is idempotent - a
  second run reports zero changes. Live over HTTP against the running server:
  an employee sees only the two self-service screens, creates a request (4
  days, calculated server-side), is offered exactly Submit and Cancel, submits
  it, is then refused both editing (400) and approving it (403); a manager
  sees a six-item queue for Branch 1 and its departments, is offered
  Approve/Reject on the employee's request and **nothing at all on his own**,
  approves it, and the history shows all three steps with the right names
  against them. A Company 2 request is 403 for the manager, for HR and for the
  employee alike. Scope staircase 26/22/14/4 for admin/priya/raj/jane, with
  the dashboard KPIs matching each list exactly.
  *Bug found and fixed during testing:* `leave_service.execute_transition`
  accepted a `LeaveRequest` object and trusted it, so the business-unit check
  lived only in the API route that happened to fetch it carefully. A manager
  in another company could approve through the service directly. The three
  acting functions now take an **id** and resolve it through the visibility
  query themselves, so the scope rule cannot be skipped by any caller.
  *Note:* the React screens are verified by build and by the API they consume;
  there is still no frontend test framework, so no automated browser test.
- [x] **Stage 10 - Attendance & Timesheet**
  Two new tables (migration `38b012a1140b`) and one column added to an
  existing one. `attendance` is one row per employee per day, with a unique
  constraint doing the work rather than a check in the service, and a
  `worked_minutes` that is derived from the two timestamps but stored - the
  duplication is deliberate, and a test proves the stored value always matches
  the times it came from. `timesheets` is kept separate on purpose: the two
  disagreeing is useful information, and merging them would make "present, but
  nothing logged" impossible to express.
  The seeded `TIMESHEET_APPROVAL` workflow is the first with a **loop**:
  `REJECTED -> DRAFT` (Revise) returns a rejected entry to its author.
  `attendance_service` holds the clock rules; `timesheet_service` delegates
  every state change to the Stage 7 engine. `/api/attendance/*` and
  `/api/timesheets/*`; fifteen widgets across two dashboards on the existing
  Attendance Dashboard screen, all live and scoped; four React screens
  registered through the existing screen registry.
  **The engine was not modified.** A `Timesheet` satisfies its four-field
  contract and is driven by rows.
  *Shared rather than copied:* the visibility rule used by Leave, Attendance
  and Timesheets - your own records always, plus your team's if you hold
  APPROVE - was extracted into `app/services/employee_scope.py` and all three
  now call it. Writing it three times would have been three chances to drift.
  *One metadata change, and why:* `workflow_states.is_owner_held`. Stage 9
  inferred "is this the owner's action?" from `is_initial`, which is true only
  while every owner action leaves the first state. Revise breaks that - it is
  the author's action starting from Rejected - so inferring from `is_initial`
  would have handed Revise to the approver. Marking the *state* says it
  directly and generalises; Leave now reads the same flag, and the column
  defaults to false so nothing else changed.
  *Verified:* 357 backend tests pass (96 new, 261 pre-existing, one Stage 6
  metadata expectation updated for the two added screens); `alembic check`
  clean; `npm run build` clean; the seed is idempotent - a second run reports
  zero changes across 417 attendance rows, 231 timesheets and 587 history
  entries. Live over HTTP: an employee checks in, is refused a duplicate
  check-in, checks out, is refused a duplicate check-out; a manager's
  "missing checkout" filter returns 13 open days across his branch; a
  timesheet goes Draft to Submitted to Rejected to Draft to Submitted to
  Approved, with the author offered Revise and **the manager who rejected it
  offered nothing**, and all six steps in the history with the right names
  against them. A Company 2 record is 403 for the manager, for HR and for the
  employee alike. A manager is refused the correction endpoint because
  MANAGER has no EDIT permission - no role name involved. Scope staircase
  418/292/125/21 for admin/priya/raj/jane.
  *Note:* the React screens are verified by build and by the API they consume;
  there is still no frontend test framework, so no automated browser test.
- [x] **Stage 11 - Expense Management**
  Three new tables (migration `aab477092eec`) and one column added to an
  existing one. `expense_categories` is configuration, so adding a category is
  an INSERT and the React dropdown is built from the API. `expenses` carries
  `workflow_id` / `current_state_id` rather than a status column, and its
  `amount` is **Numeric(12, 2), never Float** - a binary float cannot hold
  0.10 exactly, and money that does not reconcile is worse than no money.
  `expense_attachments` stores receipt metadata; the bytes live on local disk
  under a git-ignored directory.
  `expense_service` holds the claim rules and the storage rules;
  `/api/expenses/*` covers claims, the workflow, and receipt upload,
  download and removal; eight widgets on the existing Expense Dashboard now
  draw live scoped figures; two React screens are registered through the
  existing screen registry.
  **The engine was not modified.** An `Expense` satisfies its four-field
  contract and is driven by rows.
  *One metadata change, and why it was needed a third time:*
  `workflow_transitions.actor` (OWNER / OTHER / ANY, default ANY). Stage 9
  inferred "is this the owner's action?" from `is_initial`; Stage 10 moved it
  to the from-state's `is_owner_held`. Expense breaks both, because Cancel
  leaves SUBMITTED - a state that genuinely sits on the approver's desk, which
  is what the pending queue counts - and still belongs to the claimant. No
  state-level flag can say both things at once, so the marker moved onto the
  transition where it always belonged. `is_owner_held` stays, because "whose
  desk is this on?" is a separate and still-useful question.
  *Shared rather than copied:* the three private `_is_owner_action` helpers in
  Leave, Timesheets and Expenses collapsed into `app/workflows/ownership.py`.
  *Receipt security:* an attachment keeps two names. `file_name` is what the
  person called it and is only displayed; `stored_name` is generated
  server-side and is the only thing used to build a path. A test uploads a
  file called `../../../../etc/passwd` and checks that nothing resembling it
  reaches the filesystem. Type is an allow-list of three, size is capped at
  5 MB, and downloads are addressed by attachment id with the usual scope
  check through the parent claim.
  *Verified:* 440 backend tests pass (83 new); `alembic check`
  clean; `npm run build` clean; the seed is idempotent - a second run reports
  zero changes across 8 categories, 94 claims and 247 history entries. Live
  over HTTP: an employee sees only My Expenses, creates a claim, edits it,
  attaches a PNG receipt and is refused an `.exe`; the claim goes Draft to
  Submitted to Rejected to Draft to Submitted to Approved, with the rejection
  reason preserved on the history row; while Submitted, **the claimant is
  offered Cancel and the manager Approve/Reject, at the same moment on the
  same record**; a manager downloads the receipt of a claim in his scope, and
  a Company 2 claim is 403 for the manager, for HR and for the employee alike.
  Scope staircase 95/68/30/6 for admin/priya/raj/jane.
  *Note:* the React screens are verified by build and by the API they consume;
  there is still no frontend test framework, so no automated browser test.
- [ ] **Stage 12 - Payroll + richer ECharts dashboards**
- [ ] **Stage 13 - External connectors (PostgreSQL, REST API, FTP/SFTP)**
- [ ] **Stage 14 - Azure Data Factory + ADLS, Bronze/Silver/Gold**
- [ ] **Stage 15 - Metadata-driven ETL configuration**
- [ ] **Stage 16 - Integration, testing, documentation, architecture diagrams**

### UI design system (after Stage 4)

- [x] Centralised colour/design-token system in `frontend/src/index.css` using
  the project palette (Prussian `#0B132B`, Indigo `#1C2541`, Dusk `#3A506B`,
  Teal `#5BC0BE`, white) plus light neutrals; dark navy sidebar shell, teal
  accent, reusable card / button / form / table / status styles.
  *Verified:* every colour is a token (no hex outside `:root`, none in any
  `.jsx`); contrast measured on all 16 real pairings, lowest 5.72:1, all at
  least AA; `vite build` clean; backend untouched and all 83 tests still pass;
  the 11-point RBAC regression re-checked live and unchanged.
  *Note:* appearance itself was not verified in a browser by an automated test.

## MAJOR CHECKPOINT - AFTER STAGE 8

**Date:** 2026-09-11 · **Tests:** 195 passed before and after (no regressions) ·
`alembic check` clean · `npm run build` clean.

### Architecture findings

- Sound where it matters most: **no role name appears outside the seed**;
  **one** business-unit scoping implementation, reused by Employee Management
  rather than copied; models and migrations agree; every dependency is used.
- Authorisation is consistently two questions (RBAC + scope) and both are
  enforced server-side - confirmed live: an EMPLOYEE gets 403 on every
  Employee Management endpoint regardless of their business-unit scope.
- The workflow engine holds no application logic; the state check runs
  before the role check, so an unauthorised user attempting an out-of-state
  transition receives 409 rather than 403. Correct, but worth knowing.

### Fixed in this checkpoint

- **Charts** - `EChart` now uses a `ResizeObserver` on its own container (a
  chart created at 0px width stayed 0px; sidebar/content resizes were
  missed). Pie legends scroll on the right instead of colliding with the
  ring; long category labels tilt; chart widgets share a fixed height so
  mixed spans no longer produce ragged rows.
- **Admin screen** - `/api/users` now includes each user's business units, so
  the column no longer reads "assign one to load".
- **Employee list** - the Manager dropdown offers everyone active in scope,
  not just the ten rows on the current page.
- **Shell** - sticky sidebar and header; navigation items are data-driven
  inside `AppLayout` (one `NavItem`); `App.jsx` routes through a `VIEWS`
  table instead of nested ternaries, and unknown views fall back to the
  launcher.
- **Layout** - two-column layouts stack at 1100px, not only at phone width;
  tables have a minimum width and scroll inside their wrapper, never the page.
- **Engine** - user roles fetched once per `get_available_transitions`, not
  once per transition.
- **Cleanup** - five unused service wrappers, six Stage 1 placeholder READMEs,
  unused `BACKEND_HOST/PORT` in the root `.env.example`; README rewritten
  (it still described Stage 3).

### Known remaining issues

- **No frontend test framework.** Screens are verified by build and by the
  API they consume. Adding Vitest is a deliberate future decision.
- `app/metadata/seed.py` is ~960 lines. Splitting definitions from apply
  logic is the next maintainability step; deferred to avoid churn here.
- `access.py` returns 403 for an inaccessible application's screens but 404
  for every other "not yours" lookup. Harmless, inconsistent.
- `users.employee_code` (NOT NULL) duplicates the concept now owned by
  `employees.employee_code`. Reconcile when a real user-provisioning flow is
  built; not worth a destructive migration now.
- Second columns of composite association keys are unindexed (reverse
  lookups scan). Irrelevant at this size.
- The ECharts bundle makes the JS ~1.3 MB; fine locally, would want
  code-splitting before any real deployment.

## Known issues and follow-ups

Small items that are not worth a stage of their own.

- [ ] The root `.env.example` lists `BACKEND_HOST` / `BACKEND_PORT`, but nothing
  reads them - uvicorn takes its host and port from the command line. Either
  wire them up or remove them, so they cannot mislead.
- [ ] No frontend tests yet. The login form is verified only at the API level.
- [ ] `pytest` runs against the real local database inside a rolled-back
  transaction. A dedicated test database would be cleaner if the suite grows.

## Resolved

- [x] **Login stuck on "Signing in..."** - port 8000 was held by a stale uvicorn
  process that accepted connections but never answered, so `fetch()` never
  settled. Fixed by adding a request timeout in
  `frontend/src/services/authService.js`, so an unresponsive backend now
  produces a clear error instead of a frozen button.
- [x] **`WinError 10013` when starting uvicorn on port 8000** - the port was
  occupied by a leftover uvicorn. Windows reports an occupied port as 10013
  ("access forbidden") rather than 10048 when the binding socket sets
  `SO_REUSEADDR`, which uvicorn does. Resolved by stopping the stale process;
  port 8000 remains the project default.
