"""SAHJONY Studio 360 — free local music generator.

100% local, zero cost, zero license risk: every sound is synthesized
with numpy (drums, bass, chords, brass-like lead). No samples, no APIs.

Presets: regueton (dembow), balada, salsa, trap, pop.
Usage: python3 free_music.py --style regueton --secs 60 --out /tmp/x.wav
"""
import argparse
import math
import os
import subprocess
import wave

import numpy as np

SR = 44100

# ------------------------------------------------------------------ helpers

def _adsr(n, a=0.005, d=0.05, s=0.7, r=0.08):
    """Simple ADSR envelope over n samples."""
    env = np.ones(n)
    na, nd, nr = int(a * SR), int(d * SR), int(r * SR)
    if na > 0:
        env[:na] = np.linspace(0, 1, na)
    if nd > 0 and n > na:
        env[na:na + nd] = np.linspace(1, s, min(nd, n - na))
    if nr > 0 and n > nr:
        env[-nr:] *= np.linspace(1, 0, nr)
    return env


def _tone(freq, n, kind="sine", vibrato=0.0, vib_rate=5.5):
    t = np.arange(n) / SR
    if vibrato:
        freq = freq * (1 + vibrato * np.sin(2 * math.pi * vib_rate * t))
    ph = 2 * math.pi * np.cumsum(freq if isinstance(freq, np.ndarray) else
                                 np.full(n, freq)) / SR
    if kind == "sine":
        return np.sin(ph)
    if kind == "square":
        return np.sign(np.sin(ph))
    if kind == "saw":
        return 2 * ((ph / (2 * math.pi)) % 1) - 1
    if kind == "tri":
        return 2 * np.abs(2 * ((ph / (2 * math.pi)) % 1) - 1) - 1
    return np.sin(ph)


def _brass(freq, n):
    """Brass/trombone-ish: saw + square blend with vibrato and soft attack."""
    vib = _tone(freq, n, "saw", vibrato=0.006)
    sq = _tone(freq, n, "square", vibrato=0.006)
    sig = 0.65 * vib + 0.35 * sq
    # lowpass-ish: tame harsh highs by mixing a sine octave
    sig = 0.8 * sig + 0.4 * _tone(freq, n, "sine")
    env = _adsr(n, a=0.03, d=0.08, s=0.85, r=0.12)
    return sig * env


def _kick(n):
    t = np.arange(n) / SR
    f = 150 * np.exp(-t * 30) + 45
    sig = np.sin(2 * math.pi * np.cumsum(f) / SR)
    return sig * np.exp(-t * 18)


def _snare(n):
    t = np.arange(n) / SR
    noise = np.random.default_rng(7).standard_normal(n)
    tone = np.sin(2 * math.pi * 190 * t)
    return (0.6 * noise + 0.4 * tone) * np.exp(-t * 22)


def _hat(n, open_=False):
    rng = np.random.default_rng(13)
    noise = rng.standard_normal(n)
    # crude highpass
    hp = noise - np.convolve(noise, np.ones(32) / 32, mode="same")
    decay = 30 if not open_ else 8
    return hp * np.exp(-np.arange(n) / SR * decay) * 0.5


def _pluck(freq, n):
    sig = _tone(freq, n, "tri") + 0.3 * _tone(freq * 2, n, "sine")
    return sig * np.exp(-np.arange(n) / SR * 6)


def _bass_note(freq, n):
    sig = _tone(freq, n, "sine") + 0.25 * _tone(freq, n, "square")
    return sig * _adsr(n, a=0.008, d=0.1, s=0.8, r=0.1)


def _place(track, sig, at_sec, gain=1.0):
    i = int(at_sec * SR)
    j = min(len(track), i + len(sig))
    if i < len(track):
        track[i:j] += sig[: j - i] * gain


def _reverb(sig, decay=2.2, wet=0.18):
    n = int(SR * 0.35)
    ir = np.random.default_rng(3).standard_normal(n) * np.exp(
        -np.arange(n) / SR * decay)
    wet_sig = np.convolve(sig, ir, mode="full")[: len(sig)]
    wet_sig *= np.max(np.abs(sig)) / (np.max(np.abs(wet_sig)) + 1e-9)
    return (1 - wet) * sig + wet * wet_sig


def _normalize(sig, peak=0.89):
    m = np.max(np.abs(sig))
    if m > 1e-9:
        sig = sig / m * peak
    return sig


