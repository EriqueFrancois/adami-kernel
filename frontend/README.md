## Purpose

This is the **Web Console** for `adami-kernel`. It provides a browser UI for inspecting the kernel state (skills, market, memory/workflows) and interacting with the backend.

## Key files

- `index.html`: Vite entry HTML.
- `vite.config.ts`: Vite configuration.
- `src/main.tsx`: React bootstrap.
- `src/App.tsx`: main app shell / routing.
- `src/Dashboard.tsx`: dashboard view.
- `src/Market.tsx`: skill market view.
- `src/MemoryPanel.tsx`: memory/workflow inspection panel.
- `src/SkillsPanel.tsx`: skills panel.

## Key subdirectories

- `src/`: React application code.
- `public/`: static public assets.

## Development

```bash
cd frontend
npm install
npm run dev
```

## Operational notes

- `frontend/node_modules/` is vendor-managed and should not be edited manually.
- The backend is started by the Python kernel (`src/adami_kernel/web/`); this frontend expects it to be running.

