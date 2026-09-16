# Employee Platform Demo

Permanent project context and development rules for Claude Code.

## Project purpose

A **beginner-friendly learning project** demonstrating a metadata-driven
enterprise platform combined with a metadata-driven data engineering / ETL
architecture.

The goal is learning architecture and implementation concepts - **not** building
a production enterprise system. Favour clarity over completeness.

## Runtime

- The application runs **completely locally**.
- **Do NOT use Docker.**
- **Do NOT deploy** the frontend or backend to the cloud.
- Azure is used **only** for the data engineering portion, later:
  - Azure Data Factory
  - Azure Data Lake Storage Gen2
- **Do NOT use Azure Databricks** - it is outside the intended free-trial scope.

## Tech stack

**Frontend:** HTML concepts, simple CSS, JavaScript, React, Vite.
Apache ECharts later, for dashboards.

**Backend:** Python, FastAPI, Pydantic, SQLAlchemy, Alembic, bcrypt
authentication.

**Database:** local PostgreSQL (`employee_platform`).

## The 8 applications

The platform contains exactly eight applications:

1. Employee Management
2. Leave Management System
3. Payroll
4. Attendance & Timesheet
5. Expense Management
6. User Management *(platform admin only)*
7. Role Management *(platform admin only)*
8. User-Role Management *(platform admin only)*

**LMS in this project means Leave Management System, never Learning
Management.** There are no courses, enrolments or learning content anywhere in
this platform. The application code is `LEAVE_MANAGEMENT` so the abbreviation
cannot be misread again.

The final three are platform administration applications, visible only to the
Super Admin / Platform Admin.

Two access rules that are easy to get wrong:

- **Employee Management is not self-service.** It is for HR, managers and
  administrators. An ordinary EMPLOYEE has no access to it.
- **Payroll is employee-facing.** Everyone can open it to see their own salary.
  Opening an application is not the same as seeing everybody's data - row-level
  filtering is a separate concern, handled when payroll is actually built.

Application Admins can configure settings for their assigned business
applications, but do **not** automatically become platform administrators.

## Metadata-driven design (primary learning objective)

Business configuration must not be unnecessarily hardcoded in frontend or
backend code.

**Code contains reusable behaviour and engines.
The database contains business configuration.**

Metadata/configuration should eventually cover: users, roles, permissions,
applications, screens, dashboards, dashboard widgets, business unit types,
business units, user-role assignments, user-business-unit assignments,
application administration, workflows, workflow states, workflow transitions,
workflow actions, data sources, connectors, ETL pipelines, pipeline steps,
mappings, incremental-load configuration, and schedules.

Practical test: *adding a new role, screen, dashboard or data source should be
an INSERT, not a code change.*

## RBAC

Access is metadata-driven:

```
User -> Role -> Permission -> Application -> Screen -> Dashboard
```

- Users may have multiple roles.
- Roles may have multiple permissions.
- Roles may have access to multiple applications.
- **Application Admin** is scoped to specific applications.
- **Super Admin / Platform Admin** manages platform-wide configuration: users,
  roles, user-role assignment, permissions, applications, screens, dashboards,
  business units, workflows, connectors, ETL configuration, platform settings.

## Business unit hierarchy

Business Unit Type is metadata-driven. Initial conceptual types: Headquarters,
Company, Branch, Department.

**Do NOT create separate company / branch / department tables.** Use one
self-referencing table:

```
business_units.parent_id -> business_units.id
```

```
Headquarters
├── Company
│      ├── Branch
│      │      ├── Department
│      │      └── Department
│      └── Branch
│             ├── Department
│             └── Department
└── Company
       └── Branch
              └── Department
```

Users can belong to multiple business units. Organisational access is separate
from role access, so effective access combines **RBAC + business unit scope**:

```
roles          -> WHAT   permissions, applications, screens
business units -> WHERE  this unit and everything beneath it
```

