# ATLAS Frontend Foundation

**Frontend foundation** — A clean, production-ready interface with Phase 4 conversational chat integration for ATLAS.

## Overview

This is the **frontend foundation only**. It provides:

- ✅ Application shell with sidebar navigation
- ✅ Home page with chat interface
- ✅ Activity page with operation tracking
- ✅ Memory page for context management
- ✅ Connected Services page (integration placeholders)
- ✅ Settings page (configuration placeholders)
- ✅ Responsive design (desktop, tablet, mobile)
- ✅ Backend health check integration
- ✅ Type-safe architecture with TypeScript
- ✅ Supabase Auth email magic-link sign-in
- ✅ Clean, professional UI

## Not Included

This phase deliberately does **not** include:

- Database or persistent memory
- External service integrations (Google, GitHub, etc.)
- Tool execution or permission engine (chat responses do not execute actions)
- Voice functionality (UI placeholder only)
- Workflow automation

The architecture is designed to make it easy to add these features in later phases.

## Quick Start

### Prerequisites

- Node.js 18+
- npm 9+

### Setup

```bash
cd frontend

# Install dependencies
npm install

# Create environment file
cp .env.example .env.local
# Set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY.
# Set NEXT_PUBLIC_API_BASE_URL if the backend is not at http://127.0.0.1:8001.

# Start development server
npm run dev
```

The app runs on **http://localhost:3000**.
Configure the matching Supabase Auth redirect URLs and backend JWT verification
as described in [docs/authentication.md](../docs/authentication.md).

### Build

```bash
npm run build      # Production build
npm start          # Start production server
npm run lint       # ESLint check
```

## Architecture

### File Structure

```
frontend/
├── app/                           # Next.js app router pages
│   ├── page.tsx                  # Home (chat interface)
│   ├── activity/page.tsx         # Activity tracking
│   ├── memory/page.tsx           # Memory management
│   ├── connected-services/page.tsx
│   ├── settings/page.tsx         # Settings
│   ├── layout.tsx                # Root layout with AppShell
│   └── globals.css               # Global styles
│
├── components/
│   ├── layout/
│   │   └── app-shell.tsx         # Main navigation shell
│   ├── chat/
│   │   ├── chat-panel.tsx        # Chat interface container
│   │   └── chat-message.tsx      # Individual message
│   └── ui/
│       ├── activity-indicator.tsx # Loading/status states
│       └── confirmation-dialog.tsx # Confirmation modal
│
├── services/
│   └── api.ts                    # Backend API client
│
├── types/
│   └── index.ts                  # Shared TypeScript types
│
├── public/                       # Static assets
├── package.json
├── tsconfig.json
└── .env.example
```

## Backend Integration

### API Client (`services/api.ts`)

- Centralized API configuration
- Environment variable support: `NEXT_PUBLIC_API_BASE_URL`
- Chat: `POST /api/v1/chat`
- Type-safe request handling
- Health check integration

Default backend: **http://127.0.0.1:8001** (configurable via env)

### Routes Used

- `GET /api/v1/health` — Backend health check
- `POST /api/v1/chat` — Conversational assistant response
- Ready for: chat, activities, memory, services (future phases)

## Styling

- **No external UI libraries** (pure CSS)
- Modern design with smooth transitions
- Responsive grid layouts
- Accessible color contrast
- Calm, professional palette

## Responsive Design

The interface adapts to:
- Desktop (1200px+)
- Tablet (640px–1199px)
- Mobile (<640px)

## Type Safety

All components use TypeScript with strict mode.

## Environment Variables

Create `.env.local`:

```env
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

## Development

```bash
npm run dev    # Start dev server (hot reload)
npm run build  # Build for production
npm run lint   # Check code quality
```

---

**Phase 2 Complete** ✅

Chat is connected to the Phase 4 basic agent. Other integrations and tool execution remain future work.
