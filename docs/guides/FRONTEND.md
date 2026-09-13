# Frontend

The Nally web UI is a single-page application built with vanilla HTML, CSS, and JavaScript — no build tools or frameworks. As of commit `f3f75e8` the frontend is modular: `index.html` is a lightweight shell that loads 10 external stylesheets and 22 external JS modules.

## File Structure

```
web/
├── index.html        # HTML shell — loads CSS + JS modules (no inline code)
├── css/              # 10 modular stylesheets
│   ├── base.css      #   base layout + theme variables
│   ├── orb.css       #   WebGL orb
│   ├── drawer.css    #   chat drawer
│   ├── toolcards.css #   tool call/result cards
│   ├── mobile.css    #   responsive layout
│   ├── settings.css  #   settings panel
│   ├── auth.css      #   login gate + auth modal
│   ├── diff.css      #   diff viewer
│   ├── trace.css     #   execution trace panel
│   └── command.css   #   command palette
├── js/               # 22 ES5 modules (loaded in dependency order)
│   ├── config.js     #   shared config / state providers
│   ├── app.js        #   entry point — bootstraps the UI
│   ├── auth.js       #   login/token handling
│   ├── authmodal.js  #   OAuth modal
│   ├── chat.js       #   message list + input
│   ├── command.js    #   command palette
│   ├── diff.js       #   file diff viewer
│   ├── dom.js        #   DOM helpers
│   ├── drawer.js     #   chat drawer chrome
│   ├── hotkeys.js    #   keyboard shortcuts
│   ├── markdown.js   #   marked + DOMPurify rendering, highlight.js hook
│   ├── orb.js        #   animated WebGL background
│   ├── services.js   #   MCP/service status grid
│   ├── settings.js   #   settings panel behavior
│   ├── sse.js        #   SSE client (POST /api/chat)
│   ├── state.js      #   shared app state
│   ├── sync.js       #   multi-tab broadcast channel sync
│   ├── think.js      #   thought panel
│   ├── toolcards.js  #   tool cards rendering
│   ├── trace.js      #   trace panel
│   ├── voice.js      #   mic input / voice pipeline
│   └── websocket.js  #   WS client (/ws/{session_id})
├── marked.min.js     # Markdown parser (v4.3.0, bundled)
├── purify.min.js     # HTML sanitizer (DOMPurify, bundled)
├── nally-ws.js       # WebSocket + SSE client helper
└── mvp/              # Three.js 3D face-avatar demo (separate from the main UI)
    ├── index.html
    ├── css/style.css
    ├── js/face-tracker.js
    ├── js/lipsync.js
    ├── models/facecap.glb
    └── vendor/       # vendored three.js + GLTF loaders
```

## Architecture

`index.html` contains only structure. Styling lives in `web/css/` (loaded in `<head>`), and behavior lives in `web/js/` modules loaded at the end of `<body>`:

```
index.html (shell)
├── <head>           # Google Fonts (Space Grotesk, JetBrains Mono),
│                    # highlight.js theme (CDN), Lucide icons (CDN)
│                    # 10 <link> stylesheets → /static/css/
│                    # marked, purify, nally-ws scripts
├── <body>
│   ├── Command Palette  # keyboard command search
│   ├── Login Overlay    # Bearer token gate (localStorage)
│   ├── Root             # Orb (WebGL + Canvas 2D), status, thought panel
│   ├── Chat Drawer      # messages, input, mic button, resize handles
│   ├── Diff Panel       # file diff viewer
│   ├── Settings         # MCP/services, themes, API, emergency, lock, about
│   └── Auth Modal       # OAuth flow modal
└── <script>         # 22 JS modules → /static/js/ (dependency order)
```

The JS modules are plain `<script>` tags (no ES modules/imports) sharing globals; order matters — deps load first, `app.js` boots the app.

## Key Features

