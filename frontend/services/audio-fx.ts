/**
 * ATLAS Procedural Audio & Sound FX Engine
 *
 * Fully synthesized Web Audio API sound effects for the Mark VII JARVIS/ATLAS HUD.
 * Zero external audio files, zero HTTP requests, zero loading latency, 100% offline.
 */

const SFX_MUTED_STORAGE_KEY = "atlas_sfx_muted";

export class AudioFxService {
  private static instance: AudioFxService | null = null;
  private audioCtx: AudioContext | null = null;
  private masterGain: GainNode | null = null;
  private muted: boolean = false;

  private constructor() {
    if (typeof window !== "undefined") {
      try {
        const stored = localStorage.getItem(SFX_MUTED_STORAGE_KEY);
        this.muted = stored === "true";
      } catch {
        this.muted = false;
      }
    }
  }

  public static getInstance(): AudioFxService {
    if (!AudioFxService.instance) {
      AudioFxService.instance = new AudioFxService();
    }
    return AudioFxService.instance;
  }

  /**
   * Initializes or resumes the Web Audio context. Must be called in response to a user gesture.
   */
  public async ensureContext(): Promise<AudioContext | null> {
    if (typeof window === "undefined") return null;

    if (!this.audioCtx) {
      const AudioCtxConstructor =
        window.AudioContext ||
        (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!AudioCtxConstructor) return null;

      try {
        this.audioCtx = new AudioCtxConstructor();
        this.masterGain = this.audioCtx.createGain();
        this.masterGain.gain.setValueAtTime(this.muted ? 0 : 0.22, this.audioCtx.currentTime);
        this.masterGain.connect(this.audioCtx.destination);
      } catch (err) {
        console.warn("Could not create Web Audio Context:", err);
        return null;
      }
    }

    if (this.audioCtx.state === "suspended") {
      try {
        await this.audioCtx.resume();
      } catch {
        // May wait for additional user gesture
      }
    }

    return this.audioCtx;
  }

  public isMuted(): boolean {
    return this.muted;
  }

  public setMuted(muted: boolean): void {
    this.muted = muted;
    if (typeof window !== "undefined") {
      try {
        localStorage.setItem(SFX_MUTED_STORAGE_KEY, String(muted));
      } catch {
        // Storage unavailable
      }
    }
    if (this.masterGain && this.audioCtx) {
      this.masterGain.gain.setTargetAtTime(muted ? 0 : 0.22, this.audioCtx.currentTime, 0.02);
    }
  }

  public toggleMute(): boolean {
    this.setMuted(!this.muted);
    return this.muted;
  }