**The inheritance rule:** an assignment grants that unit **and all of its
descendants**, never anything above it. Company 1 sees its branches and their
departments; Branch 1 does not see Company 1.

Neither half implies the other. Adding a role never widens organisational
scope, and adding a business unit never grants a permission - not even for
SUPER_ADMIN, which still needs an assignment to have scope.

Descendants are resolved with a **recursive CTE** in
`app/services/business_unit_service.py` (adjacency list only - no closure
tables, nested sets or materialised paths). Never write hierarchy SQL in a
route; ask that service.

## Workflow engine

A **generic**, metadata-driven engine - workflows are not hardcoded one by one:

```
Workflow -> States -> Transitions -> Actions -> Allowed roles/permissions
```

Example:

```
DRAFT --Submit--> PENDING_APPROVAL --Approve--> APPROVED
                                   --Reject---> REJECTED
```

Do not force every CRUD operation through a workflow. Use workflows only where
state transitions are meaningful.

**How it is built (Stage 7).** `app/workflows/engine.py` is the *only* workflow
code. It never names a state, a transition or a role - it reads them from the
tables and applies them. Rules that follow from that:

- A new process is rows in `workflows` / `workflow_states` /
  `workflow_transitions`, never a new Python module and never a
  per-application branch.
- Who may perform a transition comes from `workflow_transition_roles`, which
  reuses the RBAC roles. There is no second permission system, and a
  transition with no roles attached is performable by nobody (fail closed).
- Any entity can be workflow-driven by carrying `workflow_id` and
  `current_state_id`. `WorkflowDemoRequest` is the first; an expense or a
  leave request will be the next, with no engine change.
- `workflow_history` is append-only and generic: it stores
  `(entity_type, entity_id)` rather than a foreign key to one business table.
  No API modifies it.
- A transition and its history row commit **together**. A state change with no
  history entry would be an audit trail with a hole in it.

## Dashboards

Metadata-driven:

```
Dashboard -> Dashboard Widgets -> Widget Configuration -> Data -> ECharts
```

Do not hardcode every dashboard layout or business configuration into React.

**How it is built (Stage 6).** A widget row carries `widget_type`
(`stat`/`bar`/`line`/`pie`/`table`), a `config_json` blob and a `width` in
columns out of 12. `DashboardWidget.jsx` holds one small switch mapping the
type to a component; `EChart.jsx` is the single ECharts wrapper. Adding a tile
is an INSERT, and adding a *kind* of tile is one new case plus a component -
never a new dashboard page. Sample values live in `config_json` until real
queries arrive, so the render path is real before the analytics are.

## Data engineering / ETL

External sources will eventually include PostgreSQL, REST API, and FTP/SFTP.

```
External Sources -> Azure Data Factory -> ADLS Gen2 -> Bronze -> Silver -> Gold
```

Transformations should remain **moderate** and use ADF.

ETL must also be metadata-driven, so a new source/table/pipeline is configured
through metadata rather than a new hardcoded extraction function per source.
Conceptual metadata: `data_sources`, `source_connections`, `source_objects`,
`source_columns`, `pipelines`, `pipeline_steps`, `mappings`,
`incremental_configs`, `schedules`, `pipeline_runs`.

**Do not build a generic ETL framework prematurely.** Keep it understandable.

### Sample data

Realistic free/public sample data (Kaggle/public datasets, public REST APIs,
public CSV/file sources). **Do not invent the final external data architecture
prematurely.**

## Database design

Use proper relational design: one-to-many, many-to-many, self-referencing
relationships, foreign keys, uniqueness, indexes. SQLAlchemy for the ORM,
Alembic for schema migrations.

## Authentication

Local application authentication with bcrypt password hashing. Never store
plaintext passwords.

Do **not** use Entra ID, OAuth, Auth0, or any external identity provider unless
explicitly requested later.

## Development style

Always favour **simple, explicit, understandable, modular, minimal
dependencies** over enterprise complexity. Do not introduce architecture or
libraries just because they are common in production.

