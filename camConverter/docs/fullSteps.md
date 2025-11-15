Alright, buckle up 😄 Let’s design the whole thing end-to-end.

I’ll walk through:

1. System block diagram (TX + RX)
2. CVBS timing & where we’re allowed to “touch” the signal
3. Scrambling algorithm (segment shuffle, inversion, shift, burst tricks)
4. Hardware blocks (analog front-end, ADC/DAC choices, sync detect)
5. Firmware architecture on STM32 (scrambler)
6. Firmware architecture on STM32 (descrambler)
7. Keying & session setup
8. PCB & layout considerations
9. Minimal viable version vs “full crypto” version

---

## 1. High-level system architecture

**TX side (on the quad):**

```text
[FPV Camera]
    |
    | Composite video (CVBS)
    v
[Analog Front-End + Clamp]  --> feeds sync comparator + ADC
    |
    v
[ADC] --(DMA)--> [STM32 Scrambler]
                       |
                       | CVBS (scrambled via DAC)
                       v
                 [Analog Back-End + Filter]
                       |
                       v
                    [VTX]
```

**RX side (ground station / goggles side):**

```text
[VRX 5.8 GHz Receiver]
    |
    | Composite video (scrambled CVBS)
    v
[Analog Front-End + Clamp]
    |
    v
[ADC] --(DMA)--> [STM32 Descrambler]
                       |
                       | CVBS (restored)
                       v
                 [Analog Back-End + Filter]
                       |
                       v
                 [Goggles / Screen / DVR]
```

**Digital “contract” between TX and RX:**

* Shared **256-bit key**
* Agreed **mode parameters**:

  * segments per line
  * which operations enabled
* Shared **frame counter scheme** (for nonce)

Everything else (sync, VTX/RX, camera, goggles) stays standard analog.

---

## 2. CVBS timing & where we’re allowed to operate

Very simplified **PAL line** (similar for NTSC, just timings differ):

```text
|<--------------------- ~64 µs total --------------------->|
| 4.7µs |  5.7µs   |<----------- ~52 µs ----------->|
+-------+----------+---------------------------------------+
| sync  | backporch|           active video                |
+-------+----------+---------------------------------------+
          ^ 2.25µs colorburst inside backporch (for color)
```

**We must not break:**

* Horizontal sync pulse timing
* Vertical sync structure (sequence of long/short pulses)
* Backporch baseline (black level)
* Colorburst amplitude + approximate timing

**We *can* safely scramble inside:**

* The **active video** region (≈ 52 µs)
* Possibly the color content (by messing with colorburst phase) as long as a burst is still present.

So: we detect **sync**, pass it through unchanged, and only manipulate **active video** samples.

---

## 3. Scrambling algorithm

We’ll design this in layers. Think of each line as:

```text
Line = [sync | backporch | active[0..N-1]]
```

We only touch `active[]`.

### 3.1 Sampling model

Let’s say we sample active video at **Fs ≈ 8–10 MHz** from an external 8-bit video ADC (recommended for quality).

For a PAL line:

* Active duration ≈ 52 µs
* Samples per line N ≈ 52e-6 * 10e6 = ~520 samples

We can split into **S segments**:

* e.g. `S = 16`
* Segment size: `seg_len = N / S ≈ 32–34 samples`

So:

```text
active = [seg0 | seg1 | seg2 | ... | seg15]
```

### 3.2 Cryptographic core

Use **ChaCha20** (or XChaCha20) in keystream mode.

* Key: 256 bits
* Nonce per frame: derived from:

  * Session ID (e.g. 64 bits)
  * Frame counter (e.g. 32 bits)
* Block counter: incremented per line or per operation

The ChaCha keystream never directly XORs the analog data.
Instead, we convert keystream bytes into **operation parameters**.

### 3.3 Per-line operations

Assume we have a chunk of keystream bytes for each line: `K_line`.

We derive:

1. **A permutation of [0..S-1]**

   Use Fisher–Yates shuffle seeded from `K_line`:

   * This defines how segments are rearranged.

2. **Per-segment flags & parameters** (from more keystream bytes):

   * Invert flag (`invert[i]` ∈ {0,1})
   * Pixel shift amount (`shift[i]` ∈ [0..seg_len-1])
   * Optional: amplitude offset/clipping, etc.

#### Step 1: Segment permutation

Scrambler TX:

```pseudocode
for i in 0..S-1:
    perm[i] = i
FisherYatesShuffle(perm, K_line)

for out_idx in 0..S-1:
    in_idx  = perm[out_idx]
    out_segment[out_idx] = in_segment[in_idx]
```

Descrambler RX does the **inverse**:

```pseudocode
# Recompute the same perm[] from the same K_line (same frame, same line)
for in_idx in 0..S-1:
    out_idx = perm[in_idx]
    in_segment[in_idx] = out_segment[out_idx]  # reverse mapping
```

