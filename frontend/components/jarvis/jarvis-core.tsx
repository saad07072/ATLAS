"use client";

import type { JSX } from "react";
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { cleanTextForSpeech } from "@/services/voice";
import {
  sendChatMessage,
  getSystemVitals,
  getSystemMacros,
  deleteSystemMacro,
  getBrowserCDPStatus,
  getBrowserCDPTabs,
  openBrowserCDPTab,
  activateBrowserCDPTab,
  closeBrowserCDPTab,
  reloadBrowserCDPTab,
  launchDebugBrowser,
  type ActionRecord,
  type MacroItem,
  type BrowserCDPStatus,
  type BrowserCDPTab,
  type GroundingSource,
  getTTSStatus,
  synthesizeSpeechAudio,
  type TTSStatusResponse,
} from "@/services/api";
import type { SystemVitals } from "@/types";
import { audioFx } from "@/services/audio-fx";

export type AtlasState = "standby" | "listening" | "processing" | "speaking";

interface TelemetryData {
  frequency: number;
  audioLevel: number;
  activeVoice: string;
}

interface SpeechRecognitionResultItem {
  transcript: string;
}

interface SpeechRecognitionResultLike {
  isFinal: boolean;
  [index: number]: SpeechRecognitionResultItem;
}

interface SpeechRecognitionEventLike {
  resultIndex: number;
  results: {
    length: number;
    [index: number]: SpeechRecognitionResultLike;
  };
}

interface SpeechRecognitionLike {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  abort: () => void;
  stop: () => void;
}

function subscribeOnline(callback: () => void): () => void {
  window.addEventListener("online", callback);
  window.addEventListener("offline", callback);
  return () => {
    window.removeEventListener("online", callback);
    window.removeEventListener("offline", callback);
  };
}

function getOnlineSnapshot(): boolean {
  return typeof navigator !== "undefined" && typeof navigator.onLine === "boolean"
    ? navigator.onLine
    : true;
}

function getServerOnlineSnapshot(): boolean {
  return true;
}

export interface AtlasCoreProps {
  initialMini?: boolean;
  isStandaloneOverlay?: boolean;
}