- Explain important concepts to the developer at each stage.
- Do not silently redesign the architecture.
- Do not implement future stages without explicit instruction.

## Development process

| Stage | Contents | Status |
| ----- | -------- | ------ |
| 1  | Project foundation: React, FastAPI, Git, local structure | **Complete** |
| 2  | PostgreSQL, SQLAlchemy, Alembic, initial metadata/domain tables | **Complete** |
| 3  | Authentication | **Complete** |
| 4  | Users / Roles / Permissions, RBAC | **Complete** |
| 5  | Business Unit hierarchy, business-unit access | **Complete** |
| 6  | Applications / Screens / Dashboards, metadata-driven app launcher | **Complete** |
| 7  | Generic workflow engine: states / transitions / actions | **Complete** |
| 8  | Employee Management | **Complete** |
| 9  | Leave Management System | **Complete** |
| 10 | Attendance & Timesheet | Not started |
| 11 | Expense Management | Not started |
| 12 | Payroll + richer ECharts dashboards | Not started |
| 13 | External connectors: PostgreSQL, REST API, FTP/SFTP | Not started |
| 14 | Azure Data Factory + ADLS, Bronze/Silver/Gold | Not started |
| 15 | Metadata-driven ETL configuration | Not started |
| 16 | Integration, testing, documentation, architecture diagrams | Not started |

### Current status

- **Stage 1 complete** - React + Vite frontend, FastAPI backend, local-only, no Docker.
- **Stage 2 complete** - PostgreSQL connected, SQLAlchemy + Alembic configured,
  12 initial tables migrated, database health endpoint verified.
- **Stage 3 complete** - bcrypt authentication, bearer tokens stored in
  `auth_tokens`, `/api/auth/login|me|logout`, React login + landing page.
- **Stage 4 complete** (corrected) - metadata-driven RBAC: `role_screens`, the metadata
  seed, `rbac_service`, `require_permission` / `require_application`,
  `/api/access/*` and the RBAC management APIs, and a React launcher whose menu
  comes entirely from the database. 37 backend tests passing.

- **Stage 5 complete** - the organisation hierarchy: `business_unit_types` and
  a self-referencing `business_units` tree, `business_unit_service` with a
  recursive CTE for descendants, business-unit CRUD and user-assignment APIs,
  the `/api/business-units/{id}/access-check` demonstration of RBAC **plus**
  scope, and a React organisation tree. 116 backend tests passing.

- **Stage 6 complete** - the metadata chain Application -> Screen -> Dashboard
  -> Widget. New `dashboard_widgets` table, `metadata_service` for
  access-filtered lookups, `/api/access/{applications,screens,dashboards}/...`
  endpoints, and a React application shell that renders any application from
  metadata alone, with ECharts widgets. 137 backend tests passing.

- **Stage 7 complete** - the generic workflow engine: `workflows`,
  `workflow_states`, `workflow_transitions`, `workflow_transition_roles`,
  `workflow_history` and a throwaway `workflow_demo_requests` entity;
  `app/workflows/engine.py` interprets the metadata and reuses RBAC roles for
  authorisation. 164 backend tests passing.

- **Stage 8 complete** - Employee Management, the first real business
  application: an `employees` table kept separate from `users`, scoped reads
  through `business_unit_service`, paginated/filtered CRUD, and an employee
  dashboard whose widgets keep their metadata shape but draw live scoped
  figures from PostgreSQL. 195 backend tests passing.

- **Checkpoint after Stage 8 (2026-09-11)** - full audit, layout/chart fixes,
  dead-code removal, README rewritten. 195 tests. Findings and remaining
  issues are recorded in `docs/TODO.md`.

