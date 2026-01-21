# Olivia - YMCA Activity Assistant

An intelligent AI-powered assistant for helping YMCA members and staff find classes, check schedules, and manage enrollments.

## Features

- **Member Portal**: Browse class calendar, filter by activity type, intelligent class suggestions
- **Front Desk Staff Tool**: Command-based enrollment and schedule lookup
- **Voice Support**: Talk to Olivia using your voice (text & speech)
- **Smart Suggestions**: Intelligent fallback to nearby branches and alternative times
- **Friendly AI**: Conversational tone that feels welcoming, not pushy

## Tech Stack

- **Backend**: Python 3.11 + FastAPI
- **Frontend**: React 18 + TypeScript + Vite
- **LLM**: Ollama (local) with Llama 3.2
- **Database**: SQLite
- **Containerization**: Docker + Docker Compose

## Prerequisites

- Docker & Docker Compose
- Ollama (for local LLM) — install from https://ollama.ai
- Git

## Quick Start (Local Development)

### 1. Clone the repository
```bash
git clone git@github.com:hb-datag/Olivia.git
cd Olivia
```

### 2. Start Ollama locally
```bash
ollama pull llama3.2:3b
ollama serve
```

Ollama will run on `http://localhost:11434`

### 3. Start services with Docker Compose
```bash
docker-compose up --build
```

This starts:
- **Backend API**: http://localhost:8000 (FastAPI docs: http://localhost:8000/docs)
- **Frontend UI**: http://localhost:5173
- **Ollama**: http://localhost:11434 (already running separately)

### 4. Test the app
- Open http://localhost:5173 in your browser
- Try asking: "What's swim availability this week at my Y?"
- Toggle between "Member" and "Front Desk" modes (top-left corner)

## Project Structure

```
Olivia/
├── apps/
│   ├── backend/
│   │   ├── app/
│   │   │   ├── main.py           # FastAPI app entry point
│   │   │   ├── llm.py            # Ollama integration
│   │   │   ├── calendar_store.py # Database logic
│   │   │   └── routers/          # API endpoints
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   └── frontend/
│       ├── src/
│       │   ├── App.tsx           # Main React component
│       │   ├── lib/api.ts        # API client
│       │   └── lib/voice.ts      # Speech integration
│       ├── Dockerfile
│       └── package.json
├── configs/
│   ├── facilities.json           # Branch/location data
│   ├── class_catalog.json        # Class types & metadata
│   ├── branch_proximity.json     # Nearby branches + drive times
│   ├── member_profiles.json      # Member home branches
│   └── hours.json                # Operating hours
├── docker-compose.yml
├── .env.example
├── .env.local
└── README.md
```

## Environment Variables

See `.env.example` for all options. For local development, `.env.local` is used.

### Key Variables
- `OLIVIA_OLLAMA_URL` — Ollama server URL (e.g., `http://localhost:11434`)
- `OLIVIA_OLLAMA_MODEL` — Model to use (e.g., `llama3.2:3b`)
- `VITE_API_BASE_URL` — Backend URL for frontend (e.g., `http://localhost:8000`)

## Development Workflow

### Making changes
Both services auto-reload on file changes:
- **Backend**: Uvicorn auto-reloads on `.py` file changes
- **Frontend**: Vite HMR reloads on `.tsx` file changes

### Viewing logs
```bash
docker-compose logs -f backend
docker-compose logs -f frontend
docker-compose logs -f ollama
```

### Stopping services
```bash
docker-compose down
```

### Full rebuild
```bash
docker-compose down
docker-compose up --build
```

## Testing the Chat Endpoint

```bash
# Check backend health
curl http://localhost:8000/api/v1/health

# Test chat
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "test_session",
    "message": "What swim classes are available this week?",
    "ui_context": {
      "selected_branch_ids": [],
      "selected_buckets": ["swim"],
      "only_has_spots": true,
      "member_id": "demo_member",
      "user_group": "member"
    }
  }'
```

## Database

SQLite database is stored at `apps/backend/data/olivia.db`. It initializes automatically on first run with:
- Branch locations
- Class definitions
- Sample session schedule (21 days of synthetic data)

To reset the database, delete the `.db` file and restart:
```bash
rm apps/backend/data/olivia.db
docker-compose restart backend
```

## Future Deployment

When ready to deploy to cloud (olivia-dev.xtainable.com, olivia-uat.xtainable.com):

1. Update DNS to point to your server
2. Modify `docker-compose.yml` and `.env.dev` for cloud host
3. Use CI/CD (GitHub Actions) to auto-deploy on push
4. Set up SSL/TLS with Let's Encrypt

See `docs/DEPLOYMENT.md` for detailed cloud setup guide (coming soon).

## Troubleshooting

### Backend won't connect to Ollama
- Make sure Ollama is running: `ollama serve`
- On Windows/Mac with Docker Desktop, use `host.docker.internal:11434`
- On Linux, you may need to use the actual machine IP or run Ollama in Docker too

### Frontend can't reach backend
- Check backend is running: `curl http://localhost:8000/api/v1/health`
- Verify `VITE_API_BASE_URL` in frontend environment

### No classes showing
- Check database initialized: `ls apps/backend/data/olivia.db`
- Verify `configs/` JSON files exist and are valid
- Check backend logs: `docker-compose logs -f backend`

### LLM responses are slow
- Ensure Ollama model is fully loaded: `ollama list`
- Check available RAM/VRAM
- Consider using a smaller model (e.g., `neural-chat:7b-v3.1-q4_K_M`)

## Contributing

1. Create a feature branch: `git checkout -b feature/your-feature`
2. Make your changes
3. Test locally with Docker Compose
4. Push and create a PR

## License

[Your License Here]

## Contact

Questions? Reach out to [your contact info]
