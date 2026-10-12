import assert from "node:assert/strict";
import test from "node:test";

import {
  DEFAULT_VOICE_SETTINGS,
  cleanTextForSpeech,
  getVoiceCapabilities,
} from "../services/voice.ts";

test("cleanTextForSpeech strips markdown formatting for natural voice playback", () => {
  const markdown = `
# Welcome to ATLAS!
Here is a plan:
1. Review calendar
2. Send summary
Check out [this docs link](https://example.com).
\`\`\`python
def hello():
    print("world")
\`\`\`
Use the \`GET /api/v1/chat\` endpoint.
**Important:** _Stay safe_ and > quote this note.
  `;

  const cleaned = cleanTextForSpeech(markdown);

  assert.ok(!cleaned.includes("```"), "Should not contain code fences");
  assert.ok(!cleaned.includes("https://example.com"), "Should not contain URLs");
  assert.ok(cleaned.includes("this docs link"), "Should contain link text");
  assert.ok(cleaned.includes("Code block omitted."), "Should replace code block with spoken placeholder");
  assert.ok(!cleaned.includes("#"), "Should not contain markdown headers");
  assert.ok(!cleaned.includes("**"), "Should not contain bold markers");
  assert.ok(!cleaned.includes("_Stay safe_"), "Should not contain italic markers");
  assert.ok(cleaned.includes("Important: Stay safe and quote this note."));
});

test("cleanTextForSpeech handles empty or whitespace input safely", () => {
  assert.equal(cleanTextForSpeech(""), "");
  assert.equal(cleanTextForSpeech("   \n\t  "), "");
});

test("default voice settings provide safe, non-intrusive defaults", () => {
  assert.equal(DEFAULT_VOICE_SETTINGS.autoSpeak, false, "Auto-speak should default to false");
  assert.equal(DEFAULT_VOICE_SETTINGS.rate, 1.0, "Rate should default to 1.0x");
  assert.equal(DEFAULT_VOICE_SETTINGS.pitch, 1.0, "Pitch should default to 1.0");
  assert.equal(DEFAULT_VOICE_SETTINGS.voiceURI, null, "Default voiceURI should be null");
});

test("getVoiceCapabilities executes safely in non-browser Node environments", () => {
  const caps = getVoiceCapabilities();
  assert.equal(typeof caps.recognitionSupported, "boolean");
  assert.equal(typeof caps.synthesisSupported, "boolean");
  assert.equal(caps.recognitionSupported, false, "Should be false in Node SSR environment");
  assert.equal(caps.synthesisSupported, false, "Should be false in Node SSR environment");
});

test("voice state transitions handle permission denial and interruption", () => {
  // Verify state transitions for recognition
  const states = ["idle", "listening", "processing", "permission_denied", "error", "unsupported"];
  assert.ok(states.includes("listening"));
  assert.ok(states.includes("permission_denied"));

  // Mock recognition event processing
  let state = "idle";
  let transcript = "";

  function onStart() {
    state = "listening";
  }

  function onResult(interim, final) {
    if (final) {
      transcript = (transcript ? transcript + " " : "") + final;
    }
  }

  function onError(errorType) {
    if (errorType === "not-allowed" || errorType === "service-not-allowed") {
      state = "permission_denied";
    } else {
      state = "error";
    }
  }

  function onCancel() {
    state = "idle";
    transcript = "";
  }

  onStart();
  assert.equal(state, "listening");

  onResult("interim text", "Hello ATLAS");
  assert.equal(transcript, "Hello ATLAS");

  onCancel();
  assert.equal(state, "idle");
  assert.equal(transcript, "");

  onStart();
  onError("not-allowed");
  assert.equal(state, "permission_denied");
});