Without key → impossible to know correct perm → image is cut and reassembled incorrectly.

#### Step 2: Per-segment pixel shift (circular)

Within each segment:

```pseudocode
shift[i] = K_line.nextByte() mod seg_len

tmp = segment[i].copy()
for p in 0..seg_len-1:
    out[p] = tmp[(p + shift[i]) mod seg_len]
```

Descrambler applies the inverse shift: `(p - shift[i]) mod seg_len`.

#### Step 3: Per-segment inversion

We can represent luminance in 8-bit space (0–255):

```pseudocode
if (K_line.nextBit() == 1):
    for p in 0..seg_len-1:
        out[p] = 255 - out[p]
```

Descrambler runs the same transform again (self-inverse).

---

### 3.4 Optional: Colorburst messing (if you want maximum “WTF” look)

* For PAL/NTSC, the colorburst is a small sine wave at subcarrier frequency during backporch.
* You can, per line, decide to **invert its phase** (0° → 180°) or even rotate more.
* This will cause wild color artifacts unless descrambled.
* Must be done *very* carefully, and likely with an external video encoder/decoder.

I’d treat colorburst messing as **advanced mode**.

---

## 4. Hardware building blocks

### 4.1 Analog Front-End (TX & RX)

You need:

1. **AC coupling and clamping**

   * Composite is typically 1 Vpp centered around some level.
   * Clamp it to a fixed DC level (e.g. sync tip close to 0 V, white near 1 V).
   * Use a simple clamp circuit + op-amp.

2. **Sync comparator**

   * Take the clamped composite and feed to a high-speed comparator.
   * Threshold between sync tip and backporch (e.g. ~0.3 V equivalent).
   * Output: digital pulses for H-sync/V-sync detection.

3. **Option A: External video ADC + DAC (recommended)**

   * 8–10 bit, 20–30 Msps ADC (e.g. generic “video ADC” chips).
   * 8–10 bit, 20–30 Msps DAC.

   Connect ADC parallel bus to STM32 via:

   * DCMI (camera interface) or
   * FMC/HSPI or
   * parallel GPIO + DMA

   Connect DAC bus similarly.

4. **Option B: Use STM32 internal ADC/DAC (more hacky)**

   * H7 ADC can reach a few Msps; borderline for nice video but workable if you accept slightly lower bandwidth.
   * Could sample at ~5–7 Msps and still get a “usable” analog picture.
   * For a first prototype, this is okay if expectations are calibrated.

**Given your background, I’d strongly recommend external video ADC/DAC.**

---

### 4.2 STM32 (“brain”)

On both scrambler and descrambler:

* **Peripherals:**

  * Timer for HSYNC/VSYNC detection and timestamps
  * DMA channels for:

    * ADC → Line buffer
    * Line buffer → DAC
  * SPI (or I²C) for configuration, key loading
* **Memory:**

  * 1–2 KB line buffer (double-buffered for ping-pong)
  * Extra buffers for permutations and temporary operations
* **Clock:**

  * > 200 MHz core clock (H7)
  * Enough throughput to process 16 segments per line in <52 µs

---

## 5. Firmware architecture – Scrambler (TX side)

Think “line machine” triggered by HSYNC.

### 5.1 State machine per frame

States:

1. **WAIT_VSYNC**
2. **IN_FRAME**
3. **LINE_ACTIVE** (per line)
4. **FRAME_DONE** (increment frame counter)

### 5.2 Peripherals setup

* **Comparator interrupt** or timer capture for HSYNC and VSYNC:

  * Detect VSYNC pattern (series of long pulses).
  * Reset frame counter at each VSYNC.
  * Count lines: line_idx++ at each HSYNC.

* **ADC + DMA**:

  * ADC runs continuously but we gate the DMA:

    * On HSYNC, we wait until backporch ends, then start DMA for active window
      (either via timer delay or a “sample window” timer).

* **DAC + DMA**:

  * Either:

    * real-time pipeline (read-modify-write within same line), or
    * 1-line delay (more realistic).

### 5.3 Line pipeline

Example with one-line delay (simpler):

1. **On HSYNC (line N)**:

   * If this line is “active video” (not in vertical blanking):

     * Configure Timer to start ADC DMA after backporch delay.
     * ADC DMA: writes `N` samples into `line_buffer_in`.
   * Meanwhile, we are outputting line N-1 via `line_buffer_out` → DAC with previous line’s scrambled samples.

2. **After ADC DMA completes**:

   * Generate **ChaCha keystream** for this line:

     * Input = key, nonce(frame_ctr), line index.
   * From keystream, derive:

     * perm[]
     * shift[]
     * invert flags
   * Apply operations:

     * Segment permutation
     * Pixel shifts
     * Inversion
   * Write result into `line_buffer_out`.

