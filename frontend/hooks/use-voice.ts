"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  cleanTextForSpeech,
  getVoiceSettings,
  isSpeechRecognitionSupported,
  isSpeechSynthesisSupported,
  saveVoiceSettings,
} from "@/services/voice";
import type {
  SpeechRecognitionErrorEvent,
  SpeechRecognitionEvent,
  SpeechRecognitionInstance,
  VoiceRecognitionState,
  VoiceSettings,
} from "@/types";

export interface UseVoiceReturn {
  // Capabilities
  isRecognitionSupported: boolean;
  isSynthesisSupported: boolean;

  // Recognition state
  recognitionState: VoiceRecognitionState;
  interimTranscript: string;
  finalTranscript: string;
  recognitionError: string | null;

  // Recognition controls
  startListening: (onTranscriptReady?: (transcript: string) => void) => void;
  stopListening: () => void;
  cancelListening: () => void;
  clearRecognitionError: () => void;

  // Synthesis state
  isSpeaking: boolean;
  isPaused: boolean;
  speakingMessageId: string | null;
  settings: VoiceSettings;
  voices: SpeechSynthesisVoice[];

  // Synthesis controls
  speak: (text: string, messageId?: string) => void;
  stopSpeaking: () => void;
  pauseSpeaking: () => void;
  resumeSpeaking: () => void;
  toggleAutoSpeak: () => void;
  setVoiceRate: (rate: number) => void;
  setVoiceURI: (uri: string | null) => void;
}

