# Production Webapp Scaffold

This folder is the production-direction replacement for the Streamlit frontend.

Target stack:
- Next.js App Router
- typed API client against FastAPI
- enterprise auth handled at backend / OIDC layer
- responsive operator dashboard UI

Current state:
- dashboard shell
- government-style layout
- mock queue table
- ready for API integration

Run locally after installing dependencies:

```bash
cd webapp
npm install
npm run dev
```