3. **Next HSYNC**:

   * Line N+1 starts, we repeat.

Vertical blanking lines can be passed through untouched (or lightly scrambled).

### 5.4 ChaCha implementation

* Use a **tiny C implementation**.
* Pre-generate keystream for several lines if CPU allows, or generate line-by-line.
* Since we only need a few hundred bytes per line, ChaCha overhead is small on H7.

---

## 6. Firmware architecture – Descrambler (RX side)

Almost identical to scrambler, except the operations are **inverted**.

Key points:

* Same sync detection mechanism.
* Same ADC/DAC pipeline.
* Same ChaCha key/nonce derivation:

  * Must use same frame counter, same line index.
* Same segment count, etc.

Descrambler pipeline:

1. Receive scrambled line via ADC DMA → `line_buffer_scrambled`.
2. Generate `K_line` (same as TX).
3. Recreate `perm[]`, `shift[]`, `invert[]`.
4. Apply inverse transform to reconstruct original line:

   * undo inversion
   * reverse shift
   * reverse permutation
5. Output to DAC.

If key or frame counter is wrong, output will be garbage.

---

## 7. Keying & Session Setup

We want:

* **Strong secrecy**
* **Replay-resistant**
* **User-friendly** (for FPV pilots)

### 7.1 Static key

* A static 256-bit key stored in flash on both scrambler and descrambler.
* Derived from pilot’s passphrase via e.g. PBKDF2/Argon2 offline.

### 7.2 Per-session nonces

On arming/boot:

* Scrambler chooses a random **64-bit session ID**.
* Scrambler encodes session ID in a few frames in a **visible / OSD-style header** or via a simple side channel (e.g. modulated onto a few specific lines, or via UART/2.4 GHz RF secondary link).

Nonce for ChaCha:

```text
nonce = concat(
    session_id (64 bits),
    frame_counter (32 bits)
)
```

Frame counter increments with each VSYNC.

Descrambler must:

* Receive session_id (out-of-band or via video)
* Start frame counter at the same time (or resync via pattern)

For a simpler v1: just start both devices roughly at the same time and rely on **monotonic frame counter**; add a resync pattern occasionally.

---

## 8. PCB & layout considerations

### 8.1 Video path

* Keep **analog paths short and clean**.
* Use 75 Ω impedance where appropriate.
* Place clamp/ op-amp / ADC / DAC physically close together.
* Use proper filtering (low-pass at ~7–8 MHz) to avoid aliasing.

### 8.2 Grounding & noise

* Separate **analog ground** and **digital ground** and join at a star point.
* Decouple all supply pins (0.1 µF + 1 µF).
* Use LDOs if possible for clean analog rails.

### 8.3 Connectors

* FPV cameras / VTX usually use:

  * 3-pin (V+, GND, Video) or 4-pin JST
* Your module will sit inline:

  * Input: camera cable
  * Output: VTX cable
* Same for ground unit: VRX → descrambler → goggles.

---

## 9. Minimal viable version vs “full crypto”

To actually build something in a reasonable time, I’d split into phases.

### Phase 1 – Minimal viable scrambler

Goal: Get *something* working on real gear quickly.

* Use **STM32H7 internal ADC + DAC** (or very simple external ADC/DAC).
* Only implement:

  * **line inversion** (sometimes invert full active line)
  * maybe **2–4 segment permutation**, no pixel shift
* Use **LFSR-based PRN** first (easiest), then swap to ChaCha once pipeline works.
* Keep key static & hard-coded.

This already produces a picture that is unusable for others but easy to debug.

### Phase 2 – Add full segment-permutation & pixel shift

* Increase segments to 8–16.
* Add per-segment pixel shifts.
* Switch to ChaCha20-based keystream.
* Start using frame counter + line index as ChaCha input.

### Phase 3 – External video ADC/DAC & better image quality

* Replace internal ADC/DAC with proper video-grade ones.
* Move sampling to 10–20 Msps.
* Improve front-end (proper clamp, op-amp driver).
* Tighten pipeline for lower noise and bandwidth preservation.

### Phase 4 – Session IDs + OSD-sideband channel

* Add a basic OSD overlay that writes the current session ID into a reserved area of the image.
* Descrambler uses that to sync nonce.

---

If you want, next step I can:

* Draft **concrete firmware pseudocode** for the line pipeline (TX + RX)
* Propose **specific STM32H7 pinouts & DMA mappings**
* Sketch a **first prototype schematic** (text-form, with parts)
* Or drill into **one piece** (e.g. “implement ChaCha20 + permutation logic in C for STM32”)

Pick one of those and I’ll go into “implementation mode” for that part.
