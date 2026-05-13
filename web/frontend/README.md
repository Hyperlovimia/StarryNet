# StarryNet Frontend

This directory contains the standalone web GUI scaffold for StarryNet.

## Development

Start the backend:

```bash
uvicorn web.backend.app.main:app --reload
```

Start the frontend:

```bash
cd web/frontend
npm install
npm run dev
```

The frontend expects:

- `VITE_API_BASE_URL` pointing at the FastAPI backend
- `VITE_USER_ID` for the required `X-User-Id` header

## Current scope

- experiments list
- experiment detail
- run detail
- topology snapshot
- events list
- tasks list and output preview