export function useVoice(): UseVoiceReturn {
  const [isRecognitionSupported] = useState<boolean>(isSpeechRecognitionSupported);
  const [isSynthesisSupported] = useState<boolean>(isSpeechSynthesisSupported);
  const [recognitionState, setRecognitionState] =
    useState<VoiceRecognitionState>(() =>
      isSpeechRecognitionSupported() ? "idle" : "unsupported",
    );
  const [interimTranscript, setInterimTranscript] = useState("");
  const [finalTranscript, setFinalTranscript] = useState("");
  const [recognitionError, setRecognitionError] = useState<string | null>(null);

  const [isSpeaking, setIsSpeaking] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const [speakingMessageId, setSpeakingMessageId] = useState<string | null>(null);
  const [settings, setSettings] = useState<VoiceSettings>(getVoiceSettings);
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([]);

  const activeRecognitionRef = useRef<SpeechRecognitionInstance | null>(null);
  const onTranscriptReadyRef = useRef<((transcript: string) => void) | undefined>(
    undefined,
  );
  const accumulatedFinalRef = useRef("");

  // Load available speech synthesis voices on mount
  useEffect(() => {
    if (typeof window !== "undefined" && typeof window.speechSynthesis !== "undefined") {
      const loadVoices = (): void => {
        const available = window.speechSynthesis.getVoices();
        setVoices(available);
      };
      loadVoices();
      if (typeof window.speechSynthesis.onvoiceschanged !== "undefined") {
        window.speechSynthesis.onvoiceschanged = loadVoices;
      }
    }
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (activeRecognitionRef.current) {
        try {
          activeRecognitionRef.current.abort();
        } catch {
          // Ignore cleanup errors
        }
        activeRecognitionRef.current = null;
      }
      if (typeof window !== "undefined" && typeof window.speechSynthesis !== "undefined") {
        window.speechSynthesis.cancel();
      }
    };
  }, []);

  const clearRecognitionError = useCallback((): void => {
    setRecognitionError(null);
    if (recognitionState === "error" || recognitionState === "permission_denied") {
      setRecognitionState("idle");
    }
  }, [recognitionState]);

  const cancelListening = useCallback((): void => {
    if (activeRecognitionRef.current) {
      try {
        activeRecognitionRef.current.abort();
      } catch {
        // Ignore
      }
      activeRecognitionRef.current = null;
    }
    setInterimTranscript("");
    setFinalTranscript("");
    accumulatedFinalRef.current = "";
    setRecognitionState("idle");
    setRecognitionError(null);
  }, []);

  const stopListening = useCallback((): void => {
    if (activeRecognitionRef.current) {
      try {
        activeRecognitionRef.current.stop();
      } catch {
        // Ignore
      }
    }
  }, []);

  const startListening = useCallback(
    (onTranscriptReady?: (transcript: string) => void): void => {
      if (!isSpeechRecognitionSupported()) {
        setRecognitionState("unsupported");
        setRecognitionError("Speech recognition is not supported in this browser.");
        return;
      }

      // Stop any ongoing speech playback before listening
      if (typeof window !== "undefined" && typeof window.speechSynthesis !== "undefined") {
        window.speechSynthesis.cancel();
        setIsSpeaking(false);
        setIsPaused(false);
        setSpeakingMessageId(null);
      }

      // Abort any existing recognition instance
      if (activeRecognitionRef.current) {
        try {
          activeRecognitionRef.current.abort();
        } catch {
          // Ignore
        }
      }

      onTranscriptReadyRef.current = onTranscriptReady;
      accumulatedFinalRef.current = "";
      setInterimTranscript("");
      setFinalTranscript("");
      setRecognitionError(null);

      const SpeechRec =
        window.SpeechRecognition || window.webkitSpeechRecognition;
      if (!SpeechRec) {
        setRecognitionState("unsupported");
        return;
      }

      try {
        const recognition = new SpeechRec();
        activeRecognitionRef.current = recognition;
        recognition.continuous = true;
        recognition.interimResults = true;
        recognition.lang =
          typeof navigator !== "undefined" && navigator.language
            ? navigator.language
            : "en-US";

        recognition.onstart = (): void => {
          setRecognitionState("listening");
        };

        recognition.onresult = (event: SpeechRecognitionEvent): void => {
          let currentInterim = "";
          let finalDelta = "";

          for (let i = event.resultIndex; i < event.results.length; i += 1) {
            const result = event.results[i];
            if (result.isFinal) {
              finalDelta += result[0].transcript;
            } else {
              currentInterim += result[0].transcript;
            }
          }

          if (finalDelta) {
            accumulatedFinalRef.current = (
              accumulatedFinalRef.current + " " + finalDelta
            ).trim();
            setFinalTranscript(accumulatedFinalRef.current);
          }
          setInterimTranscript(currentInterim);
        };

        recognition.onerror = (event: SpeechRecognitionErrorEvent): void => {
          if (event.error === "not-allowed" || event.error === "service-not-allowed") {
            setRecognitionState("permission_denied");
            setRecognitionError(
              "Microphone permission was denied. Please allow microphone access in your browser settings to use voice input.",
            );
          } else if (event.error === "no-speech") {
            // Calm timeout; remain idle or listening
          } else if (event.error === "network") {
            setRecognitionState("error");
            setRecognitionError(
              "Speech recognition network error occurred. Please try again.",
            );
          } else if (event.error !== "aborted") {
            setRecognitionState("error");
            setRecognitionError(`Speech recognition error: ${event.error}`);
          }
        };

        recognition.onend = (): void => {
          setRecognitionState((current) =>
            current === "listening" ? "idle" : current,
          );
          setInterimTranscript("");
          const fullResult = accumulatedFinalRef.current.trim();
          if (fullResult && onTranscriptReadyRef.current) {
            onTranscriptReadyRef.current(fullResult);
          }
          activeRecognitionRef.current = null;
        };

        recognition.start();
      } catch (err) {
        setRecognitionState("error");
        setRecognitionError(
          err instanceof Error
            ? err.message
            : "Could not initialize microphone. Please check browser permissions.",
        );
      }
    },
    [],
  );

  const stopSpeaking = useCallback((): void => {
    if (typeof window !== "undefined" && typeof window.speechSynthesis !== "undefined") {
      window.speechSynthesis.cancel();
    }
    setIsSpeaking(false);
    setIsPaused(false);
    setSpeakingMessageId(null);
  }, []);

  const pauseSpeaking = useCallback((): void => {
    if (typeof window !== "undefined" && typeof window.speechSynthesis !== "undefined") {
      window.speechSynthesis.pause();
      setIsPaused(true);
    }
  }, []);

  const resumeSpeaking = useCallback((): void => {
    if (typeof window !== "undefined" && typeof window.speechSynthesis !== "undefined") {
      window.speechSynthesis.resume();
      setIsPaused(false);
    }
  }, []);

  const speak = useCallback(
    (text: string, messageId?: string): void => {
      if (!isSpeechSynthesisSupported() || typeof window === "undefined") {
        return;
      }

      const cleaned = cleanTextForSpeech(text);
      if (!cleaned) {
        return;
      }

      window.speechSynthesis.cancel();

      const utterance = new SpeechSynthesisUtterance(cleaned);
      utterance.rate = settings.rate;
      utterance.pitch = settings.pitch;

      if (settings.voiceURI) {
        const matchingVoice = voices.find(
          (voice) => voice.voiceURI === settings.voiceURI,
        );
        if (matchingVoice) {
          utterance.voice = matchingVoice;
        }
      }

      utterance.onstart = (): void => {
        setIsSpeaking(true);
        setIsPaused(false);
        setSpeakingMessageId(messageId ?? null);
      };

      utterance.onend = (): void => {
        setIsSpeaking(false);
        setIsPaused(false);
        setSpeakingMessageId(null);
      };

      utterance.onerror = (): void => {
        setIsSpeaking(false);
        setIsPaused(false);
        setSpeakingMessageId(null);
      };

      window.speechSynthesis.speak(utterance);
    },
    [settings, voices],
  );

  const toggleAutoSpeak = useCallback((): void => {
    setSettings((current) => {
      const next = saveVoiceSettings({ autoSpeak: !current.autoSpeak });
      return next;
    });
  }, []);

  const setVoiceRate = useCallback((rate: number): void => {
    setSettings(() => saveVoiceSettings({ rate }));
  }, []);

  const setVoiceURI = useCallback((uri: string | null): void => {
    setSettings(() => saveVoiceSettings({ voiceURI: uri }));
  }, []);

  return {
    isRecognitionSupported,
    isSynthesisSupported,
    recognitionState,
    interimTranscript,
    finalTranscript,
    recognitionError,
    startListening,
    stopListening,
    cancelListening,
    clearRecognitionError,
    isSpeaking,
    isPaused,
    speakingMessageId,
    settings,
    voices,
    speak,
    stopSpeaking,
    pauseSpeaking,
    resumeSpeaking,
    toggleAutoSpeak,
    setVoiceRate,
    setVoiceURI,
  };
}
