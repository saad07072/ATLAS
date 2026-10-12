"use client";

import type { JSX } from "react";

import { useVoice } from "@/hooks/use-voice";
import type { SettingGroup } from "@/types";

const settingGroups: SettingGroup[] = [
  {
    id: "account",
    title: "Account",
    description: "Identity and profile information for future user management.",
    state: "Placeholder",
  },
  {
    id: "appearance",
    title: "Appearance",
    description: "Theme and display preferences for a calm, focused experience.",
    state: "Theme ready",
  },
  {
    id: "notifications",
    title: "Notifications",
    description: "Delivery preferences for reminders, approvals, and summaries.",
    state: "Planned",
  },
  {
    id: "privacy",
    title: "Privacy",
    description: "Data handling boundaries and consent controls for future phases.",
    state: "Draft",
  },
  {
    id: "integrations",
    title: "Connected services",
    description: "Status and configuration for external platforms linked later.",
    state: "Active",
  },
];

export default function SettingsPage(): JSX.Element {
  const {
    isRecognitionSupported,
    isSynthesisSupported,
    settings: voiceSettings,
    voices,
    speak,
    stopSpeaking,
    isSpeaking,
    toggleAutoSpeak,
    setVoiceRate,
    setVoiceURI,
  } = useVoice();

  return (
    <div className="page-shell">
      <header className="page-header">
        <div>
          <p className="eyebrow">Settings</p>
          <h2>System preferences</h2>
        </div>
      </header>

      <section className="settings-grid" aria-label="Settings categories">
        {/* Voice & Speech Interaction Settings Card */}
        <article className="setting-card">
          <div className="setting-card-header">
            <h3>Voice &amp; Speech</h3>
            <span className="meta-pill">
              {isRecognitionSupported && isSynthesisSupported
                ? "Full support"
                : isRecognitionSupported || isSynthesisSupported
                  ? "Partial support"
                  : "Unavailable"}
            </span>
          </div>
          <p>
            Configure browser-native speech recognition for hands-free input and
            speech synthesis for spoken responses.
          </p>

          <div className="setting-voice-controls">
            <div className="voice-control-row">
              <span>Speech recognition (Microphone):</span>
              <span className={`status-badge ${isRecognitionSupported ? "connected" : "disconnected"}`}>
                {isRecognitionSupported ? "Supported" : "Not supported"}
              </span>
            </div>

            <div className="voice-control-row">
              <span>Speech synthesis (Speaker):</span>
              <span className={`status-badge ${isSynthesisSupported ? "connected" : "disconnected"}`}>
                {isSynthesisSupported ? "Supported" : "Not supported"}
              </span>
            </div>

            {isSynthesisSupported && (
              <>
                <div className="voice-control-row">
                  <label htmlFor="voice-auto-speak">
                    Auto-read assistant responses:
                  </label>
                  <input
                    id="voice-auto-speak"
                    type="checkbox"
                    checked={voiceSettings.autoSpeak}
                    onChange={() => toggleAutoSpeak()}
                  />
                </div>

                <div className="voice-control-row">
                  <label htmlFor="voice-rate-select">Speech speed:</label>
                  <select
                    id="voice-rate-select"
                    value={voiceSettings.rate}
                    onChange={(event) => setVoiceRate(parseFloat(event.target.value))}
                  >
                    <option value="0.8">0.8x (Slower)</option>
                    <option value="1.0">1.0x (Normal)</option>
                    <option value="1.2">1.2x (Faster)</option>
                    <option value="1.5">1.5x (Fast)</option>
                  </select>
                </div>

                {voices.length > 0 && (
                  <div className="voice-control-row">
                    <label htmlFor="voice-selection-select">Voice:</label>
                    <select
                      id="voice-selection-select"
                      value={voiceSettings.voiceURI ?? ""}
                      onChange={(event) =>
                        setVoiceURI(event.target.value ? event.target.value : null)
                      }
                    >
                      <option value="">Default browser voice</option>
                      {voices.map((v) => (
                        <option key={v.voiceURI} value={v.voiceURI}>
                          {v.name} ({v.lang})
                        </option>
                      ))}
                    </select>
                  </div>
                )}

                <div className="voice-control-row">
                  <span>Test speech output:</span>
                  <button
                    type="button"
                    className="ghost-button"
                    onClick={() => {
                      if (isSpeaking) {
                        stopSpeaking();
                      } else {
                        speak("Hello! I am ATLAS, your autonomous task and life assistant.");
                      }
                    }}
                  >
                    {isSpeaking ? "Stop testing" : "Test voice"}
                  </button>
                </div>
              </>
            )}
          </div>
        </article>

        {settingGroups.map((setting) => (
          <article key={setting.id} className="setting-card">
            <div className="setting-card-header">
              <h3>{setting.title}</h3>
              <span className="meta-pill">{setting.state}</span>
            </div>
            <p>{setting.description}</p>
          </article>
        ))}
      </section>
    </div>
  );
}
