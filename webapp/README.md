# Production Webapp MVP

This folder is the working frontend for the real product path.

Implemented:
- local login against FastAPI
- dashboard summary cards
- incoming requests page with approve / assign / override
- queue list with filters
- case detail with approve / override actions
- review page
- notifications page
- RAG assistant wired to the API
- session-based auth state in the browser
- mobile-responsive formal government dashboard layout

## Run

```bash
cd webapp
cp .env.example .env.local
npm install
npm run dev
```

Expected API base URL:
- `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000`

Main routes:
- `/login`
- `/dashboard`
- `/incoming`
- `/queues`
- `/review`
- `/notifications`
- `/cases/[caseId]`
- `/assistant`

Validation:

```bash
npm run build
```