def _write_wav(path, sig):
    sig = _normalize(sig)
    pcm = (sig * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


# ------------------------------------------------------------------ note utils

_SEMI = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def _freq(note):
    """note like 'D3' -> Hz."""
    name = note[:-1]
    octv = int(note[-1])
    semis = _SEMI[name[0].upper()]
    if len(name) > 1 and name[1] == "#":
        semis += 1
    midi = 12 * (octv + 1) + semis
    return 440.0 * 2 ** ((midi - 69) / 12)


# ------------------------------------------------------------------ styles

def _style_regueton(secs):
    """Dembow 95 BPM, Dm - Bb - F - C, brass stabs + lead."""
    bpm = 95
    beat = 60.0 / bpm
    bar = beat * 4
    n = int(secs * SR)
    drums = np.zeros(n)
    bass = np.zeros(n)
    chords = np.zeros(n)
    lead = np.zeros(n)
    progs = [["D3", "A#2", "F2", "C3"]]  # roots
    chord_tones = {
        "D3": ["D4", "F4", "A4"], "A#2": ["A#3", "D4", "F4"],
        "F2": ["F3", "A3", "C4"], "C3": ["C4", "E4", "G4"],
    }
    # catchy little lead motif (minor pentatonic-ish), per bar
    motifs = [
        ["D5", None, "F5", "E5", None, "D5", "C5", None],
        [None, "A#4", None, "A4", "G4", None, "F4", None],
        ["F5", None, "G5", "A5", None, "G5", "F5", "E5"],
        ["E5", None, "D5", None, "C5", "D5", None, None],
    ]
    nbars = int(secs / bar) + 1
    for b in range(nbars):
        t0 = b * bar
        root = progs[0][b % 4]
        motif = motifs[b % 4]
        # --- dembow drums: kick 1, syncopated 3&, snare 2&4, hats 8ths
        for k in range(4):
            bt = t0 + k * beat
            _place(drums, _kick(int(SR * 0.25)), bt, 0.9)
            _place(drums, _hat(int(SR * 0.05)), bt + beat / 2, 0.5)
            if k in (1, 3):
                _place(drums, _snare(int(SR * 0.2)), bt, 0.8)
        _place(drums, _kick(int(SR * 0.25)), t0 + 2.5 * beat, 0.7)  # dembow kick
        _place(drums, _snare(int(SR * 0.2)), t0 + 3.5 * beat, 0.55)
        for h in range(8):
            _place(drums, _hat(int(SR * 0.04)), t0 + h * beat / 2, 0.35)
        # --- bass on roots, dembow-ish rhythm
        for off in (0, 0.75, 1.5, 2.5, 3.0):
            _place(bass, _bass_note(_freq(root), int(SR * 0.3)),
                   t0 + off * beat, 0.75)
        # --- chord stabs (offbeat skank)
        for off in (0.5, 1.5, 2.5, 3.5):
            stab = sum(_pluck(_freq(nn), int(SR * 0.22))
                       for nn in chord_tones[root]) / 3
            _place(chords, stab, t0 + off * beat, 0.5)
        # --- brass lead motif
        step = beat / 2
        for i, nn in enumerate(motif):
            if nn:
                _place(lead, _brass(_freq(nn), int(SR * step * 0.95)),
                       t0 + i * step, 0.42)
    mix = drums * 0.9 + bass * 0.85 + chords * 0.7 + lead * 0.8
    return _reverb(_normalize(mix), wet=0.14)


def _style_balada(secs):
    bpm = 72
    beat = 60.0 / bpm
    bar = beat * 4
    n = int(secs * SR)
    piano = np.zeros(n)
    pad = np.zeros(n)
    progs = [["A2", "F2", "C3", "G2"]]
    tones = {"A2": ["A3", "C4", "E4"], "F2": ["F3", "A3", "C4"],
             "C3": ["C4", "E4", "G4"], "G2": ["G3", "B3", "D4"]}
    nbars = int(secs / bar) + 1
    for b in range(nbars):
        t0 = b * bar
        root = progs[0][b % 4]
        arp = tones[root] * 2
        for i, nn in enumerate(arp):
            _place(piano, _pluck(_freq(nn), int(SR * 0.6)),
                   t0 + i * beat / 2, 0.5)
        for nn in tones[root]:
            _place(pad, _tone(_freq(nn), int(SR * bar), "sine"),
                   t0, 0.12)
    return _reverb(_normalize(piano * 0.8 + pad), wet=0.25)


def _style_salsa(secs):
    bpm = 180
    beat = 60.0 / bpm
    bar = beat * 4
    n = int(secs * SR)
    perc = np.zeros(n)
    piano = np.zeros(n)
    bass = np.zeros(n)
    montuno = [["C4", "E4", "G4", "A4", "G4", "E4", "D4", "E4"]]
    roots = ["C2", "G2", "A2", "F2"]
    nbars = int(secs / bar) + 1
    for b in range(nbars):
        t0 = b * bar
        # cascara-ish: hats on 8ths, accent 2-3
        for h in range(8):
            _place(perc, _hat(int(SR * 0.04)), t0 + h * beat / 2,
                   0.5 if h % 2 == 0 else 0.3)
        for k in (1, 3):
            _place(perc, _snare(int(SR * 0.15)), t0 + k * beat, 0.6)
        _place(perc, _kick(int(SR * 0.2)), t0, 0.6)
        _place(perc, _kick(int(SR * 0.2)), t0 + 2.5 * beat, 0.5)
        # montuno
        for i, nn in enumerate(montuno[0]):
            _place(piano, _pluck(_freq(nn), int(SR * 0.25)),
                   t0 + i * beat / 2, 0.55)
        # tumbao bass
        for off, nn in ((0, roots[b % 4]), (1.5, roots[b % 4]),
                        (2.5, roots[(b + 1) % 4])):
            _place(bass, _bass_note(_freq(nn), int(SR * 0.3)),
                   t0 + off * beat, 0.7)
    return _reverb(_normalize(perc * 0.8 + piano * 0.75 + bass * 0.8),
                   wet=0.12)


def _style_trap(secs):
    bpm = 140
    beat = 60.0 / bpm
    bar = beat * 4
    n = int(secs * SR)
    drums = np.zeros(n)
    b808 = np.zeros(n)
    dark = np.zeros(n)
    roots = ["D2", "D2", "A#1", "C2"]
    nbars = int(secs / bar) + 1
    for b in range(nbars):
        t0 = b * bar
        root = roots[b % 4]
        _place(drums, _kick(int(SR * 0.3)), t0, 0.9)
        _place(drums, _snare(int(SR * 0.2)), t0 + beat, 0.8)
        _place(drums, _kick(int(SR * 0.3)), t0 + 2.75 * beat, 0.7)
        _place(drums, _snare(int(SR * 0.2)), t0 + 3 * beat, 0.8)
        for h in range(16):
            g = 0.6 if h % 4 == 2 else 0.32
            _place(drums, _hat(int(SR * 0.03)), t0 + h * beat / 4, g)
        for off in (0, 1.0, 2.5):
            _place(b808, _bass_note(_freq(root), int(SR * 0.5)),
                   t0 + off * beat, 0.9)
        for nn in ("D4", "F4", "A4"):
            _place(dark, _tone(_freq(nn), int(SR * bar), "sine"), t0, 0.1)
    return _reverb(_normalize(drums * 0.85 + b808 + dark * 0.7), wet=0.15)


def _style_pop(secs):
    bpm = 120
    beat = 60.0 / bpm
    bar = beat * 4
    n = int(secs * SR)
    drums = np.zeros(n)
    chords = np.zeros(n)
    bass = np.zeros(n)
    progs = ["C3", "G2", "A2", "F2"]
    tones = {"C3": ["C4", "E4", "G4"], "G2": ["G3", "B3", "D4"],
             "A2": ["A3", "C4", "E4"], "F2": ["F3", "A3", "C4"]}
    nbars = int(secs / bar) + 1
    for b in range(nbars):
        t0 = b * bar
        root = progs[b % 4]
        for k in range(4):
            _place(drums, _kick(int(SR * 0.25)), t0 + k * beat, 0.85)
            _place(drums, _hat(int(SR * 0.04)), t0 + k * beat + beat / 2,
                   0.4)
            if k % 2 == 1:
                _place(drums, _snare(int(SR * 0.18)), t0 + k * beat, 0.75)
        for off in (0, 1, 2, 3):
            stab = sum(_pluck(_freq(nn), int(SR * 0.3))
                       for nn in tones[root]) / 3
            _place(chords, stab, t0 + off * beat, 0.55)
            _place(bass, _bass_note(_freq(root), int(SR * 0.3)),
                   t0 + off * beat, 0.7)
    return _reverb(_normalize(drums * 0.85 + chords * 0.7 + bass * 0.8),
                   wet=0.16)


STYLES = {
    "regueton": ("Reguetón Dembow 🎺", _style_regueton),
    "balada": ("Balada 🎹", _style_balada),
    "salsa": ("Salsa 💃", _style_salsa),
    "trap": ("Trap 🔥", _style_trap),
    "pop": ("Pop ✨", _style_pop),
}


def generate(style, secs, out_wav, seed=None):
    if style not in STYLES:
        raise ValueError(f"estilo no válido: {style}")
    if seed is not None:
        np.random.seed(seed)
    secs = max(5, min(600, int(secs)))
    sig = STYLES[style][1](secs)
    _write_wav(out_wav, sig)
    return out_wav


def to_mp3(wav_path, mp3_path):
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", wav_path,
           "-codec:a", "libmp3lame", "-b:a", "128k", mp3_path]
    subprocess.run(cmd, check=True)
    return mp3_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--style", default="regueton", choices=list(STYLES))
    ap.add_argument("--secs", type=int, default=60)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    tmp = args.out + ".tmp.wav"
    generate(args.style, args.secs, tmp)
    if args.out.lower().endswith(".mp3"):
        to_mp3(tmp, args.out)
        os.remove(tmp)
    else:
        os.rename(tmp, args.out)
    print("OK", args.out)