  /**
   * 1. BOOT / INITIALIZATION ARPEGGIO
   * Holographic power-up chord: rising sub-bass resonance + crystal arpeggio (C5 -> E5 -> G5 -> C6).
   */
  public async playBoot(): Promise<void> {
    if (this.muted) return;
    const ctx = await this.ensureContext();
    if (!ctx || !this.masterGain) return;

    const t = ctx.currentTime;

    // Sub-bass sweep
    const subOsc = ctx.createOscillator();
    const subGain = ctx.createGain();
    subOsc.type = "sine";
    subOsc.frequency.setValueAtTime(80, t);
    subOsc.frequency.exponentialRampToValueAtTime(260, t + 0.35);

    subGain.gain.setValueAtTime(0.001, t);
    subGain.gain.linearRampToValueAtTime(0.35, t + 0.08);
    subGain.gain.exponentialRampToValueAtTime(0.001, t + 0.45);

    subOsc.connect(subGain);
    subGain.connect(this.masterGain);

    subOsc.start(t);
    subOsc.stop(t + 0.45);

    // Holographic arpeggio notes (C5=523Hz, E5=659Hz, G5=784Hz, C6=1046Hz)
    const notes = [
      { freq: 523.25, time: 0.08, dur: 0.22 },
      { freq: 659.25, time: 0.16, dur: 0.25 },
      { freq: 783.99, time: 0.24, dur: 0.28 },
      { freq: 1046.5, time: 0.32, dur: 0.55 },
    ];

    notes.forEach(({ freq, time, dur }) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      const filter = ctx.createBiquadFilter();

      osc.type = "triangle";
      osc.frequency.setValueAtTime(freq, t + time);

      filter.type = "bandpass";
      filter.frequency.setValueAtTime(freq * 1.5, t + time);
      filter.Q.setValueAtTime(3.0, t + time);

      gain.gain.setValueAtTime(0.001, t + time);
      gain.gain.linearRampToValueAtTime(0.28, t + time + 0.015);
      gain.gain.exponentialRampToValueAtTime(0.0001, t + time + dur);

      osc.connect(filter);
      filter.connect(gain);
      gain.connect(this.masterGain!);

      osc.start(t + time);
      osc.stop(t + time + dur);
    });
  }

  /**
   * 2. LISTENING CHIRP (Microphone Active)
   * High-tech dual-tone chirp signaling active ambient voice reception.
   */
  public async playListenStart(): Promise<void> {
    if (this.muted) return;
    const ctx = await this.ensureContext();
    if (!ctx || !this.masterGain) return;

    const t = ctx.currentTime;

    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    const filter = ctx.createBiquadFilter();

    osc.type = "sine";
    osc.frequency.setValueAtTime(880, t);
    osc.frequency.exponentialRampToValueAtTime(1320, t + 0.08);

    filter.type = "highpass";
    filter.frequency.setValueAtTime(600, t);

    gain.gain.setValueAtTime(0.001, t);
    gain.gain.linearRampToValueAtTime(0.22, t + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.14);

    osc.connect(filter);
    filter.connect(gain);
    gain.connect(this.masterGain);

    osc.start(t);
    osc.stop(t + 0.14);
  }

  /**
   * 3. SPEECH COMMIT / PROMPT DISPATCHED
   * Fast subtle confirmation blip (1174Hz -> 880Hz) when speech ends and task is dispatched.
   */
  public async playCommit(): Promise<void> {
    if (this.muted) return;
    const ctx = await this.ensureContext();
    if (!ctx || !this.masterGain) return;

    const t = ctx.currentTime;

    const osc = ctx.createOscillator();
    const gain = ctx.createGain();

    osc.type = "sine";
    osc.frequency.setValueAtTime(1174.66, t);
    osc.frequency.exponentialRampToValueAtTime(880, t + 0.09);

    gain.gain.setValueAtTime(0.001, t);
    gain.gain.linearRampToValueAtTime(0.18, t + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.12);

    osc.connect(gain);
    gain.connect(this.masterGain);

    osc.start(t);
    osc.stop(t + 0.12);
  }

  /**
   * 4. ACTION VERIFIED / SUCCESS CHIME
   * Resonant crystal chime chord (E6 1318Hz + G#6 1661Hz + B6 1975Hz) when task execution is verified.
   */
  public async playSuccess(): Promise<void> {
    if (this.muted) return;
    const ctx = await this.ensureContext();
    if (!ctx || !this.masterGain) return;

    const t = ctx.currentTime;
    const chords = [1318.51, 1661.22, 1975.53];

    chords.forEach((freq, idx) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      const delay = idx * 0.035;

      osc.type = "sine";
      osc.frequency.setValueAtTime(freq, t + delay);

      gain.gain.setValueAtTime(0.001, t + delay);
      gain.gain.linearRampToValueAtTime(0.2, t + delay + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, t + delay + 0.55);

      osc.connect(gain);
      gain.connect(this.masterGain!);

      osc.start(t + delay);
      osc.stop(t + delay + 0.55);
    });
  }

  /**
   * 5. ALERT / TASK ERROR WARNING
   * High-tech dual-pulse alert tone (440Hz -> 330Hz) for failures or safety intervention.
   */
  public async playAlert(): Promise<void> {
    if (this.muted) return;
    const ctx = await this.ensureContext();
    if (!ctx || !this.masterGain) return;

    const t = ctx.currentTime;

    [0, 0.12].forEach((offset) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      const filter = ctx.createBiquadFilter();

      osc.type = "sawtooth";
      osc.frequency.setValueAtTime(440, t + offset);
      osc.frequency.linearRampToValueAtTime(330, t + offset + 0.08);

      filter.type = "lowpass";
      filter.frequency.setValueAtTime(800, t + offset);

      gain.gain.setValueAtTime(0.001, t + offset);
      gain.gain.linearRampToValueAtTime(0.18, t + offset + 0.01);
      gain.gain.exponentialRampToValueAtTime(0.0001, t + offset + 0.1);

      osc.connect(filter);
      filter.connect(gain);
      gain.connect(this.masterGain!);

      osc.start(t + offset);
      osc.stop(t + offset + 0.1);
    });
  }

  /**
   * 6. STANDBY / DEACTIVATION SWEEP
   * Futuristic downward harmonic sweep when entering standby.
   */
  public async playStandby(): Promise<void> {
    if (this.muted) return;
    const ctx = await this.ensureContext();
    if (!ctx || !this.masterGain) return;

    const t = ctx.currentTime;

    const osc = ctx.createOscillator();
    const gain = ctx.createGain();

    osc.type = "sine";
    osc.frequency.setValueAtTime(523.25, t);
    osc.frequency.exponentialRampToValueAtTime(130.81, t + 0.3);

    gain.gain.setValueAtTime(0.001, t);
    gain.gain.linearRampToValueAtTime(0.18, t + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.35);

    osc.connect(gain);
    gain.connect(this.masterGain);

    osc.start(t);
    osc.stop(t + 0.35);
  }

  /**
   * 7. HOLOGRAPHIC UI CLICK / TAP
   * Subtle glass click for buttons and console toggles.
   */
  public async playUiTap(): Promise<void> {
    if (this.muted) return;
    const ctx = await this.ensureContext();
    if (!ctx || !this.masterGain) return;

    const t = ctx.currentTime;

    const osc = ctx.createOscillator();
    const gain = ctx.createGain();

    osc.type = "sine";
    osc.frequency.setValueAtTime(2400, t);
    osc.frequency.exponentialRampToValueAtTime(1200, t + 0.025);

    gain.gain.setValueAtTime(0.001, t);
    gain.gain.linearRampToValueAtTime(0.12, t + 0.005);
    gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.03);

    osc.connect(gain);
    gain.connect(this.masterGain);

    osc.start(t);
    osc.stop(t + 0.03);
  }

  /**
   * Calculates the dominant frequency (pitch peak) in Hz from an AnalyserNode.
   */
  public calculateDominantFrequency(
    analyser: AnalyserNode,
    sampleRate: number,
    frequencyData: Uint8Array<ArrayBuffer> | Uint8Array,
  ): number {
    analyser.getByteFrequencyData(frequencyData as unknown as Uint8Array<ArrayBuffer>);

    let maxVal = -1;
    let maxIdx = -1;

    // Search from ~80Hz to ~3500Hz (speech range)
    const binSize = sampleRate / analyser.fftSize;
    const startBin = Math.floor(80 / binSize);
    const endBin = Math.min(frequencyData.length - 1, Math.ceil(3500 / binSize));

    for (let i = startBin; i <= endBin; i++) {
      if (frequencyData[i] > maxVal) {
        maxVal = frequencyData[i];
        maxIdx = i;
      }
    }

    if (maxVal < 15 || maxIdx <= 0) {
      return 432; // Default harmonic baseline
    }

    return Math.round(maxIdx * binSize);
  }
}

export const audioFx = AudioFxService.getInstance();