export function AtlasCore({
  initialMini = false,
  isStandaloneOverlay = false,
}: AtlasCoreProps = {}): JSX.Element {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  // Core State
  const [atlasState, setAtlasState] = useState<AtlasState>("standby");
  const [isActive, setIsActive] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [atlasResponse, setAtlasResponse] = useState<string>(
    "Systems operational. Speak naturally, sir, or tap spacebar to begin.",
  );
  const [telemetry, setTelemetry] = useState<TelemetryData>({
    frequency: 432,
    audioLevel: 0,
    activeVoice: "Detecting neural voice...",
  });
  const [vitals, setVitals] = useState<SystemVitals | null>(null);
  const [macros, setMacros] = useState<MacroItem[]>([]);
  const [macroRecording, setMacroRecording] = useState<{
    isRecording: boolean;
    name: string | null;
    bufferCount: number;
  }>({ isRecording: false, name: null, bufferCount: 0 });
  const [cdpStatus, setCdpStatus] = useState<BrowserCDPStatus | null>(null);
  const [cdpTabs, setCdpTabs] = useState<BrowserCDPTab[]>([]);
  const [newTabUrl, setNewTabUrl] = useState<string>("");
  const [liveSources, setLiveSources] = useState<GroundingSource[]>([]);
  const [liveQueries, setLiveQueries] = useState<string[]>([]);
  const [voicePreset, setVoicePreset] = useState<string>("cinematic_british");
  const [ttsStatus, setTtsStatus] = useState<TTSStatusResponse | null>(null);
  const activeAudioElemRef = useRef<HTMLAudioElement | null>(null);

  const fetchMacros = useCallback(async () => {
    try {
      const data = await getSystemMacros();
      setMacros(data.macros || []);
      setMacroRecording({
        isRecording: data.is_recording,
        name: data.active_macro || null,
        bufferCount: data.buffer_count,
      });
    } catch {
      // Fallback silently
    }
  }, []);

  const fetchCDP = useCallback(async () => {
    try {
      const [statusRes, tabsRes] = await Promise.allSettled([
        getBrowserCDPStatus(),
        getBrowserCDPTabs(),
      ]);
      if (statusRes.status === "fulfilled") {
        setCdpStatus(statusRes.value);
      }
      if (tabsRes.status === "fulfilled") {
        setCdpTabs(tabsRes.value.tabs || []);
      }
    } catch {
      // Fallback silently
    }
  }, []);

  const handleOpenCDPTab = useCallback(
    async (url: string) => {
      if (!url.trim()) return;
      try {
        await openBrowserCDPTab(url.trim());
        setNewTabUrl("");
        await fetchCDP();
      } catch (err) {
        console.warn("Failed to open tab via CDP:", err);
      }
    },
    [fetchCDP],
  );

  const handleActivateCDPTab = useCallback(
    async (tabId: string) => {
      try {
        await activateBrowserCDPTab(tabId);
        await fetchCDP();
      } catch (err) {
        console.warn("Failed to activate tab:", err);
      }
    },
    [fetchCDP],
  );

  const handleCloseCDPTab = useCallback(
    async (tabId: string) => {
      try {
        await closeBrowserCDPTab(tabId);
        await fetchCDP();
      } catch (err) {
        console.warn("Failed to close tab:", err);
      }
    },
    [fetchCDP],
  );

  const handleReloadCDPTab = useCallback(
    async (tabId?: string) => {
      try {
        await reloadBrowserCDPTab(tabId);
        await fetchCDP();
      } catch (err) {
        console.warn("Failed to reload tab:", err);
      }
    },
    [fetchCDP],
  );

  const handleLaunchDebugBrowser = useCallback(async () => {
    try {
      await launchDebugBrowser();
      setTimeout(() => void fetchCDP(), 1500);
    } catch (err) {
      console.warn("Failed to launch debug browser:", err);
    }
  }, [fetchCDP]);

  const handleDeleteMacro = useCallback(
    async (macroName: string) => {
      try {
        await deleteSystemMacro(macroName);
        await fetchMacros();
      } catch (err) {
        console.warn("Failed to delete macro:", err);
      }
    },
    [fetchMacros],
  );

  useEffect(() => {
    let isMounted = true;
    const fetchAll = async () => {
      try {
        const [vitalsRes, macrosRes, cdpStatusRes, cdpTabsRes, ttsRes] = await Promise.allSettled([
          getSystemVitals(),
          getSystemMacros(),
          getBrowserCDPStatus(),
          getBrowserCDPTabs(),
          getTTSStatus(),
        ]);
        if (isMounted && vitalsRes.status === "fulfilled") {
          setVitals(vitalsRes.value);
        }
        if (isMounted && macrosRes.status === "fulfilled") {
          setMacros(macrosRes.value.macros || []);
          setMacroRecording({
            isRecording: macrosRes.value.is_recording,
            name: macrosRes.value.active_macro || null,
            bufferCount: macrosRes.value.buffer_count,
          });
        }
        if (isMounted && cdpStatusRes.status === "fulfilled") {
          setCdpStatus(cdpStatusRes.value);
        }
        if (isMounted && cdpTabsRes.status === "fulfilled") {
          setCdpTabs(cdpTabsRes.value.tabs || []);
        }
        if (isMounted && ttsRes.status === "fulfilled") {
          setTtsStatus(ttsRes.value);
        }
      } catch {
        // Fallback silently if server temporarily offline
      }
    };
    fetchAll();
    const interval = setInterval(fetchAll, 4000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, []);
  const [hudConsoleOpen, setHudConsoleOpen] = useState(false);
  const [isScreenShared, setIsScreenShared] = useState(false);
  const isOnline = useSyncExternalStore(subscribeOnline, getOnlineSnapshot, getServerOnlineSnapshot);
  const prevOnlineRef = useRef(isOnline);
  const [isSfxMuted, setIsSfxMuted] = useState<boolean>(() => audioFx.isMuted());
  const [isMiniMode, setIsMiniMode] = useState<boolean>(initialMini);
  const isMiniModeRef = useRef<boolean>(initialMini);

  // Wake-Word & Follow-Up State
  const [isWakeWordEnabled, setIsWakeWordEnabled] = useState<boolean>(() => {
    if (typeof window === "undefined") return true;
    try {
      const saved = localStorage.getItem("atlas_wake_word_enabled");
      return saved === null ? true : saved === "true";
    } catch {
      return true;
    }
  });
  const isWakeWordEnabledRef = useRef<boolean>(true);
  const [wakeWordTriggered, setWakeWordTriggered] = useState<boolean>(false);
  const wakeWordExpiryTimerRef = useRef<NodeJS.Timeout | null>(null);
  const followUpTimerRef = useRef<NodeJS.Timeout | null>(null);
  const lastTelemetryTimeRef = useRef<number>(0);
  const [textInput, setTextInput] = useState("");
  const screenStreamRef = useRef<MediaStream | null>(null);
  const screenVideoRef = useRef<HTMLVideoElement | null>(null);
  const [lastAction, setLastAction] = useState<ActionRecord | null>(null);
  const [actionTimer, setActionTimer] = useState<number>(0);
  const actionTimerIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const lastDispatchedTextRef = useRef<string>("");
  const lastDispatchedTimeRef = useRef<number>(0);

  // Audio & Speech References
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const micStreamRef = useRef<MediaStream | null>(null);
  const audioDataRef = useRef<Uint8Array | null>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);

  // Critical State Machine References (Prevents "stuck listening" race condition)
  const isBusyRef = useRef(false); // True when processing or speaking
  const atlasStateRef = useRef<AtlasState>("standby");
  const accumulatedTextRef = useRef<string>("");
  const debounceTimerRef = useRef<NodeJS.Timeout | null>(null);
  const silenceTimerRef = useRef<NodeJS.Timeout | null>(null);
  const conversationIdRef = useRef<string | undefined>(undefined);
  const isActiveRef = useRef(false);

  // Keep refs synchronized
  useEffect(() => {
    atlasStateRef.current = atlasState;
  }, [atlasState]);

  // Audio cue when network connectivity status changes
  useEffect(() => {
    if (prevOnlineRef.current !== isOnline) {
      if (isOnline) {
        void audioFx.playSuccess();
      } else {
        void audioFx.playAlert();
      }
      prevOnlineRef.current = isOnline;
    }
  }, [isOnline]);

  useEffect(() => {
    isActiveRef.current = isActive;
  }, [isActive]);

  useEffect(() => {
    isMiniModeRef.current = isMiniMode;
  }, [isMiniMode]);

  useEffect(() => {
    isWakeWordEnabledRef.current = isWakeWordEnabled;
    if (typeof window !== "undefined") {
      localStorage.setItem("atlas_wake_word_enabled", String(isWakeWordEnabled));
    }
  }, [isWakeWordEnabled]);

  // Safe Recognition Starter (declared early so speakAtlas can call it safely)
  const startRecognitionSafe = useCallback(() => {
    if (!isActiveRef.current || isBusyRef.current) return;
    try {
      if (recognitionRef.current) {
        recognitionRef.current.abort();
        setTimeout(() => {
          if (!isBusyRef.current && isActiveRef.current) {
            try {
              recognitionRef.current?.start();
            } catch {
              // Ignore collisions if already starting
            }
          }
        }, 120);
      }
    } catch {
      // Ignore
    }
  }, []);

  // -------------------------------------------------------------
  // 1. Audio Visualizer & Frequency Analyzer (Web Audio API)
  // -------------------------------------------------------------
  const initAudioAnalyser = useCallback(async () => {
    try {
      if (audioContextRef.current && audioContextRef.current.state === "suspended") {
        await audioContextRef.current.resume();
        return;
      }

      if (!audioContextRef.current) {
        const AudioCtx =
          window.AudioContext ||
          (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
        if (!AudioCtx) return;
        const ctx = new AudioCtx();
        audioContextRef.current = ctx;

        const stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
          },
        });
        micStreamRef.current = stream;

        const source = ctx.createMediaStreamSource(stream);
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 256;
        analyser.smoothingTimeConstant = 0.75;
        source.connect(analyser);

        analyserRef.current = analyser;
        audioDataRef.current = new Uint8Array(analyser.frequencyBinCount);
      }
    } catch (err) {
      console.warn("Audio input visualization notice (microphone permission needed):", err);
    }
  }, []);

  // -------------------------------------------------------------
  // 2. Speech Synthesis (ATLAS Voice Protocol & Neural TTS)
  // -------------------------------------------------------------
  const speakWithBrowserSynthesis = useCallback((cleanText: string, onComplete: () => void) => {
    if (typeof window === "undefined" || !window.speechSynthesis) {
      onComplete();
      return;
    }

    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(cleanText);
    const voices = window.speechSynthesis.getVoices();

    const britishMale = voices.find(
      (v) =>
        (v.lang.includes("en-GB") || v.lang.includes("en_GB")) &&
        (v.name.toLowerCase().includes("george") ||
          v.name.toLowerCase().includes("male") ||
          v.name.toLowerCase().includes("daniel") ||
          v.name.toLowerCase().includes("uk")) &&
        !v.name.toLowerCase().includes("female"),
    );
    const englishVoice =
      britishMale ||
      voices.find(
        (v) =>
          (v.lang.startsWith("en-GB") || v.lang.startsWith("en-US")) &&
          v.name.toLowerCase().includes("male") &&
          !v.name.toLowerCase().includes("female"),
      ) ||
      voices.find((v) => v.lang.startsWith("en-GB") && !v.name.toLowerCase().includes("female")) ||
      voices.find((v) => v.lang.startsWith("en") && !v.name.toLowerCase().includes("female")) ||
      voices[0];

    if (englishVoice) {
      utterance.voice = englishVoice;
      setTelemetry((prev) => ({ ...prev, activeVoice: `${englishVoice.name} (Native)` }));
    }

    utterance.pitch = 0.94;
    utterance.rate = 1.03;

    let fallbackTimer: NodeJS.Timeout | null = null;

    utterance.onstart = () => {
      isBusyRef.current = true;
      setAtlasState("speaking");
      try {
        recognitionRef.current?.abort();
      } catch {}
    };

    const finish = () => {
      if (fallbackTimer) clearTimeout(fallbackTimer);
      onComplete();
    };

    utterance.onend = finish;
    utterance.onerror = finish;

    const wordCount = cleanText.split(/\s+/).length;
    const estimatedDurationMs = Math.max(3200, (wordCount / 2.0) * 1000 + 2200);
    fallbackTimer = setTimeout(finish, estimatedDurationMs);

    window.speechSynthesis.speak(utterance);
  }, []);

  const speakAtlas = useCallback((text: string) => {
    if (typeof window === "undefined") return;

    if (activeAudioElemRef.current) {
      activeAudioElemRef.current.pause();
      activeAudioElemRef.current = null;
    }
    if (window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }

    const cleanText = cleanTextForSpeech(text);
    if (!cleanText) {
      isBusyRef.current = false;
      setAtlasState("listening");
      startRecognitionSafe();
      return;
    }

    const handleSpeechComplete = () => {
      setAtlasState("standby");
      void audioFx.playStandby();
      setTimeout(() => {
        isBusyRef.current = false;
        accumulatedTextRef.current = "";
        setTranscript("");
        if (isActiveRef.current || isWakeWordEnabledRef.current) {
          setAtlasState("listening");
          void audioFx.playListenStart();
          startRecognitionSafe();

          if (followUpTimerRef.current) clearTimeout(followUpTimerRef.current);
          followUpTimerRef.current = setTimeout(() => {
            if (!isBusyRef.current && atlasStateRef.current === "listening" && !accumulatedTextRef.current.trim()) {
              setAtlasState("standby");
              void audioFx.playStandby();
            }
          }, 7000);
        }
      }, 450);
    };

    // If Neural TTS is enabled, attempt backend stream
    if (voicePreset !== "browser") {
      void (async () => {
        try {
          const resp = await synthesizeSpeechAudio(cleanText, voicePreset);
          const cType = resp.headers.get("content-type") || "";
          if (resp.ok && (cType.includes("audio/mpeg") || cType.includes("audio/wav"))) {
            const blob = await resp.blob();
            const audioUrl = URL.createObjectURL(blob);
            const audio = new Audio(audioUrl);
            activeAudioElemRef.current = audio;

            isBusyRef.current = true;
            setAtlasState("speaking");
            setTelemetry((prev) => ({
              ...prev,
              activeVoice: voicePreset === "cinematic_british" ? "Cinematic British (Neural)" : "Tactical Crisp (Neural)",
            }));
            try {
              recognitionRef.current?.abort();
            } catch {}

            audio.onended = () => {
              URL.revokeObjectURL(audioUrl);
              activeAudioElemRef.current = null;
              handleSpeechComplete();
            };
            audio.onerror = () => {
              URL.revokeObjectURL(audioUrl);
              activeAudioElemRef.current = null;
              speakWithBrowserSynthesis(cleanText, handleSpeechComplete);
            };

            await audio.play();
            return;
          }
        } catch {
          // Fall back gracefully
        }
        speakWithBrowserSynthesis(cleanText, handleSpeechComplete);
      })();
      return;
    }

    speakWithBrowserSynthesis(cleanText, handleSpeechComplete);
  }, [voicePreset, speakWithBrowserSynthesis, startRecognitionSafe]);

  // Screen Streaming & Multimodal Vision Helpers
  const stopScreenShare = useCallback(() => {
    if (screenStreamRef.current) {
      screenStreamRef.current.getTracks().forEach((track) => track.stop());
      screenStreamRef.current = null;
    }
    if (screenVideoRef.current) {
      screenVideoRef.current.srcObject = null;
    }
    setIsScreenShared(false);
  }, []);

  const startScreenShare = useCallback(async () => {
    try {
      if (typeof navigator === "undefined" || !navigator.mediaDevices?.getDisplayMedia) {
        alert("Screen sharing is not supported by your current browser environment.");
        return;
      }
      const stream = await navigator.mediaDevices.getDisplayMedia({
        video: {
          displaySurface: "monitor",
        },
        audio: false,
      });
      screenStreamRef.current = stream;

      const video = document.createElement("video");
      video.autoplay = true;
      video.playsInline = true;
      video.muted = true;
      video.srcObject = stream;
      screenVideoRef.current = video;
      await video.play().catch(() => {});

      const track = stream.getVideoTracks()[0];
      if (track) {
        track.onended = () => {
          stopScreenShare();
        };
      }

      setIsScreenShared(true);
      const conf = "Visual display link established, sir. I am now observing your screen in real time.";
      setAtlasResponse(conf);
      speakAtlas(conf);
    } catch (err) {
      console.warn("Screen sharing permission declined or cancelled:", err);
    }
  }, [speakAtlas, stopScreenShare]);

  const toggleSfx = useCallback((e?: React.MouseEvent) => {
    if (e) e.stopPropagation();
    const nextMuted = audioFx.toggleMute();
    setIsSfxMuted(nextMuted);
    if (!nextMuted) {
      void audioFx.playUiTap();
    }
  }, []);

  const toggleScreenShare = useCallback(() => {
    void audioFx.playUiTap();
    if (isScreenShared) {
      stopScreenShare();
    } else {
      void startScreenShare();
    }
  }, [isScreenShared, startScreenShare, stopScreenShare]);

  const captureScreenFrame = useCallback((): string | null => {
    if (!screenStreamRef.current || !screenStreamRef.current.active) return null;
    const video = screenVideoRef.current;
    if (!video || video.videoWidth === 0 || video.videoHeight === 0) return null;

    try {
      const canvas = document.createElement("canvas");
      const maxDim = 1280;
      let w = video.videoWidth;
      let h = video.videoHeight;
      if (w > maxDim) {
        h = Math.round((h * maxDim) / w);
        w = maxDim;
      }
      canvas.width = w;
      canvas.height = h;
      const ctx = canvas.getContext("2d");
      if (!ctx) return null;
      ctx.drawImage(video, 0, 0, w, h);
      return canvas.toDataURL("image/jpeg", 0.75);
    } catch (e) {
      console.warn("Screen frame capture error:", e);
      return null;
    }
  }, []);

  // -------------------------------------------------------------
  // 3. Backend Agent Request Dispatcher
  // -------------------------------------------------------------
  const abortCurrentTask = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    if (actionTimerIntervalRef.current) {
      clearInterval(actionTimerIntervalRef.current);
      actionTimerIntervalRef.current = null;
    }
    isBusyRef.current = false;
    setAtlasState("listening");
    setAtlasResponse("Task execution aborted on your command, sir.");
    startRecognitionSafe();
  }, [startRecognitionSafe]);

  const sendToAtlas = useCallback(
    async (userMessage: string) => {
      const query = userMessage.trim();
      if (!query) return;

      // Client-side deduplication (drop duplicate within 3.5s)
      const now = Date.now();
      if (
        query.toLowerCase() === lastDispatchedTextRef.current.toLowerCase() &&
        now - lastDispatchedTimeRef.current < 3500
      ) {
        return;
      }
      lastDispatchedTextRef.current = query;
      lastDispatchedTimeRef.current = now;

      // Abort previous in-flight task if any
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      const controller = new AbortController();
      abortControllerRef.current = controller;

      // Elapsed action timer
      setActionTimer(0);
      if (actionTimerIntervalRef.current) clearInterval(actionTimerIntervalRef.current);
      const startTime = Date.now();
      actionTimerIntervalRef.current = setInterval(() => {
        setActionTimer((Date.now() - startTime) / 1000);
      }, 100);

      // Mark busy immediately so recognition won't restart on end
      isBusyRef.current = true;
      setAtlasState("processing");

      // Clear any pending timers
      if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
      if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);

      // Stop speech recognition while processing
      try {
        recognitionRef.current?.abort();
      } catch {
        // ignore
      }

      const screenFrame = captureScreenFrame();

      try {
        const data = await sendChatMessage(
          query,
          [],
          conversationIdRef.current,
          controller.signal,
          screenFrame,
        );

        if (actionTimerIntervalRef.current) {
          clearInterval(actionTimerIntervalRef.current);
          actionTimerIntervalRef.current = null;
        }

        if (data.conversation_id) {
          conversationIdRef.current = data.conversation_id;
        }

        if (data.actions && data.actions.length > 0) {
          const act = data.actions[0];
          setLastAction(act);
          if (act.status === "success") {
            void audioFx.playSuccess();
          } else {
            void audioFx.playAlert();
          }
          setTimeout(() => {
            setLastAction(null);
          }, 9000);
        }

        if (data.sources && data.sources.length > 0) {
          setLiveSources(data.sources);
          setLiveQueries(data.grounding_queries || []);
        } else {
          setLiveSources([]);
          setLiveQueries([]);
        }

        const reply = data.message || "Right away, sir. Task acknowledged.";
        setAtlasResponse(reply);
        speakAtlas(reply);
        void fetchMacros();
        void fetchCDP();
      } catch (err: unknown) {
        if (actionTimerIntervalRef.current) {
          clearInterval(actionTimerIntervalRef.current);
          actionTimerIntervalRef.current = null;
        }

        if (err instanceof Error && err.name === "AbortError") {
          isBusyRef.current = false;
          setAtlasState("listening");
          setAtlasResponse("Task execution cancelled on your order, sir.");
          startRecognitionSafe();
          return;
        }

        void audioFx.playAlert();
        const rawMsg = err instanceof Error ? err.message : "";
        const isFetchError =
          rawMsg.toLowerCase().includes("failed to fetch") ||
          rawMsg.toLowerCase().includes("network error") ||
          rawMsg.toLowerCase().includes("fetch failed");

        const errorReply = isFetchError
          ? "The ATLAS neural core backend appears to be offline, sir. Please start the backend service on port 8000 using run_backend.ps1."
          : rawMsg || "I encountered an issue processing your request, sir. The backend neural core may be reconnecting.";
        setAtlasResponse(errorReply);
        speakAtlas(errorReply);
      }
    },
    [captureScreenFrame, fetchCDP, fetchMacros, speakAtlas, startRecognitionSafe],
  );

  // -------------------------------------------------------------
  // 4. Ambient Speech Recognition with Precision Silence Detection
  // -------------------------------------------------------------
  const initSpeechRecognition = useCallback(() => {
    if (typeof window === "undefined") return;

    const SpeechRecognitionConstructor =
      (window as unknown as { SpeechRecognition?: new () => SpeechRecognitionLike }).SpeechRecognition ||
      (window as unknown as { webkitSpeechRecognition?: new () => SpeechRecognitionLike }).webkitSpeechRecognition;

    if (!SpeechRecognitionConstructor) {
      setAtlasResponse("Speech recognition is not supported in this browser engine, sir.");
      return;
    }

    // Abort existing instance if any
    if (recognitionRef.current) {
      try {
        recognitionRef.current.abort();
      } catch {
        // ignore
      }
    }

    const recognition = new SpeechRecognitionConstructor();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = "en-US";

    recognition.onresult = (event: SpeechRecognitionEventLike) => {
      if (isBusyRef.current) return;

      let interim = "";
      let final = "";

      for (let i = event.resultIndex; i < event.results.length; i++) {
        const item = event.results[i];
        if (item.isFinal) {
          final += item[0].transcript;
        } else {
          interim += item[0].transcript;
        }
      }

      const activeText = (final || interim).trim();
      if (!activeText) return;

      const WAKE_WORD_PATTERN = /\b(?:hey\s+atlas|ok\s+atlas|atlas|hey\s+jarvis|jarvis)\b/i;

      // 1. Passive Wake-Word Standby Interception
      if (atlasStateRef.current === "standby") {
        if (!isWakeWordEnabledRef.current) return;

        if (WAKE_WORD_PATTERN.test(activeText)) {
          void audioFx.playListenStart();
          isActiveRef.current = true;
          setIsActive(true);
          setWakeWordTriggered(true);
          if (wakeWordExpiryTimerRef.current) clearTimeout(wakeWordExpiryTimerRef.current);
          wakeWordExpiryTimerRef.current = setTimeout(() => setWakeWordTriggered(false), 8000);

          const commandText = activeText.replace(WAKE_WORD_PATTERN, "").replace(/^[,.\s]+/, "").trim();

          if (commandText.length > 0) {
            setTranscript(commandText);
            accumulatedTextRef.current = commandText;
            setAtlasState("listening");

            if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
            debounceTimerRef.current = setTimeout(() => {
              if (!isBusyRef.current && accumulatedTextRef.current.trim()) {
                const textToDispatch = accumulatedTextRef.current.trim();
                accumulatedTextRef.current = "";
                void audioFx.playCommit();
                setAtlasResponse("Processing request, sir...");
                void sendToAtlas(textToDispatch);
              }
            }, 380);
          } else {
            setTranscript("");
            accumulatedTextRef.current = "";
            setAtlasState("listening");
            setAtlasResponse("Listening, sir. How may I assist?");

            if (followUpTimerRef.current) clearTimeout(followUpTimerRef.current);
            followUpTimerRef.current = setTimeout(() => {
              if (!isBusyRef.current && atlasStateRef.current === "listening" && !accumulatedTextRef.current.trim()) {
                setAtlasState("standby");
                void audioFx.playStandby();
              }
            }, 7000);
          }
        }
        return;
      }

      // 2. Active Speech Recognition Mode
      if (followUpTimerRef.current) clearTimeout(followUpTimerRef.current);

      const cleanActive = activeText.replace(WAKE_WORD_PATTERN, "").replace(/^[,.\s]+/, "").trim() || activeText;
      setTranscript(cleanActive);
      accumulatedTextRef.current = cleanActive;
      setAtlasState("listening");

      // Industry-Standard Voice Activity Detection (VAD) Silence Dispatcher:
      if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
      if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);

      // Fast-commit on final (380ms) or natural pause in speech (1000ms)
      const delay = final ? 380 : 1000;
      debounceTimerRef.current = setTimeout(() => {
        if (!isBusyRef.current && accumulatedTextRef.current.trim()) {
          const textToDispatch = accumulatedTextRef.current.trim();
          accumulatedTextRef.current = "";
          void audioFx.playCommit();
          setAtlasResponse("Processing request, sir...");
          void sendToAtlas(textToDispatch);
        }
      }, delay);
    };

    recognition.onerror = (event: { error: string }) => {
      if (event.error !== "no-speech" && event.error !== "aborted") {
        console.warn("Speech recognition notice:", event.error);
      }
    };

    recognition.onend = () => {
      // ONLY restart if ATLAS is NOT busy (i.e. not processing or speaking)
      if ((isActiveRef.current || isWakeWordEnabledRef.current) && !isBusyRef.current) {
        setTimeout(() => {
          if ((isActiveRef.current || isWakeWordEnabledRef.current) && !isBusyRef.current) {
            try {
              recognition.start();
            } catch {
              // ignore restart collision
            }
          }
        }, 150);
      }
    };

    recognitionRef.current = recognition;

    try {
      recognition.start();
      setAtlasState("listening");
      void audioFx.playListenStart();
    } catch {
      // ignore
    }
  }, [sendToAtlas]);

  // -------------------------------------------------------------
  // 5. Activation (One-Click User Gesture to Boot ATLAS)
  // -------------------------------------------------------------
  const activateAtlas = useCallback(async () => {
    if (isActive) return;
    setIsActive(true);
    isActiveRef.current = true;
    void audioFx.playBoot();
    await initAudioAnalyser();
    initSpeechRecognition();

    const welcome = "Systems online, sir. ATLAS neural task system fully operational. How may I assist you today?";
    setAtlasResponse(welcome);
    speakAtlas(welcome);
  }, [initAudioAnalyser, initSpeechRecognition, isActive, speakAtlas]);

  // Keyboard shortcut: Spacebar to toggle / commit / interrupt
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.code === "Space" && (e.target as HTMLElement).tagName !== "INPUT") {
        e.preventDefault();
        if (!isActive) {
          void activateAtlas();
        } else if (atlasStateRef.current === "speaking") {
          window.speechSynthesis?.cancel();
          isBusyRef.current = false;
          setAtlasState("listening");
          startRecognitionSafe();
        } else if (atlasStateRef.current === "listening" && accumulatedTextRef.current.trim()) {
          // Immediately commit speech on spacebar
          const query = accumulatedTextRef.current.trim();
          accumulatedTextRef.current = "";
          void sendToAtlas(query);
        }
      } else if ((e.code === "KeyM" && e.altKey) || (e.code === "KeyM" && (e.metaKey || e.ctrlKey))) {
        e.preventDefault();
        void audioFx.playUiTap();
        setIsMiniMode((prev) => !prev);
      } else if ((e.code === "KeyS" && e.shiftKey && (e.ctrlKey || e.metaKey)) || (e.code === "KeyS" && e.altKey)) {
        e.preventDefault();
        toggleScreenShare();
      } else if (e.code === "Escape") {
        if (atlasStateRef.current === "processing") {
          abortCurrentTask();
        } else if (atlasStateRef.current === "speaking") {
          window.speechSynthesis?.cancel();
          isBusyRef.current = false;
          setAtlasState("listening");
          startRecognitionSafe();
        }
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [activateAtlas, abortCurrentTask, isActive, sendToAtlas, startRecognitionSafe, toggleScreenShare]);

  // -------------------------------------------------------------
  // 6. Holographic Arc Reactor & Gyroscope Core Animation (60fps)
  // -------------------------------------------------------------
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let animationFrameId: number;
    let angle = 0;
    let pulseAngle = 0;

    const resizeCanvas = () => {
      if (isMiniModeRef.current) {
        canvas.width = canvas.parentElement?.clientWidth || 390;
        canvas.height = canvas.parentElement?.clientHeight || 540;
      } else {
        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight;
      }
    };
    resizeCanvas();
    window.addEventListener("resize", resizeCanvas);

    // Floating Holographic Embers
    const particles = Array.from({ length: 64 }, () => ({
      x: 0,
      y: 0,
      radius: Math.random() * 2.2 + 0.8,
      angle: Math.random() * Math.PI * 2,
      distance: Math.random() * 160 + 50,
      speed: (Math.random() * 0.012 + 0.004) * (Math.random() > 0.5 ? 1 : -1),
      opacity: Math.random() * 0.7 + 0.3,
    }));

    const render = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      const centerX = canvas.width / 2;
      const centerY = isMiniModeRef.current ? canvas.height * 0.35 : canvas.height / 2;
      const miniScale = isMiniModeRef.current ? 0.6 : 1.0;

      // Extract real-time frequency data
      let audioLevel = 0;
      if (analyserRef.current && audioDataRef.current) {
        analyserRef.current.getByteFrequencyData(audioDataRef.current as unknown as Uint8Array<ArrayBuffer>);
        let sum = 0;
        const binCount = audioDataRef.current.length;
        for (let i = 0; i < binCount; i++) {
          sum += audioDataRef.current[i];
        }
        audioLevel = sum / (binCount * 255);
        const now = performance.now();
        if (now - lastTelemetryTimeRef.current > 100) {
          lastTelemetryTimeRef.current = now;
          const sampleRate = audioContextRef.current?.sampleRate || 44100;
          const dominantFreq = audioFx.calculateDominantFrequency(
            analyserRef.current,
            sampleRate,
            audioDataRef.current as unknown as Uint8Array,
          );
          setTelemetry((prev) => ({
            ...prev,
            audioLevel: Math.round(audioLevel * 100),
            frequency: dominantFreq,
          }));
        }
      }

      const currentState = atlasStateRef.current;
      const isSpeakingState = currentState === "speaking";
      const isListeningState = currentState === "listening";
      const isProcessingState = currentState === "processing";

      // Modulated rotation speed for holographic gyroscopes
      const rotSpeed = isProcessingState
        ? 0.045
        : isSpeakingState
          ? 0.024
          : isListeningState
            ? 0.014 + audioLevel * 0.04
            : 0.007;

      angle += rotSpeed;
      pulseAngle += 0.035;

      const dynamicPulse = Math.sin(pulseAngle) * 6;
      const speechPulse = isSpeakingState ? Math.sin(pulseAngle * 3.5) * 14 : 0;
      const baseRadius = (115 + dynamicPulse + speechPulse + audioLevel * 45) * miniScale;

      // State-specific Neon Glow Themes
      const glowColor = isSpeakingState
        ? "rgba(245, 158, 11, "     // Arc Reactor Gold / Amber
        : isProcessingState
          ? "rgba(139, 92, 246, "   // Neural Violet / Ultraviolet
          : isListeningState
            ? "rgba(0, 255, 170, "  // Listening Emerald / Cyan
            : "rgba(0, 240, 255, "; // Calibrated Stark Cyan

      // ---------------------------------------------------------
      // A. Deep Center Plasma Core
      // ---------------------------------------------------------
      const coreGradient = ctx.createRadialGradient(
        centerX,
        centerY,
        4,
        centerX,
        centerY,
        baseRadius * 0.6,
      );
      coreGradient.addColorStop(0, "rgba(255, 255, 255, 0.98)");
      coreGradient.addColorStop(0.25, `${glowColor}0.85)`);
      coreGradient.addColorStop(0.65, `${glowColor}0.25)`);
      coreGradient.addColorStop(1, "rgba(0, 0, 0, 0)");

      ctx.fillStyle = coreGradient;
      ctx.beginPath();
      ctx.arc(centerX, centerY, baseRadius * 0.65, 0, Math.PI * 2);
      ctx.fill();

      // ---------------------------------------------------------
      // B. Ring 1: Inner Gyroscope Hex Petals (Rotating Clockwise)
      // ---------------------------------------------------------
      ctx.save();
      ctx.translate(centerX, centerY);
      ctx.rotate(angle);
      ctx.strokeStyle = `${glowColor}0.85)`;
      ctx.lineWidth = 3;
      ctx.shadowBlur = 18;
      ctx.shadowColor = `${glowColor}0.9)`;

      const innerSegments = 6;
      for (let i = 0; i < innerSegments; i++) {
        const startArc = (i * Math.PI * 2) / innerSegments;
        const arcLength = (Math.PI * 2) / innerSegments - 0.22;
        ctx.beginPath();
        ctx.arc(0, 0, baseRadius * 0.76, startArc, startArc + arcLength);
        ctx.stroke();

        // Inner laser node marker
        const markerX = Math.cos(startArc) * (baseRadius * 0.76);
        const markerY = Math.sin(startArc) * (baseRadius * 0.76);
        ctx.fillStyle = "#ffffff";
        ctx.beginPath();
        ctx.arc(markerX, markerY, 2.5, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.restore();

      // ---------------------------------------------------------
      // C. Ring 2: Telemetry Compass Ring (Counter-Rotating)
      // ---------------------------------------------------------
      ctx.save();
      ctx.translate(centerX, centerY);
      ctx.rotate(-angle * 1.3);
      ctx.strokeStyle = `${glowColor}0.65)`;
      ctx.lineWidth = 1.5;
      ctx.setLineDash([6, 8]);
      ctx.shadowBlur = 12;
      ctx.shadowColor = `${glowColor}0.7)`;

      ctx.beginPath();
      ctx.arc(0, 0, baseRadius, 0, Math.PI * 2);
      ctx.stroke();

      // 360-degree precision tick marks & cardinal crosshairs
      ctx.setLineDash([]);
      for (let i = 0; i < 36; i++) {
        const tickAngle = (i * Math.PI * 2) / 36;
        const isMajor = i % 9 === 0;
        const tickLen = isMajor ? 12 : 5;
        const x1 = Math.cos(tickAngle) * (baseRadius - tickLen);
        const y1 = Math.sin(tickAngle) * (baseRadius - tickLen);
        const x2 = Math.cos(tickAngle) * (baseRadius + tickLen);
        const y2 = Math.sin(tickAngle) * (baseRadius + tickLen);

        ctx.strokeStyle = isMajor ? "#ffffff" : `${glowColor}0.5)`;
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.stroke();
      }
      ctx.restore();

      // ---------------------------------------------------------
      // D. Ring 3: Circular Sonic Frequency Waveform Bars (64 Bands)
      // ---------------------------------------------------------
      ctx.save();
      ctx.translate(centerX, centerY);
      ctx.rotate(angle * 0.5);

      const spectrumBands = 48;
      const spectrumBaseR = baseRadius * 1.25;
      for (let i = 0; i < spectrumBands; i++) {
        const theta = (i * Math.PI * 2) / spectrumBands;
        let barHeight = 4;
        if (audioDataRef.current && audioDataRef.current.length > 0) {
          const val = audioDataRef.current[i % audioDataRef.current.length] / 255;
          barHeight = Math.max(3, val * 38);
        } else {
          barHeight = 4 + Math.sin(theta * 8 + pulseAngle * 2) * 5;
        }

        const x1 = Math.cos(theta) * spectrumBaseR;
        const y1 = Math.sin(theta) * spectrumBaseR;
        const x2 = Math.cos(theta) * (spectrumBaseR + barHeight);
        const y2 = Math.sin(theta) * (spectrumBaseR + barHeight);

        ctx.strokeStyle = `${glowColor}${0.45 + (barHeight / 40) * 0.55})`;
        ctx.lineWidth = 2.2;
        ctx.shadowBlur = 10;
        ctx.shadowColor = `${glowColor}0.8)`;
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.stroke();
      }
      ctx.restore();

      // ---------------------------------------------------------
      // E. Ring 4: Outer Gyroscope Track with Orbiting Satellites
      // ---------------------------------------------------------
      ctx.save();
      ctx.translate(centerX, centerY);
      ctx.rotate(-angle * 0.7);
      ctx.strokeStyle = `${glowColor}0.4)`;
      ctx.lineWidth = 1;
      ctx.setLineDash([12, 16]);

      const outerR = baseRadius * 1.55;
      ctx.beginPath();
      ctx.arc(0, 0, outerR, 0, Math.PI * 2);
      ctx.stroke();

      // 3 Orbiting Satellites / Sensor Nodes
      ctx.setLineDash([]);
      for (let i = 0; i < 3; i++) {
        const satAngle = (i * Math.PI * 2) / 3;
        const sx = Math.cos(satAngle) * outerR;
        const sy = Math.sin(satAngle) * outerR;

        ctx.fillStyle = "#ffffff";
        ctx.shadowBlur = 14;
        ctx.shadowColor = `${glowColor}1)`;
        ctx.beginPath();
        ctx.arc(sx, sy, 3.5, 0, Math.PI * 2);
        ctx.fill();

        ctx.strokeStyle = `${glowColor}0.9)`;
        ctx.beginPath();
        ctx.arc(sx, sy, 7, 0, Math.PI * 2);
        ctx.stroke();
      }
      ctx.restore();

      // ---------------------------------------------------------
      // F. Orbiting Holographic Embers / Energy Particles
      // ---------------------------------------------------------
      ctx.save();
      ctx.fillStyle = `${glowColor}0.9)`;
      ctx.shadowBlur = 12;
      ctx.shadowColor = `${glowColor}1)`;

      for (const p of particles) {
        p.angle += p.speed * (isSpeakingState || isProcessingState ? 2.2 : 1);
        const dist = p.distance + audioLevel * 45;
        const px = centerX + Math.cos(p.angle) * dist;
        const py = centerY + Math.sin(p.angle) * dist;

        ctx.beginPath();
        ctx.arc(px, py, p.radius, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.restore();

      animationFrameId = requestAnimationFrame(render);
    };

    render();

    return () => {
      cancelAnimationFrame(animationFrameId);
      window.removeEventListener("resize", resizeCanvas);
    };
  }, []);

  return (
    <div
      className={`atlas-viewport${isMiniMode ? " mini-mode" : ""}${isStandaloneOverlay ? " standalone-overlay" : ""}`}
      onClick={() => {
        if (!isActive) {
          void activateAtlas();
        } else if (atlasStateRef.current === "speaking") {
          window.speechSynthesis?.cancel();
          isBusyRef.current = false;
          setAtlasState("listening");
          startRecognitionSafe();
        } else if (atlasStateRef.current === "listening" && accumulatedTextRef.current.trim()) {
          const textToDispatch = accumulatedTextRef.current.trim();
          accumulatedTextRef.current = "";
          void sendToAtlas(textToDispatch);
        }
      }}
    >
      {/* 1. Holographic HUD Canvas */}
      <canvas ref={canvasRef} className="atlas-canvas" />

      {/* 2. Top-Left Holographic Telemetry HUD */}
      <div className="atlas-hud-top-left">
        <div className="hud-badge">
          <span className="hud-dot pulsing" />
          <span>ATLAS // NEURAL CORE</span>
        </div>
        <div className="hud-sub">MARK VII // AUTONOMOUS TASK SYSTEM</div>
        <div className="hud-telemetry-row">
          <span>PROTOCOL:</span>
          <span className="hud-val">AUTONOMOUS AGENT</span>
        </div>
        <div className="hud-telemetry-row">
          <span>CORE:</span>
          <span className="hud-val" suppressHydrationWarning>
            {isOnline ? "GEMINI FLASH LATEST" : "LOCAL OFFLINE CORE"}
          </span>
        </div>
        <div className="hud-telemetry-row">
          <span>LINK:</span>
          <span className={`hud-val ${!isOnline ? "state-speaking" : ""}`} suppressHydrationWarning>
            {isOnline ? "CLOUD CONNECTED" : "LOCAL AUTONOMOUS"}
          </span>
        </div>
        <div className="hud-telemetry-row">
          <span>STATE:</span>
          <span className={`hud-val state-${atlasState}`}>
            {atlasState.toUpperCase()}
          </span>
        </div>
        {macroRecording.isRecording && (
          <div className="hud-recording-badge">
            <span className="rec-dot red pulsing" />
            <span className="rec-text">
              REC: {macroRecording.name} ({macroRecording.bufferCount})
            </span>
            <button
              type="button"
              className="rec-stop-btn"
              onClick={(e) => {
                e.stopPropagation();
                void sendToAtlas("stop recording macro");
              }}
              title="Stop and save macro"
            >
              SAVE
            </button>
          </div>
        )}
      </div>

      {/* 3. Top-Right Audio & Memory Telemetry HUD */}
      <div className="atlas-hud-top-right">
        <div className="hud-badge right-aligned">
          <span>SYSTEM DIAGNOSTICS</span>
          <span className="hud-dot green" />
        </div>
        {vitals && (
          <>
            <div className="hud-telemetry-row right-aligned">
              <span>CPU LOAD:</span>
              <span className="hud-val">{vitals.cpu_percent}%</span>
            </div>
            <div className="hud-telemetry-row right-aligned">
              <span>RAM USAGE:</span>
              <span className="hud-val">{vitals.memory_used_gb}/{vitals.memory_total_gb} GB ({vitals.memory_percent}%)</span>
            </div>
            {vitals.battery_percent !== null && (
              <div className="hud-telemetry-row right-aligned">
                <span>BATTERY:</span>
                <span className="hud-val">{vitals.battery_percent}% [{vitals.battery_plugged}]</span>
              </div>
            )}
            <div className="hud-telemetry-row right-aligned">
              <span>DISK FREE:</span>
              <span className="hud-val">{vitals.disk_free_gb} GB ({vitals.disk_percent}%)</span>
            </div>
          </>
        )}
        <div className="hud-telemetry-row right-aligned">
          <span>LIVE GROUNDING:</span>
          <span className="hud-val state-listening">CONTINUOUS (SYNCED)</span>
        </div>
        <div className="hud-telemetry-row right-aligned">
          <span>MACROS:</span>
          <span className="hud-val">{macros.length} SAVED</span>
        </div>
        <div className="hud-telemetry-row right-aligned">
          <span>CDP LINK:</span>
          <span className={`hud-val ${cdpStatus?.connected ? "state-listening" : ""}`}>
            {cdpStatus?.connected ? `ACTIVE (${cdpTabs.length} TABS)` : "STANDBY"}
          </span>
        </div>
        <div className="hud-telemetry-row right-aligned">
          <span>FREQUENCY:</span>
          <span className="hud-val">{telemetry.frequency} HZ</span>
        </div>
        <div className="hud-telemetry-row right-aligned">
          <span>SYNTHESIZER:</span>
          <span className="hud-val truncate-voice">{telemetry.activeVoice}</span>
        </div>
        <div className="hud-telemetry-row right-aligned">
          <span>PERSISTENCE:</span>
          <span className="hud-val">SUPABASE POSTGRES</span>
        </div>
        <div className="hud-telemetry-row right-aligned">
          <span>PERMISSIONS:</span>
          <span className="hud-val">SHA-256 VERIFIED</span>
        </div>
        <div className="hud-telemetry-row right-aligned">
          <span>VISION STREAM:</span>
          <span className={`hud-val ${isScreenShared ? "state-speaking" : ""}`}>
            {isScreenShared ? "LINKED (ACTIVE)" : "OFFLINE"}
          </span>
        </div>

        <div className="hud-buttons-row">
          <button
            type="button"
            className="hud-console-trigger"
            onClick={(e) => {
              e.stopPropagation();
              void audioFx.playUiTap();
              setIsMiniMode(!isMiniMode);
            }}
            title={isMiniMode ? "Expand to Fullscreen HUD (Alt+M)" : "Collapse to Floating Mini-HUD (Alt+M)"}
          >
            {isMiniMode ? "[ ⛶ FULL HUD ]" : "[ 📌 MINI HUD ]"}
          </button>
          <button
            type="button"
            suppressHydrationWarning
            className={`hud-console-trigger ${isWakeWordEnabled ? "wakeword-active" : "wakeword-muted"}`}
            onClick={(e) => {
              e.stopPropagation();
              void audioFx.playUiTap();
              setIsWakeWordEnabled(!isWakeWordEnabled);
              if (!isWakeWordEnabled) {
                startRecognitionSafe();
              }
            }}
            title={isWakeWordEnabled ? "Mute 'Hey ATLAS' passive wake-word listener" : "Enable hands-free 'Hey ATLAS' wake-word listener"}
          >
            {isWakeWordEnabled ? "[ ⚡ WAKE WORD: ON ]" : "[ 💤 WAKE WORD: OFF ]"}
          </button>
          <button
            type="button"
            suppressHydrationWarning
            className={`hud-console-trigger ${isSfxMuted ? "sfx-muted" : "sfx-active"}`}
            onClick={(e) => {
              e.stopPropagation();
              toggleSfx(e);
            }}
            title={isSfxMuted ? "Unmute procedural sound FX" : "Mute procedural sound FX"}
          >
            {isSfxMuted ? "[ 🔇 SFX MUTED ]" : "[ 🔊 SFX ACTIVE ]"}
          </button>
          <button
            type="button"
            className={`hud-console-trigger ${isScreenShared ? "vision-active" : ""}`}
            onClick={(e) => {
              e.stopPropagation();
              toggleScreenShare();
            }}
            title="Share display stream with ATLAS neural vision core"
          >
            {isScreenShared ? "[ 👁️ SCREEN LINKED ]" : "[ 👁️ SHARE SCREEN ]"}
          </button>
          <button
            type="button"
            className="hud-console-trigger"
            onClick={(e) => {
              e.stopPropagation();
              void audioFx.playUiTap();
              setHudConsoleOpen(!hudConsoleOpen);
            }}
            title="Toggle System Management Console"
          >
            {hudConsoleOpen ? "[ HIDE CONSOLE ]" : "[ SYSTEM CONSOLE ]"}
          </button>
        </div>
      </div>

      {/* 4. Bottom-Left Audio Level VU Meter */}
      <div className="atlas-hud-bottom-left">
        <span className="vu-label">MIC INPUT LEVEL</span>
        <div className="vu-meter-bar">
          {Array.from({ length: 12 }).map((_, idx) => {
            const activeThreshold = (idx + 1) * 8;
            const isLit = telemetry.audioLevel >= activeThreshold;
            const isHigh = idx >= 9;
            return (
              <span
                key={idx}
                className={`vu-segment${isLit ? " lit" : ""}${isHigh ? " peak" : ""}`}
              />
            );
          })}
        </div>
      </div>

      {/* 5. Center-Bottom Floating Holographic Transcript */}
      <div className="atlas-dialogue-hud">
        {/* Wake Word Recognition Banner */}
        {wakeWordTriggered && (
          <div className="wakeword-banner">
            <span className="hud-dot green" />
            <span>⚡ WAKE WORD DETECTED // NEURAL EAR ENGAGED</span>
          </div>
        )}

        {/* User Input Stream */}
        {transcript && (
          <div className="dialogue-bubble user-stream">
            <span className="dialogue-speaker">YOU &gt;</span>
            <span className="dialogue-text">&ldquo;{transcript}&rdquo;</span>
          </div>
        )}

        {/* Active Task Progress Indicator during Processing */}
        {atlasState === "processing" && (
          <div className="task-progress-hud">
            <span className="task-spinner" />
            <span className="task-phase">EXECUTING TASK PROTOCOL</span>
            <span className="task-timer">[T+ {actionTimer.toFixed(1)}s]</span>
            <button
              type="button"
              className="task-abort-btn"
              onClick={(e) => {
                e.stopPropagation();
                abortCurrentTask();
              }}
              title="Abort current task (ESC)"
            >
              ABORT [ESC]
            </button>
          </div>
        )}

        {/* Action Outcome Verified Badge */}
        {lastAction && (
          <div className={`action-outcome-pill ${lastAction.status}`}>
            <span className="action-status-icon">
              {lastAction.status === "success" ? "✓" : "⚠"}
            </span>
            <span className="action-tool-tag">[{lastAction.tool}]</span>
            <span className="action-detail">{lastAction.message}</span>
            <span className="action-verified-badge">
              {lastAction.verified ? "VERIFIED" : "UNVERIFIED"}
            </span>
          </div>
        )}

        {/* ATLAS Spoken Response Stream */}
        <div className="dialogue-bubble atlas-stream">
          <div className="dialogue-header">
            <span className="dialogue-speaker atlas-tag">ATLAS &gt;</span>
            {atlasState === "speaking" && (
              <span className="audio-live-waves">
                <span className="wave-bar" />
                <span className="wave-bar" />
                <span className="wave-bar" />
                <span className="wave-bar" />
              </span>
            )}
          </div>
          <p className="dialogue-text">{atlasResponse}</p>
          {liveSources.length > 0 && (
            <div className="atlas-grounding-sources">
              <div className="grounding-badge">
                <span className="grounding-dot" /> REAL-TIME GROUNDED
                {liveQueries.length > 0 && (
                  <span className="grounding-query"> — {liveQueries[0]}</span>
                )}
              </div>
              <div className="grounding-links">
                {liveSources.slice(0, 4).map((src, i) => (
                  <a
                    key={i}
                    href={src.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="grounding-link-pill"
                    title={src.title}
                  >
                    🌐 {src.title.length > 40 ? src.title.slice(0, 40) + "…" : src.title}
                  </a>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Holographic Optical Vision Quick Bar */}
        {isScreenShared && (
          <div className="atlas-vision-quick-bar" onClick={(e) => e.stopPropagation()}>
            <span className="vision-stream-tag">
              <span className="vision-dot pulsing" /> OPTICAL FEED LINKED
            </span>
            <button
              type="button"
              className="vision-quick-btn"
              onClick={() => void sendToAtlas("Inspect my screen and describe what is visible")}
              title="Full screen inspection"
            >
              🔍 Inspect Screen
            </button>
            <button
              type="button"
              className="vision-quick-btn"
              onClick={() => void sendToAtlas("What error or bug is visible on my screen?")}
              title="Debug error on screen"
            >
              🐛 Debug Error
            </button>
            <button
              type="button"
              className="vision-quick-btn"
              onClick={() => void sendToAtlas("Extract and transcribe all text from my screen")}
              title="Extract text via OCR"
            >
              ⚡ Extract Text (OCR)
            </button>
            <button
              type="button"
              className="vision-quick-btn"
              onClick={() => void sendToAtlas("Summarize the document or page on my screen")}
              title="Summarize document or page"
            >
              📄 Summarize Page
            </button>
          </div>
        )}

        {/* Holographic Quick Routine Bar */}
        <div className="atlas-protocol-quick-bar" onClick={(e) => e.stopPropagation()}>
          <button
            type="button"
            className="protocol-quick-btn"
            onClick={() => void sendToAtlas("good morning, give me my executive briefing")}
            title="Execute Autonomous Executive Morning Briefing"
          >
            ☀️ Executive Briefing
          </button>
          <button
            type="button"
            className="protocol-quick-btn"
            onClick={() => void sendToAtlas("run macro standup_prep")}
            title="Execute Standup Prep Macro"
          >
            📋 Standup Prep
          </button>
          <button
            type="button"
            className="protocol-quick-btn"
            onClick={() => void sendToAtlas("activate focus mode protocol")}
            title="Engage Focus Mode Protocol"
          >
            🎯 Focus Mode
          </button>
          <button
            type="button"
            className="protocol-quick-btn"
            onClick={() =>
              void sendToAtlas(
                macroRecording.isRecording
                  ? "stop recording macro"
                  : "start recording macro custom_task",
              )
            }
            title={
              macroRecording.isRecording
                ? "Stop recording macro"
                : "Record new custom macro"
            }
          >
            {macroRecording.isRecording ? "⏹️ Save Macro" : "⏺️ Record Macro"}
          </button>
          <button
            type="button"
            className="protocol-quick-btn"
            onClick={() => void sendToAtlas("list browser tabs")}
            title="Inspect active browser tabs via CDP"
          >
            🌐 Tabs ({cdpTabs.length})
          </button>
          <button
            type="button"
            className="protocol-quick-btn"
            onClick={() => void sendToAtlas("reload browser tab")}
            title="Reload active tab via CDP"
          >
            🔄 Reload Tab
          </button>
          <button
            type="button"
            className="protocol-quick-btn"
            onClick={() => void sendToAtlas("what is the latest news today")}
            title="Query continuous live real-time news & search grounding"
          >
            📡 Live News
          </button>
        </div>

        {/* Sleek Liquid-Glass Quick Command Bar */}
        <form
          className="atlas-command-bar"
          onSubmit={(e) => {
            e.preventDefault();
            const q = textInput.trim();
            if (q) {
              setTextInput("");
              setTranscript(q);
              void sendToAtlas(q);
            }
          }}
          onClick={(e) => e.stopPropagation()}
        >
          <input
            type="text"
            className="atlas-command-input"
            placeholder="Type a command or query, or speak naturally (e.g. 'India versus New Zealand', 'can you see my screen')..."
            value={textInput}
            onChange={(e) => setTextInput(e.target.value)}
          />
          <button
            type="submit"
            className="atlas-command-submit"
            disabled={!textInput.trim() || atlasState === "processing"}
          >
            EXECUTE
          </button>
          <button
            type="button"
            className={`atlas-screen-toggle-btn ${isScreenShared ? "active" : ""}`}
            onClick={toggleScreenShare}
            title={isScreenShared ? "Screen Linked - Click to disconnect" : "Share screen with ATLAS"}
          >
            {isScreenShared ? "👁️ LINKED" : "👁️ SCREEN"}
          </button>
        </form>

        {/* Prompt Cue */}
        <div className="atlas-cue">
          {!isActive ? (
            <span className="cue-pulse">CLICK ANYWHERE OR PRESS SPACEBAR TO INITIALIZE</span>
          ) : atlasState === "listening" ? (
            <span className="cue-listening">
              <span className="wave-icon" /> LISTENING... SPEAK NATURALLY, SIR
            </span>
          ) : atlasState === "processing" ? (
            <span className="cue-thinking">COMPUTING NEURAL RESPONSE &amp; VERIFYING ACTIONS...</span>
          ) : (
            <span className="cue-speaking">TRANSMITTING VOICE PROTOCOL...</span>
          )}
        </div>
      </div>

      {/* 6. Optional Holographic System Console Drawer (for Connected Services / Settings) */}
      {hudConsoleOpen && (
        <aside
          className="atlas-console-drawer"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="console-header">
            <h3>ATLAS // SYSTEM CONSOLE</h3>
            <button
              type="button"
              className="hud-close-btn"
              onClick={() => setHudConsoleOpen(false)}
            >
              ×
            </button>
          </div>
          <p className="console-desc">
            Direct access to external cloud service bridges, workflows, and memory vaults.
          </p>

          <div className="console-links">
            <Link href="/connected-services" className="console-card">
              <h4>Connected Services</h4>
              <p>Manage Google Workspace (Calendar, Gmail) &amp; GitHub App.</p>
            </Link>
            <Link href="/workflows" className="console-card">
              <h4>Workflow Execution</h4>
              <p>Inspect multi-step autonomous task pipelines &amp; rollbacks.</p>
            </Link>
            <Link href="/memory" className="console-card">
              <h4>Memory Vault</h4>
              <p>View episodic and semantic long-term memory entries.</p>
            </Link>
            <Link href="/settings" className="console-card">
              <h4>Settings &amp; Audio</h4>
              <p>Configure speech rate, pitch, and API preferences.</p>
            </Link>
          </div>

          <div className="console-macros-section">
            <h4>Saved Desktop Macros ({macros.length})</h4>
            <div className="macro-items-list">
              {macros.length === 0 ? (
                <p className="console-desc">
                  No macros saved yet. Say &quot;Record macro [name]&quot; to capture actions.
                </p>
              ) : (
                macros.map((m) => (
                  <div key={m.name} className="macro-item-card">
                    <div className="macro-info">
                      <h5>{m.name}</h5>
                      <p>
                        {m.steps.length} steps &bull; {m.description}
                      </p>
                    </div>
                    <div className="macro-actions">
                      <button
                        type="button"
                        className="macro-btn play"
                        onClick={() => void sendToAtlas(`run macro ${m.name}`)}
                        title="Execute macro"
                      >
                        ▶ Play
                      </button>
                      <button
                        type="button"
                        className="macro-btn del"
                        onClick={() => void handleDeleteMacro(m.name)}
                        title="Delete macro"
                      >
                        🗑
                      </button>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          <div className="console-macros-section">
            <div className="cdp-section-header">
              <h4>Browser CDP Live Control ({cdpTabs.length} Tabs)</h4>
              <span className={`cdp-conn-pill ${cdpStatus?.connected ? "connected" : "standby"}`}>
                {cdpStatus?.connected ? `LINKED // ${cdpStatus.browser}` : "STANDBY"}
              </span>
            </div>

            <div className="cdp-new-tab-row">
              <input
                type="text"
                className="cdp-tab-input"
                placeholder="https://... (open new tab via CDP)"
                value={newTabUrl}
                onChange={(e) => setNewTabUrl(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    void handleOpenCDPTab(newTabUrl);
                  }
                }}
              />
              <button
                type="button"
                className="macro-btn play"
                onClick={() => void handleOpenCDPTab(newTabUrl)}
              >
                + Open
              </button>
              {!cdpStatus?.connected && (
                <button
                  type="button"
                  className="macro-btn play"
                  onClick={() => void handleLaunchDebugBrowser()}
                  title="Launch browser with --remote-debugging-port=9222"
                >
                  🚀 Launch CDP
                </button>
              )}
            </div>

            <div className="macro-items-list">
              {cdpTabs.length === 0 ? (
                <p className="console-desc">
                  No active CDP browser tabs found. Click &quot;Launch CDP&quot; or say &quot;Launch debug browser&quot;.
                </p>
              ) : (
                cdpTabs.map((t) => (
                  <div key={t.id} className="macro-item-card">
                    <div className="macro-info">
                      <h5>{t.title || "Untitled Tab"}</h5>
                      <p className="cdp-tab-url">{t.url}</p>
                    </div>
                    <div className="macro-actions">
                      <button
                        type="button"
                        className="macro-btn play"
                        onClick={() => void handleActivateCDPTab(t.id)}
                        title="Focus this tab"
                      >
                        Focus
                      </button>
                      <button
                        type="button"
                        className="macro-btn play"
                        onClick={() => void handleReloadCDPTab(t.id)}
                        title="Reload tab"
                      >
                        🔄
                      </button>
                      <button
                        type="button"
                        className="macro-btn del"
                        onClick={() => void handleCloseCDPTab(t.id)}
                        title="Close tab"
                      >
                        ×
                      </button>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          <div className="console-macros-section">
            <div className="cdp-section-header">
              <h4>Neural Voice Synthesis Engine</h4>
              <span className={`cdp-conn-pill ${ttsStatus?.has_elevenlabs ? "connected" : "standby"}`}>
                {ttsStatus?.has_elevenlabs ? "ELEVENLABS ONLINE" : "BROWSER NATIVE"}
              </span>
            </div>
            <p className="console-desc" style={{ marginBottom: "0.6rem" }}>
              Active Voice Model: <strong>{voicePreset === "cinematic_british" ? "Cinematic British (JARVIS)" : voicePreset === "tactical_crisp" ? "Tactical Crisp" : "Browser Web Speech"}</strong>
            </p>
            <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
              <button
                type="button"
                className={`protocol-quick-btn ${voicePreset === "cinematic_british" ? "wakeword-active" : ""}`}
                onClick={() => {
                  setVoicePreset("cinematic_british");
                  setTelemetry((prev) => ({ ...prev, activeVoice: "Cinematic British (Neural)" }));
                  speakAtlas("Voice synthesizer configured to Cinematic British, sir.");
                }}
                title="Hyper-realistic studio-grade British gentleman neural voice"
              >
                👑 Cinematic British
              </button>
              <button
                type="button"
                className={`protocol-quick-btn ${voicePreset === "tactical_crisp" ? "wakeword-active" : ""}`}
                onClick={() => {
                  setVoicePreset("tactical_crisp");
                  setTelemetry((prev) => ({ ...prev, activeVoice: "Tactical Crisp (Neural)" }));
                  speakAtlas("Tactical crisp neural voice online and operational, sir.");
                }}
                title="Fast, clear operational neural voice"
              >
                ⚡ Tactical Crisp
              </button>
              <button
                type="button"
                className={`protocol-quick-btn ${voicePreset === "browser" ? "wakeword-active" : ""}`}
                onClick={() => {
                  setVoicePreset("browser");
                  setTelemetry((prev) => ({ ...prev, activeVoice: "Browser Web Speech (Native)" }));
                  speakAtlas("Native browser speech synthesis engaged, sir.");
                }}
                title="Zero-latency local browser synthesis"
              >
                🔊 Native Browser
              </button>
            </div>
          </div>
        </aside>
      )}
    </div>
  );
}

// Backward-compatible alias
export const JarvisCore = AtlasCore;
