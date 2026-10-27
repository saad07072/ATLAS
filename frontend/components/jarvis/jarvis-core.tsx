"use client";

import type { JSX } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { cleanTextForSpeech } from "@/services/voice";
import { sendChatMessage } from "@/services/api";

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

export function AtlasCore(): JSX.Element {
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
  const [hudConsoleOpen, setHudConsoleOpen] = useState(false);

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

  useEffect(() => {
    isActiveRef.current = isActive;
  }, [isActive]);

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
  // 2. Speech Synthesis (ATLAS Voice Protocol)
  // -------------------------------------------------------------
  const speakAtlas = useCallback((text: string) => {
    if (typeof window === "undefined" || !window.speechSynthesis) return;

    window.speechSynthesis.cancel();
    const cleanText = cleanTextForSpeech(text);
    if (!cleanText) {
      isBusyRef.current = false;
      setAtlasState("listening");
      startRecognitionSafe();
      return;
    }

    const utterance = new SpeechSynthesisUtterance(cleanText);
    const voices = window.speechSynthesis.getVoices();

    // Prefer British/UK deep clear male voices (Paul Bettany style)
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
      setTelemetry((prev) => ({ ...prev, activeVoice: englishVoice.name }));
    }

    utterance.pitch = 0.94;
    utterance.rate = 1.03;

    let fallbackTimer: NodeJS.Timeout | null = null;

    const handleSpeechEnd = () => {
      if (fallbackTimer) clearTimeout(fallbackTimer);
      isBusyRef.current = false;
      accumulatedTextRef.current = "";
      setTranscript("");
      // Return seamlessly to ambient listening loop
      setAtlasState("listening");
      startRecognitionSafe();
    };

    utterance.onstart = () => {
      isBusyRef.current = true;
      setAtlasState("speaking");
    };

    utterance.onend = handleSpeechEnd;
    utterance.onerror = handleSpeechEnd;

    // Safety fallback: ensure speech state unlocks even if browser drops onend
    const wordCount = cleanText.split(/\s+/).length;
    const estimatedDurationMs = Math.max(3200, (wordCount / 2.0) * 1000 + 2200);
    fallbackTimer = setTimeout(handleSpeechEnd, estimatedDurationMs);

    window.speechSynthesis.speak(utterance);
  }, [startRecognitionSafe]);

  // -------------------------------------------------------------
  // 3. Backend Agent Request Dispatcher
  // -------------------------------------------------------------
  const sendToAtlas = useCallback(
    async (userMessage: string) => {
      const query = userMessage.trim();
      if (!query) return;

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

      try {
        const data = await sendChatMessage(
          query,
          [],
          conversationIdRef.current,
        );

        if (data.conversation_id) {
          conversationIdRef.current = data.conversation_id;
        }

        const reply = data.message || "Right away, sir. Task acknowledged.";
        setAtlasResponse(reply);
        speakAtlas(reply);
      } catch (err) {
        const errorReply =
          err instanceof Error
            ? err.message
            : "I encountered an issue processing your request, sir. The backend neural core may be reconnecting.";
        setAtlasResponse(errorReply);
        speakAtlas(errorReply);
      }
    },
    [speakAtlas],
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

      setTranscript(activeText);
      accumulatedTextRef.current = activeText;
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
      if (isActiveRef.current && !isBusyRef.current) {
        setTimeout(() => {
          if (isActiveRef.current && !isBusyRef.current) {
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
      } else if (e.code === "Escape") {
        if (atlasStateRef.current === "speaking") {
          window.speechSynthesis?.cancel();
          isBusyRef.current = false;
          setAtlasState("listening");
          startRecognitionSafe();
        }
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [activateAtlas, isActive, sendToAtlas, startRecognitionSafe]);

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
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
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
      const centerY = canvas.height / 2;

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
        setTelemetry((prev) => ({
          ...prev,
          audioLevel: Math.round(audioLevel * 100),
          frequency: Math.round(300 + audioLevel * 1200),
        }));
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
      const baseRadius = 115 + dynamicPulse + speechPulse + audioLevel * 45;

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
      className="atlas-viewport"
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
          <span className="hud-val">GEMINI FLASH LATEST</span>
        </div>
        <div className="hud-telemetry-row">
          <span>STATE:</span>
          <span className={`hud-val state-${atlasState}`}>
            {atlasState.toUpperCase()}
          </span>
        </div>
      </div>

      {/* 3. Top-Right Audio & Memory Telemetry HUD */}
      <div className="atlas-hud-top-right">
        <div className="hud-badge right-aligned">
          <span>SYSTEM DIAGNOSTICS</span>
          <span className="hud-dot green" />
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

        {/* Minimalist Switch to System Console (Discreet Drawer) */}
        <button
          type="button"
          className="hud-console-trigger"
          onClick={(e) => {
            e.stopPropagation();
            setHudConsoleOpen(!hudConsoleOpen);
          }}
          title="Toggle System Management Console"
        >
          {hudConsoleOpen ? "[ HIDE CONSOLE ]" : "[ SYSTEM CONSOLE ]"}
        </button>
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
        {/* User Input Stream */}
        {transcript && (
          <div className="dialogue-bubble user-stream">
            <span className="dialogue-speaker">YOU &gt;</span>
            <span className="dialogue-text">&ldquo;{transcript}&rdquo;</span>
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
        </div>

        {/* Prompt Cue */}
        <div className="atlas-cue">
          {!isActive ? (
            <span className="cue-pulse">CLICK ANYWHERE OR PRESS SPACEBAR TO INITIALIZE</span>
          ) : atlasState === "listening" ? (
            <span className="cue-listening">
              <span className="wave-icon" /> LISTENING... SPEAK NATURALLY, SIR
            </span>
          ) : atlasState === "processing" ? (
            <span className="cue-thinking">COMPUTING NEURAL RESPONSE...</span>
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
        </aside>
      )}
    </div>
  );
}

// Backward-compatible alias
export const JarvisCore = AtlasCore;
