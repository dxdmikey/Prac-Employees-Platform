# Employee Platform Demo

A local learning project: a **metadata-driven enterprise platform** with eight
business applications, built stage by stage to learn architecture - not to be
a production system.

1. Employee Management *(built)*
2. Leave Management System *(built)*
3. Payroll *(screens only)*
4. Attendance & Timesheet *(screens only)*
5. Expense Management *(screens only)*
6. User Management *(platform admin)*
7. Role Management *(platform admin)*
8. User-Role Management *(platform admin)*

> **Current status: Stages 1-9 complete.** Authentication, metadata-driven
> RBAC, the business-unit hierarchy with scoped access, metadata-driven
> applications/screens/dashboards with ECharts, a generic workflow engine,
> Employee Management, and the Leave Management System are implemented and
> tested. Leave is the first business process driven end to end by the
> workflow engine - it added two tables and no engine changes. The remaining
> business applications, external connectors and the Azure ETL are not built
> yet. See `docs/TODO.md` for the roadmap and `CLAUDE.md` for the
> architecture rules.

## Architecture

```
Browser
  React + Vite  (frontend/)          http://localhost:5173
       |  JSON over HTTP, bearer token
  FastAPI       (backend/)           http://127.0.0.1:8000
       |  SQLAlchemy + Alembic
  PostgreSQL    (employee_platform, local)

Later - data engineering only (etl/):
  External sources (PostgreSQL, REST, FTP/SFTP)
       -> Azure Data Factory -> ADLS Gen2 -> Bronze / Silver / Gold
```

Everything above the dotted line runs on your machine. **Docker is
deliberately not used**, and the application is not deployed anywhere.

### The idea in one sentence

**Code holds reusable engines; the database holds business configuration.**
Which applications exist, which screens they have, which dashboards and
widgets sit on them, who may do what and where, and how a record moves
through an approval - all of it is rows, read by generic code. Adding a role,
a screen or a workflow step is an INSERT, not a deploy.

### Layers

```
Frontend:  React component -> services/*.js -> apiClient.js -> FastAPI
Backend:   api/ (HTTP only) -> services/ (rules) -> models/ (SQLAlchemy) -> PostgreSQL
```

Authorisation is two independent questions, both answered on the backend:

| Question | Answered by | Source of truth |
| -------- | ----------- | --------------- |
| **What** may this user do? | `services/rbac_service.py` | roles -> permissions / applications / screens |
| **Where** may they do it? | `services/business_unit_service.py` | user's business units + every descendant |

Hiding something in React is never the control; every API re-checks.

## What is implemented

| Area | Where |
| ---- | ----- |
| Login with bcrypt, bearer tokens stored server-side, logout revokes | `app/core/security.py`, `app/api/auth.py` |
| Roles, permissions, applications, screens as metadata; `require_permission`, `require_application` | `app/services/rbac_service.py`, `app/api/deps.py` |
| Self-referencing business-unit tree; descendants via recursive CTE; scope inheritance downward only | `app/services/business_unit_service.py` |
| Applications -> screens -> dashboards -> widgets, all metadata; React renders whatever it is given | `app/services/metadata_service.py`, `frontend/src/components/ScreenView.jsx` |
| Widgets that declare a `data_source` get live, scoped numbers | `app/services/dashboard_data_service.py` |
| Generic workflow engine: states, transitions, RBAC-authorised, append-only history | `app/workflows/engine.py` |
| Employee Management: scoped, paginated CRUD; live dashboard | `app/services/employee_service.py`, `frontend/src/screens/` |
| Leave Management: leave types as rows, requests driven by the `LEAVE_APPROVAL` workflow, scoped approval queue, live dashboard | `app/services/leave_service.py`, `frontend/src/screens/` |

## Prerequisites

- **Node.js 20.19+ or 22.12+** - `node --version`
- **Python 3.11+** - `python --version`
- **PostgreSQL 14+** running locally - `psql --version`

## Setup

```powershell
# 1. backend environment
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. database connection - copy and edit with your local credentials
Copy-Item .env.example .env
#    A password containing @ : / # % ? must be percent-encoded (@ -> %40).

# 3. database
createdb -U postgres employee_platform
alembic upgrade head

# 4. users and metadata
python scripts/create_admin_user.py          # prompts for a password
python scripts/seed_metadata.py              # roles, apps, screens, org tree, workflows, employees, leave
python scripts/create_user.py jane EMPLOYEE  # optional demo users
python scripts/create_user.py priya HR
python scripts/create_user.py raj MANAGER
python scripts/seed_metadata.py              # again, to place the demo users in the org tree
```

The seed is idempotent - run it as often as you like. It is also
*authoritative* for role links: re-running it discards role changes made
through the admin screen.

## Running

Two terminals. Both must be running.

```powershell
# terminal 1 - backend
cd backend; .\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload

# terminal 2 - frontend
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. API docs are at <http://127.0.0.1:8000/docs>.

**Use port 5173.** If Vite falls back to 5174 because 5173 is busy, logins
fail CORS - close the other dev server instead of widening CORS.

## Development users

Created by the commands above; the seed assigns each a business unit so scope
can be seen working:

| User | Role | Business unit | Sees |
| ---- | ---- | ------------- | ---- |
| admin | SUPER_ADMIN | Headquarters | 8 applications, all 22 employees, all 25 leave requests |
| priya | HR | Company 1 | 5 applications, 15 employees, 21 leave requests |
| raj | MANAGER | Branch 1 | 5 applications, 7 employees, 13 leave requests |
| jane | EMPLOYEE | Department 1 | 4 applications, no Employee Management, and only her **own** 3 leave requests |

The last row is the one worth looking at. jane sits in Department 1, which has
seven seeded leave requests, and she sees three of them - her own. Business-unit
scope alone never reveals somebody's leave; seeing a colleague's request also
needs the APPROVE permission, which the EMPLOYEE role does not have.

## Tests

```powershell
cd backend; .\.venv\Scripts\Activate.ps1
pytest            # runs against your local database inside a rolled-back transaction
alembic check     # models and migrations agree
```

There is no frontend test framework yet; the React screens are verified by
`npm run build` and by the API they consume.

## Repository layout

```
employee-platform-demo/
  backend/
    alembic/            migrations - env.py reads DATABASE_URL from .env
    app/
      api/              routers; deps.py holds the auth/authz dependencies
      core/             config.py, security.py
      db/               engine, session, declarative Base
      models/           one SQLAlchemy model per file
      schemas/          Pydantic request/response models
      services/         business rules; all scoping lives here
      workflows/        the generic engine
      metadata/seed.py  the development metadata, idempotent
    scripts/            create_admin_user.py, create_user.py, seed_metadata.py
    tests/
  frontend/src/
    components/         reusable pieces (EChart, DashboardWidget, StatusViews...)
    layouts/            AppLayout - the shell
    pages/              platform screens (launcher, admin, organisation, workflows)
    screens/            business-application screens, registered in ScreenView
    services/           one module per API area, all through apiClient.js
  etl/                  placeholders for the data-engineering stages
  docs/TODO.md          roadmap and verified progress
  CLAUDE.md             architecture rules and conventions
```