- **SSE Streaming**: Real-time response streaming via `POST /api/chat`
- **WebSocket**: Bidirectional chat via `WS /ws/{session_id}` (lower latency)
- **Tool Cards**: Visual display of tool calls and results
- **Multi-tab Sync**: Broadcast channel keeps tabs in sync
- **Voice Input**: Browser mic → STT → agent → TTS (via WebSocket)
- **Markdown Rendering**: `marked.min.js` + DOMPurify for formatted, sanitized responses
- **Syntax Highlighting**: highlight.js (CDN) colors code blocks in message output
- **Diff Viewer**: Dedicated panel for file diffs returned by tools
- **Command Palette**: Keyboard-driven command search
- **Theme System**: Theme swatches, compact mode, runtime customization

## How It Works

### Page Load

1. `index.html` shell loads; the `web/css/` stylesheets and `web/js/` modules are fetched
2. Checks for stored Bearer token in `localStorage`
3. If no token → show login gate
4. If token exists → connect to backend, load history

### Sending a Message

1. User types message, presses Enter
2. Message sent via `POST /api/chat` (SSE) or WebSocket
3. SSE events stream back: `stream_chunk`, `tool_call`, `tool_result`, `stream_done`
4. UI updates in real-time as chunks arrive

### SSE Event Handling

```javascript
// Event types received from /api/chat
"run_id"               // Execution trace ID
"stream_chunk"         // Partial text — append to current message
"stream_done"          // Response complete
"thought"              // Internal reasoning
"tool_call"            // Tool being invoked — show tool card
"tool_result"           // Tool completed — update tool card
"confirmation_required" // Waiting for approval — show approve/deny buttons
"verification"         // Claim verification result
"system_notice"        // System message (time budget, limits)
```

### WebSocket Mode

For lower latency, use WebSocket instead of SSE:

```javascript
// From nally-ws.js
const ws = new WebSocket(`ws://localhost:5000/ws/web:default?token=${token}`);
ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    // Handle same event types as SSE
};
```

### Voice Input

1. User clicks mic button (or uses `/voice` command)
2. Browser captures audio via `MediaRecorder` (webm format)
3. Audio sent via WebSocket to `_process_voice()` handler
4. Backend: webm → ffmpeg → PCM → STT (Faster-Whisper) → agent → TTS → WAV → base64
5. Audio response played back in browser

## Theming

The UI supports runtime theme customization. The settings panel is organized into sections (markup in `index.html`, behavior in `web/js/settings.js`):

- **MCP / Plugins**: Service connection status grid (via `services.js`)
- **Themes / Appearance**: Theme swatches — Midnight (default), Emerald, Crimson, Ocean, Gold — plus a **Compact** toggle for reduced spacing
- **API**: Read-only provider / model display
- **Emergency**: "Stop All Operations" button (aborts in-flight work)
- **Lock Mode**: Lock UI toggle (hides/relocks the interface)
- **About**: Backend status and uptime

Settings persist in `localStorage`.

## Modifying the UI

The frontend is modular:

1. Markup lives in `index.html`
2. Styles live in `web/css/` (`base.css` holds the theme CSS variables)
3. Behavior lives in `web/js/` modules, loaded in dependency order at the end of `<body>`
4. No build step needed — just refresh the browser

### Adding a New SSE Event Type

1. Add handler in the event processing loop in `web/js/sse.js` (and `web/js/websocket.js` for WS events)
2. Update the corresponding Python emit in `nally/agent/graph.py`
3. Add to the SSE event table in [API.md](API.md)

## Dependencies

| Library | Version | Purpose | CDN |
|---------|---------|---------|-----|
| marked | 4.3.0 | Markdown → HTML | No (bundled) |
| DOMPurify | latest | XSS sanitization | No (bundled) |
| Lucide | latest | Icons | CDN (`unpkg.com`) |
| highlight.js | 11 | Syntax highlighting | CDN (`cdn.jsdelivr.net`) |
| Google Fonts | — | Space Grotesk, JetBrains Mono | CDN (`fonts.googleapis.com`) |

## Browser Support

- Chrome/Edge: Full support (WebGL orb, voice)
- Firefox: Full support (Canvas 2D fallback for orb)
- Safari: Full support (Canvas 2D fallback, no voice on older versions)
- Mobile: Responsive layout, touch-friendly
