# ATLAS Voice System

The ATLAS Voice System provides browser-native speech-to-text (STT) input and text-to-speech (TTS) output integrated directly into the authenticated Next.js chat interface.

Voice interaction operates strictly through the existing conversation and agent pipeline: spoken input is transcribed locally in the browser, submitted to the authenticated `/api/v1/chat` endpoint, and processed with the exact same security policies, credential scrubbers, and permission boundaries as typed messages.

---

## 1. Architecture

The voice system is implemented using the W3C Web Speech API standard:

- **Speech Recognition (STT):** `window.SpeechRecognition` and `window.webkitSpeechRecognition`. Transcribes spoken voice into text in real time with continuous interim results and final transcript assembly.
- **Speech Synthesis (TTS):** `window.speechSynthesis` and `window.SpeechSynthesisUtterance`. Speaks assistant messages aloud with selectable browser voices, customizable playback speed, and Markdown stripping.
- **Zero Backend Audio Streaming:** Audio processing occurs entirely within the client's browser engine. No raw audio files, audio streams, or microphone data are transmitted over the network or stored on the backend.
- **Zero New Dependencies:** Leverages native browser capabilities without heavyweight client libraries or external speech API subscriptions.

```
┌─────────────────────────────────────────────────────────────────┐
│ Browser Client (Next.js)                                         │
│                                                                 │
│  [Microphone] ──> SpeechRecognition ──> Interim & Final Text    │
│                                                   │             │
│                                                   ▼             │
│                                            Chat Input Bar       │
│                                                   │             │
│                                                   ▼             │
│                                          POST /api/v1/chat      │
│                                                   │             │
│  [Speakers]   <── SpeechSynthesis   <──  Assistant Response     │
│                     ▲ (cleanTextForSpeech)                      │
└─────────────────────┼───────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│ Backend (FastAPI)                                               │
│                                                                 │
│  Auth Verification ──> Sanitization ──> Agent ──> Tools/Policy  │
│  (Supabase JWT)      (Secret Redaction)        (Permission Engine│
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Security & Policy Enforcement

Voice input is treated as untrusted user input, following ATLAS's defense-in-depth principles:

1. **Identical Authentication:** Requests sent via voice use the user's verified Supabase JWT bearer token. Unauthenticated users cannot interact with the agent or trigger actions.
2. **Untrusted Input Boundary:** Voice transcripts are validated against input length constraints (maximum 4,000 characters) and inspected for credential-like strings before ingestion.
3. **Strict Permission Engine Execution:** Voice commands cannot bypass tool permission policies. Any tool execution requested by the agent requires policy evaluation.
4. **High-Risk Confirmation Guard:** High-risk actions (e.g., sending emails, deleting data, creating calendar events) require explicit interactive confirmation in the UI regardless of whether the prompt was spoken or typed. Voice recognition cannot simulate or bypass user confirmation tokens.
5. **Privacy by Design:** Because recognition runs through the browser's native API, raw audio is never written to backend logs, databases, or third-party storage.

---

## 3. Browser Capabilities & Graceful Degradation

The voice system performs runtime feature detection (`getVoiceCapabilities`):

| Browser | Speech Recognition (STT) | Speech Synthesis (TTS) | Experience |
| :--- | :--- | :--- | :--- |
| **Google Chrome / Chromium** | Native Support | Native Support | Full Voice In & Out |
| **Microsoft Edge** | Native Support | Native Support | Full Voice In & Out |
| **Safari / WebKit** | Unsupported / Partial | Native Support | Read-aloud active, typed input fallback |
| **Mozilla Firefox** | Unsupported | Native Support | Read-aloud active, typed input fallback |
| **Mobile Browsers** | Dependent on OS engine | Dependent on OS engine | Graceful fallback when unavailable |

When Speech Recognition is not supported:
- The microphone button displays a disabled status badge and clear tooltip explaining browser limitations.
- The chat input row remains fully operational for typed input.
- Speech synthesis and "Read aloud" features remain available if supported by the browser.

---

## 4. User Experience & Controls

### Microphone & Speech Recognition
- **Microphone Toggle:** A microphone icon in the chat input bar toggles listening state (`idle`, `listening`, `processing`).
- **Pulsing Indicator:** A pulsing recording badge and audio level indicator provide clear visual feedback while listening.
- **Interim Transcript Preview:** A floating preview panel shows real-time recognized words as the user speaks.
- **Manual Completion & Cancellation:** Users can click "Done speaking" to send immediately or "Cancel" to abort without sending.
- **Automatic Interruption:** Starting a new voice recording immediately stops any active speech synthesis output to prevent audio overlap.

### Spoken Output & Playback Controls
- **Header Audio Toggle:** A master voice toggle button in the chat header (`🔊 Voice: ON` / `🔈 Voice: OFF`) toggles auto-read behavior.
- **Active Speaking Banner:** When ATLAS is speaking, an active speaker banner appears with a direct "Stop" button.
- **Per-Message Read Aloud:** Every assistant message includes a speaker button to listen to that specific response on demand or stop playback.
- **Interruption on Navigation:** Navigating away from the chat panel or switching conversations automatically halts active speech playback.

### Markdown Sanitization for Speech (`cleanTextForSpeech`)
To ensure natural, comfortable listening, assistant messages are sanitized before speech synthesis:
- Fenced code blocks (````python ... ````) are replaced with *"Code block omitted."*
- Inline code marks, markdown formatting (`**bold**`, `*italics*`, `> quotes`, `# headers`), and bullet markers are stripped.
- Hyperlinks (`[label](url)`) are converted to just the readable label, removing raw URLs.

---

## 5. Voice Settings (`/settings`)

Users can customize voice preferences in the **Voice & Speech** section of the Settings page:

- **Auto-read Assistant Responses:** Automatically read new assistant responses aloud when received.
- **Speaking Speed (Rate):** Adjustable from `0.5x` (slower) to `2.0x` (faster) in 0.25x increments. Default is `1.0x`.
- **Voice Selection:** Dropdown populated dynamically with available system and browser voices (e.g., Google US English, Microsoft Jenny, etc.).
- **Voice Test:** A "Test voice" button plays a sample utterance with current settings before saving.
- **Persistence:** Settings are saved to `localStorage` under `atlas_voice_settings` and persist across sessions.

---

## 6. Error Handling

- **Permission Denied (`not-allowed`):** Displays a polite, dismissible notification indicating that microphone access was blocked and explaining how to enable it in browser site settings.
- **No Speech Detected (`no-speech`):** Gracefully resets to idle after a quiet timeout without showing an error dialog.
- **Network / Service Errors (`network`):** Displays a brief toast notifying the user that the speech recognition service encountered a network error.
- **Synthesis Failures:** If speech synthesis is blocked (e.g., browser autoplay restrictions), the system fails silently and resets the speaking indicator without interrupting chat.

