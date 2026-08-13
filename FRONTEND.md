# Frontend

The Nally web UI is a single-page application built with vanilla HTML, CSS, and JavaScript — no build tools or frameworks.

## File Structure

```
web/
├── index.html        # Main UI — all CSS/JS inline
├── marked.min.js     # Markdown parser (v4.3.0)
├── nally-ws.js       # WebSocket + SSE client
└── purify.min.js     # HTML sanitizer (DOMPurify)
```

## Architecture

```
index.html
├── <style>          # All CSS inline (theming, layout, animations)
├── <body>
│   ├── Orb          # Animated WebGL + Canvas 2D background
│   ├── Chat Drawer  # Message list, input, tool cards
│   ├── Settings     # Accent colors, font size, compact mode
│   └── Login Gate   # Bearer token entry
└── <script>         # All JS inline (chat logic, SSE, rendering)
```

## Key Features

- **SSE Streaming**: Real-time response streaming via `POST /api/chat`
- **WebSocket**: Bidirectional chat via `WS /ws/{session_id}` (lower latency)
- **Tool Cards**: Visual display of tool calls and results
- **Multi-tab Sync**: Broadcast channel keeps tabs in sync
- **Voice Input**: Browser mic → STT → agent → TTS (via WebSocket)
- **Markdown Rendering**: `marked.min.js` for formatted responses
- **Theme System**: Accent colors, font size, compact mode

## How It Works

### Page Load

1. `index.html` loads with all CSS/JS inline
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

The UI supports runtime theme customization:

- **Accent colors**: Purple (default), blue, green, red, orange
- **Font size**: Slider control (12px–20px)
- **Compact mode**: Reduced spacing for dense layouts

Settings persist in `localStorage`.

## Modifying the UI

Since everything is inline in `index.html`:

1. Edit `index.html` directly
2. No build step needed — just refresh the browser
3. CSS variables control theming: `--accent`, `--bg`, `--text`, etc.

### Adding a New SSE Event Type

1. Add handler in the event processing loop in `index.html`
2. Update the corresponding Python emit in `nally/agent/graph.py`
3. Add to the SSE event table in [API.md](API.md)

## Dependencies

| Library | Version | Purpose | CDN |
|---------|---------|---------|-----|
| marked | 4.3.0 | Markdown → HTML | No (bundled) |
| DOMPurify | latest | XSS sanitization | No (bundled) |
| Lucide | latest | Icons | CDN |

## Browser Support

- Chrome/Edge: Full support (WebGL orb, voice)
- Firefox: Full support (Canvas 2D fallback for orb)
- Safari: Full support (Canvas 2D fallback, no voice on older versions)
- Mobile: Responsive layout, touch-friendly
