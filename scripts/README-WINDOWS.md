# Run CareSync AI on Windows from VS Code

1. Install Python 3.12 (tick **Add Python to PATH**) and Node.js LTS.
2. Open the **CareSync-AI project root folder** in VS Code.
3. Press **F5** and select **CareSync AI: Run website (F5)** if prompted.
4. The launcher creates the API virtual environment, installs backend/frontend packages, starts FastAPI and Next.js in separate PowerShell terminals, waits for both, and VS Code opens `http://localhost:3000`.

The local launcher uses SQLite and local private file storage so Docker/PostgreSQL/Redis/MinIO are not required for a local demo. It seeds demo users. This is for local development only, not public/production deployment.

- Website: http://localhost:3000
- API health: http://localhost:8000/health
- API docs: http://localhost:8000/docs

Demo password: `CareSyncDemo!2026` (demo accounts are listed in `START_HERE.md`).

To stop the app, close the two service terminals or press Ctrl+C in each. If ports 3000 or 8000 are already occupied, stop the old process before running again.
