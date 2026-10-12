import type { VoiceCapabilities, VoiceSettings } from "@/types";

const VOICE_SETTINGS_STORAGE_KEY = "atlas_voice_settings";

export const DEFAULT_VOICE_SETTINGS: VoiceSettings = {
  autoSpeak: false,
  rate: 1.0,
  pitch: 1.0,
  voiceURI: null,
};

export function isSpeechRecognitionSupported(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  return Boolean(
    window.SpeechRecognition || window.webkitSpeechRecognition,
  );
}

export function isSpeechSynthesisSupported(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  return typeof window.speechSynthesis !== "undefined" && typeof SpeechSynthesisUtterance !== "undefined";
}

export function getVoiceCapabilities(): VoiceCapabilities {
  return {
    recognitionSupported: isSpeechRecognitionSupported(),
    synthesisSupported: isSpeechSynthesisSupported(),
  };
}

export function getVoiceSettings(): VoiceSettings {
  if (typeof window === "undefined") {
    return DEFAULT_VOICE_SETTINGS;
  }
  try {
    const raw = localStorage.getItem(VOICE_SETTINGS_STORAGE_KEY);
    if (!raw) {
      return DEFAULT_VOICE_SETTINGS;
    }
    const parsed = JSON.parse(raw) as Partial<VoiceSettings>;
    return {
      autoSpeak: typeof parsed.autoSpeak === "boolean" ? parsed.autoSpeak : DEFAULT_VOICE_SETTINGS.autoSpeak,
      rate: typeof parsed.rate === "number" && parsed.rate >= 0.5 && parsed.rate <= 2.0 ? parsed.rate : DEFAULT_VOICE_SETTINGS.rate,
      pitch: typeof parsed.pitch === "number" && parsed.pitch >= 0.5 && parsed.pitch <= 1.5 ? parsed.pitch : DEFAULT_VOICE_SETTINGS.pitch,
      voiceURI: typeof parsed.voiceURI === "string" ? parsed.voiceURI : null,
    };
  } catch {
    return DEFAULT_VOICE_SETTINGS;
  }
}

export function saveVoiceSettings(updates: Partial<VoiceSettings>): VoiceSettings {
  const current = getVoiceSettings();
  const next: VoiceSettings = {
    ...current,
    ...updates,
  };
  if (typeof window !== "undefined") {
    try {
      localStorage.setItem(VOICE_SETTINGS_STORAGE_KEY, JSON.stringify(next));
    } catch {
      // Storage unavailable or quota exceeded; fallback gracefully
    }
  }
  return next;
}

/**
 * Normalizes assistant message text for natural speech synthesis.
 * Strips code fences, links, markdown markers, and excess whitespace.
 */
export function cleanTextForSpeech(text: string): string {
  if (!text) {
    return "";
  }
  return (
    text
      // Remove fenced code blocks
      .replace(/```[\s\S]*?```/g, "Code block omitted.")
      // Remove inline code
      .replace(/`([^`]+)`/g, "$1")
      // Remove markdown links [text](url) -> text
      .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
      // Remove headings (# Heading -> Heading)
      .replace(/#{1,6}\s+/g, "")
      // Remove bold / italic markers
      .replace(/(\*\*|__)(.*?)\1/g, "$2")
      .replace(/(\*|_)(.*?)\1/g, "$2")
      // Remove blockquotes (> quote -> quote)
      .replace(/^\s*>\s+/gm, "")
      // Remove list markers (- item -> item)
      .replace(/^\s*[-*+]\s+/gm, "")
      .replace(/^\s*\d+\.\s+/gm, "")
      // Remove multiple whitespace/newlines
      .replace(/\s+/g, " ")
      .trim()
  );
}

