# Repository Guidelines

## Project Structure & Module Organization
`backend/` contains the FastAPI service, API routes, models, migrations, and `backend/tests/` for Python tests. `frontend/` is the Vue 3 + Vite app, with source in `frontend/src/` and UI tests in `frontend/tests/`. `pipeline/` and `agent/` hold offline strategy and review workflows. `deploy/` contains Docker Compose, image definitions, and startup scripts. Runtime data, logs, caches, and exports live under `data/` and should stay untracked.

## Build, Test, and Development Commands
The default local workflow is Docker-first:

```bash
cp .env.example deploy/.env
./start.sh
./stop.sh
```

Use `./deploy/scripts/start.sh ps`, `logs backend`, or `exec-backend` for container operations. Run backend tests from the repo root with the project venv: `.venv/bin/python -m pytest`. Frontend commands live in `frontend/`: `npm run dev`, `npm run build`, `npm run test`, `npm run test:coverage`, and `npm run lint`.

## Coding Style & Naming Conventions
Follow existing conventions in each layer. Python uses 4-space indentation, snake_case for modules/functions, and type hints in service and API code. Vue/TypeScript uses 2-space indentation, PascalCase for view components such as `TomorrowStar.vue`, and camelCase for stores and utilities such as `initTaskViewState.ts`. Keep new files near the feature they serve instead of creating broad utility buckets. Use ESLint for frontend cleanup; keep imports explicit and grouped logically.

## Testing Guidelines
Pytest is configured in `pytest.ini` and discovers `backend/tests/test_*.py`. Use the existing markers (`unit`, `service`, `api`, `integration`, `slow`) where they fit. Backend tests rely on isolated in-memory SQLite fixtures even though production runs on PostgreSQL. Frontend tests use Vitest; place test files under `frontend/tests/` or adjacent to the module if the pattern already exists.

## Commit & Pull Request Guidelines
Recent commits use short, task-focused summaries, often in Chinese, for example `优化初始化效率` or `部署 v1.1`. Keep commit messages concise, specific, and scoped to one change set. PRs should describe the user-visible impact, note config or schema changes, link related issues, and include screenshots for frontend changes. Call out any `.env.example`, migration, or deployment script updates explicitly.

## Security & Configuration Tips
Do not commit `.env`, `deploy/.env`, `data/`, logs, or real API keys. When adding config, update `.env.example`, `README.md`, and deployment docs together.
