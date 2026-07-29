# DRAAD frontend

This Next.js application renders the DRAAD chat interface, Server-Sent Event
pipeline progress, deterministic rule findings, citations and the final
human-review or dispatch recommendation.

## Run locally

Start the FastAPI backend on port 8000, then:

```bash
npm ci
npm run dev
```

Open `http://localhost:3000`. During local development, `next.config.ts`
proxies `/api/*` to `http://localhost:8000/api/*`.

## Validate and build

```bash
npm run build
npm run start
```

The production server listens on port 3000 by default. The current rewrite is
designed for the local workshop topology; update the backend destination in
`next.config.ts` before deploying the frontend and API to separate hosts.

## Relevant files

- `app/page.tsx`: SSE client and conversation state.
- `app/components/PipelineProgress.tsx`: live agent/rule progress.
- `app/components/ResultCard.tsx`: structured dispatch result.
- `app/types.ts`: frontend response contracts.

The interface is a training aid. It does not authorize electrical work.