- **Stage 9 complete** - the Leave Management System, and the first business
  process driven end to end by the Stage 7 engine. `leave_types` as
  configuration rows and `leave_requests` carrying `workflow_id` /
  `current_state_id` instead of a status column; the seeded `LEAVE_APPROVAL`
  workflow (5 states, 4 transitions); `leave_service`, whose every read starts
  from one visibility query and whose every state change goes through the
  engine. **`app/workflows/engine.py` was not modified** - Leave satisfies its
  four-field contract and is driven by rows, which is the proof the Stage 7
  design works. Two rules are derived rather than named: a request is editable
  while its state `is_initial`, and a transition leaving the initial state
  belongs to the request's owner (which is also what forbids self-approval).
  261 backend tests passing.

## Working rule for every new stage

Before implementing a new stage:

1. Explain **what** we are building.
2. Explain **why** it exists.
3. Explain **how** it connects to the existing architecture.
4. Implement **only that stage**.
5. Give **exact verification steps**.
6. Explain the important code/files in **beginner-friendly** language.

Do not assume the developer already understands full-stack concepts.

## Task tracking

For every implementation or debugging prompt:

1. **Begin by displaying a clear task checklist.**
2. **Mark each task `[x]` immediately after it is completed** - not at the end.
3. **Mark failed tasks `[!]` and explain the error.**
4. **Keep the checklist visible during execution**, re-displaying it as progress
   is made, rather than only showing it in the final recap.
5. **Do not mark a task complete unless it was actually implemented and
   verified.** "It should work" is not verification.
6. **At the end, show the final checklist together with the verification
   results.**

If blocked, explain the blocker before continuing.

### Two levels of tracking - and only two

| Level | File / place | Scope |
| ----- | ------------ | ----- |
| Project roadmap | `docs/TODO.md` | Overall progress across the 16 stages |
| Task checklist | The Claude reply itself | Progress within the current prompt |

`docs/TODO.md` is long-lived and changes only when a stage genuinely advances.
The per-task checklist is short-lived and lives in the conversation.

**Do not create a second, duplicate tracking system** - no extra progress
files, no status tables scattered through the codebase, no per-stage TODO
files. If tracking is needed, it belongs in one of the two places above.

## UI / UX

The platform should have a clean, modern **enterprise / data-platform**
appearance: dark navy navigation, a light working area, and a single teal
accent. Restrained, not decorative.

### Colour tokens

Every colour lives in `frontend/src/index.css` as a CSS custom property. Use
the token names in components - **never a raw hex code in a `.jsx` file, and
never a new hex code outside the `:root` block.**

| Token | Value | Role |
| ----- | ----- | ---- |
| `--color-prussian` | `#0B132B` | sidebar, headings, body text |
| `--color-indigo`   | `#1C2541` | raised surfaces on dark, active nav row |
| `--color-dusk`     | `#3A506B` | muted text, secondary buttons |
| `--color-teal`     | `#5BC0BE` | the accent |
| `--color-white`    | `#FFFFFF` | surfaces |

Light neutrals `#F5F7FA`, `#E8EDF2` and `#CBD5E1` may be derived for page
backgrounds, borders, dividers, disabled states and subtle table backgrounds.
Do not replace this palette with another scheme.

Semantic tokens (`--color-error`, `--color-success`, `--color-warning`) may use
accessible reds/greens/ambers, but the core identity stays navy and teal.

### The teal rule

Contrast was measured, and it decides how teal may be used:

- Teal on white is **2.16:1** - it **fails**. Never use teal for text on a
  light surface, and never white text on teal.
- Prussian on teal is **8.52:1** - so buttons are dark text on a teal fill.
- Teal on Prussian is **8.52:1** - teal is legible as text on the dark sidebar.

Teal is an accent: button fills, active indicators, focus rings, borders, and
text on dark navy only.

### Rules

- Prefer reusable CSS classes over duplicated styling. Add a class, not an
  inline style.
- Keep the CSS understandable for a beginner - plain CSS, no preprocessor, no
  utility framework, comments explaining *why*.
