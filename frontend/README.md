# Signar Frontend

The Signar dashboard is a React and Vite single-page application deployed on
Vercel. Production data is read from the Railway ThreadRadar API.

## Local Development

```bash
npm install
npm run dev
```

The frontend defaults to the production API:

```text
https://signar-production.up.railway.app
```

To use a local or alternate backend, create `frontend/.env.local`:

```bash
VITE_API_BASE_URL=http://localhost:8000
```

## Vercel Deployment

Create a Vercel project named `signar-threadradar` and set its root directory
to `frontend`. Vercel detects Vite automatically and uses:

- Build command: `npm run build`
- Output directory: `dist`

`vercel.json` rewrites direct routes such as `/ticker/SUUN` to the SPA entry
point. `VITE_API_BASE_URL` may be configured in Vercel if the Railway API URL
changes; otherwise the production Railway URL is used by default.