- Maintain consistent spacing (`--space-*`), radii (`--radius-*`) and typography.
- Every interactive element needs hover, focus and disabled states. Focus must
  be visible for keyboard users - `:focus-visible` applies the shared ring.
- Every async screen needs loading, error and empty states. Use the shared
  `StatusViews` components and the `useAsync` hook.
- Avoid excessive gradients, animation and decorative effects. Respect
  `prefers-reduced-motion`.
- Aim for at least WCAG AA (4.5:1) on all text; measure rather than guess.
- The layout is desktop-first but must not break at narrower widths.
- **Preserve metadata-driven behaviour.** Navigation and application visibility
  come from `/api/access/me`. Never hardcode an application list, and never
  gate UI on a role name - style the data the backend returns.

## Claude Code behaviour

**Before significant changes:** inspect existing code, preserve working
functionality, avoid duplicate implementations, avoid unnecessary refactoring.

**When debugging:** identify the *actual* root cause with evidence. Do not list
random possibilities as the conclusion. Make the smallest sensible fix, and run
the relevant tests.

**When adding dependencies:** explain why they are needed; avoid unnecessary
packages.

**When changing the database:** use Alembic migrations. Do not manually modify
the schema without a migration.

**When creating code:** keep modules focused, use clear naming, avoid giant
files where reasonable.

**Do not implement the next project stage unless explicitly requested.**

---

# Repository layout

```
employee-platform-demo/
├── backend/           FastAPI application
│   ├── alembic/       migrations (env.py reads DATABASE_URL from .env)
│   ├── app/
│   │   ├── api/       routers: health.py, auth.py; deps.py holds get_current_user
│   │   ├── core/      config.py (Settings), security.py (bcrypt + tokens)
│   │   ├── db/        base.py (declarative Base), database.py (engine, session)
│   │   ├── models/    one file per table, all re-exported in __init__.py
│   │   ├── schemas/   Pydantic request/response models
│   │   ├── services/  business logic (auth_service.py)
│   │   ├── metadata/  repositories/  workflows/   (empty, later stages)
│   │   └── main.py
│   ├── scripts/       create_admin_user.py (dev only)
│   └── tests/
├── frontend/          React + Vite
│   └── src/           config/ services/ pages/ components/ layouts/ hooks/ utils/
├── etl/               placeholder for stages 13-15
└── docs/
```

## Running locally

Two terminals. **Both must be running** - the login page cannot work without
the backend.

```powershell
# terminal 1 - backend on http://127.0.0.1:8000
cd C:\employee-platform-demo\backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload

# terminal 2 - frontend on http://localhost:5173
cd C:\employee-platform-demo\frontend
npm run dev
```

Other commands:

```powershell
alembic upgrade head                      # apply migrations
alembic revision --autogenerate -m "..."  # create one after changing models
pytest                                    # backend tests
python scripts/create_admin_user.py       # create/reset the local admin user
```

## Local environment gotchas

These have each cost real debugging time - check them first.

1. **The backend must actually be running.** A login stuck on "Signing in..."
   almost always means nothing is serving port 8000, or a stale process is
   holding the port without answering. Check with
   `netstat -ano | findstr :8000` and confirm
   <http://127.0.0.1:8000/api/health> responds.
2. **Kill stale servers before starting new ones.** A wedged uvicorn keeps the
   port bound and accepts connections it never answers, which is worse than
   being down: requests hang instead of failing fast.
3. **`WinError 10013` on startup means the port is already taken** - it is not a
   permissions or firewall problem, and not a Windows port reservation. Windows
   reports an occupied port as `10048` ("only one usage of each socket address")
   for a plain bind, but as `10013` ("access forbidden") when the binding socket
   sets `SO_REUSEADDR`, which uvicorn does. Confusingly,
   `netstat -ano | findstr :8000` shows nothing if you check before the other
   process started. Find and stop the owner:

   ```powershell
   netstat -ano | findstr :8000        # last column is the PID
   Get-CimInstance Win32_Process -Filter "ProcessId=<pid>" | Select CommandLine
   Stop-Process -Id <pid>
   ```

   To rule out a real Windows reservation:
   `netsh interface ipv4 show excludedportrange protocol=tcp`.
4. **Vite must be on port 5173.** If 5173 is taken, Vite silently falls back to
   5174 and browser logins then fail CORS, because only 5173 is allowed in
   `settings.cors_origins`. Close the duplicate dev server rather than widening
   CORS.
5. **A password containing `@` (or `:` `/` `#` `%` `?`) must be percent-encoded
   in `DATABASE_URL`** - e.g. `@` becomes `%40`. Otherwise the URL splits at the
   wrong place and you get a confusing `getaddrinfo failed`. `Settings` now
   raises a clear error for this.
6. **Editors can overwrite `.env`.** If a change to `.env` seems to revert,
   close the file in your editor before editing it elsewhere.

## Building a business application

Employee Management (Stage 8) is the pattern every later application follows.

- **A business entity is not a user.** `users` is who may sign in; a business
  table is who the business knows. Link them with a nullable `user_id` - most
  records will never have a login.
- **Never query a business table directly in a route.** Go through a service
  whose base query is already narrowed by
  `business_unit_service.get_user_visible_business_unit_ids`. In
  `employee_service` that is `_scoped_query`, and nothing in the module reads
  employees without it - so a new filter cannot accidentally skip the scope.
- **No assignment means nothing, never everything.** A user with no business
  unit sees zero rows.
- **Re-check every id the client sends.** A `business_unit_id` in a request
  body is a request, not a fact; validate it against the caller's scope before
  writing.
- **Page in the database**, and return `total` / `page` / `total_pages` so the
  UI can render "showing 1-10 of 22" without a second call.
- **Prefer status over delete.** Set INACTIVE; deleting takes reporting lines
  and history with it.
- **Dashboards stay metadata-driven.** A widget declares
  `{"data_source": "..."}` in `config_json`; a resolver in
  `dashboard_data_service` supplies scoped numbers. Titles, chart types,
  widths and order remain metadata. Never write a hardcoded dashboard page.
- **Screens get a component through the small registry** in
  `ScreenView.jsx`, keyed by screen code. Unlisted screens still render as
  their dashboards or a placeholder.

## Conventions in this codebase

- **Models:** SQLAlchemy 2.0 typed style (`Mapped[...]` / `mapped_column`), one
  model per file, every model imported in `app/models/__init__.py` so Alembic
  autogenerate sees it.
- **Naming:** every metadata table has both a human `name` and a stable machine
  `code` (e.g. `SUPER_ADMIN`). Configuration is looked up by `code`.
- **Layering:** `api/` handles HTTP only -> `services/` holds business rules ->
  `models/` touch the database. Keep FastAPI types out of services.
- **Schemas:** never expose `password_hash`. Response schemas are explicit
  allow-lists, not the ORM object.
- **Secrets:** `.env` is git-ignored and must never be committed. `.env.example`
  documents every variable with placeholder values.
- **Frontend network calls:** always go through `apiRequest()` in
  `src/services/apiClient.js`, which applies the timeout, the Authorization
  header and consistent error messages. A bare `fetch()` can hang forever
  against an unresponsive server. Screens that load data should use the
  `useAsync` hook so loading always ends.
- **Authorization:** never write an access rule into an endpoint. Ask
  `app/services/rbac_service.py`, or declare the requirement with
  `require_permission("EDIT")` / `require_application("ROLE_MANAGEMENT")`.
  Never branch on a role name - `if role == "SUPER_ADMIN"` defeats the whole
  metadata-driven design.
- **Seed data:** lives in `app/metadata/seed.py`, is matched by `code` so it is
  safe to re-run, and is imported by the tests so they exercise the same
  metadata the browser does.
- **Comments:** explain *why*, and assume a beginner reader. This project is
  documentation as much as it is code.
