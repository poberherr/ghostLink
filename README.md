# ghostLink: Real-Time Analog Video Encryption

A low-latency, low-power system for securing analog video feeds by scrambling the video signal itself, renderable only by a receiver with a shared secret key.

## The Problem

Long-range battlefield drones often rely on analog video transmission due to its superior range and low power requirements. However, this creates a critical vulnerability:

* **Unencrypted:** Analog video is broadcast "in the clear."
* **Easily Intercepted:** Any adversary with a simple receiver can see the drone's live video feed in real-time.
* **High Risk:** This exposes troop positions, reconnaissance data, and operational plans.

Our challenge is to secure this analog link without adding latency or complex, power-hungry digital encryption hardware.

## 💡 Our Solution

We've designed a "matched pair" system: a **Scrambler** (on the drone) and a **Descrambler** (at the ground station). Our method manipulates the analog video signal directly, making it unwatchable to anyone without the correct key.

The technique is based on **Pseudo-Random Sync Suppression & Video Inversion**.

### How It Works

1.  **Shared Secret Key:** Both the Scrambler and Descrambler are programmed with the same `SECRET_KEY`.

2.  **Rolling Seed:** To prevent the scrambling pattern from ever repeating, the system uses a **rolling key** based on a `frameCounter`.
    * For every new frame (on the V-Sync pulse), both units calculate a new, temporary seed: `this_frame_seed = HASH(SECRET_KEY + frameCounter)`.
    * This seed is used to initialize a Pseudo-Random Number Generator (PRNG).

3.  **The Scrambler (Drone):**
    * For each new line of video (on the H-Sync pulse), it gets a "random" number from its PRNG.
    * **Decision 1: Invert.** If the number is odd, it sends the video signal through an op-amp to *invert* it (black becomes white, white becomes black).
    * **Decision 2: Suppress Sync.** If the number is even, it *removes* the horizontal sync pulse for that line, making it impossible for a standard receiver to lock onto the picture.

4.  **The Descrambler (Ground):**
    * The descrambler, running the *exact same* PRNG with the *exact same* seed, *predicts* what the scrambler did for each line.
    * **Action 1:** If it knows the line was inverted, it inverts it *back* to normal.
    * **Action 2:** If it knows the sync was suppressed, it *re-inserts* a new, clean sync pulse.

5.  **Self-Synchronization:**
    * To allow the receiver to "lock on" at any time (or after signal loss), the scrambler embeds the *current* `frameCounter` as digital data into the **Vertical Blanking Interval (VBI)**—a non-visible "blank" part of the video signal.
    * The descrambler reads this data, syncs its own counter, and can immediately start descrambling.

The result is a perfectly clear picture for the operator, but a chaotic, rolling, and unwatchable mess for anyone else.

---

## 💻 The Hackathon Demo: A Software Simulation

Since prototyping analog video circuits is difficult at a hackathon, we built a **real-time software simulation** to prove our scrambling and synchronization logic.

This demo uses your webcam to show the process:

* **Window 1: Original:** Your clean, unscrambled webcam feed.
* **Window 2: Scrambled (Enemy View):** The video feed after our scrambling logic is applied. You can see the inverted lines and "sync loss" (simulated as a horizontal shift).
* **Window 3: Descrambled (Operator View):** This window takes the *scrambled* feed, applies the *same secret key* and sync logic, and perfectly reconstructs the original image in real-time.

This proves our crypto and sync model is sound.

### How to Run the Demo

(This assumes a p5.js / JavaScript implementation)

1.  You must run this from a local server (due to browser security policies for webcams).
2.  The easiest way is with the **"Live Server"** extension for VS Code.
3.  Right-click `index.html` and select "Open with Live Server".
4.  Allow your browser to access the webcam.

---

## 🚀 Future Work: The Hardware Implementation

This project is directly translatable to a simple, low-cost hardware module.

* **Location:** The Scrambler box fits between the drone's Camera/OSD and its Video Transmitter (VTx).
    

* **Components:**
    * **MCU:** A simple, low-power microcontroller (like an **ATtiny85** or **Arduino Nano**) to run the PRNG and logic.
    * **Sync Separator:** An **LM1881** chip to get the V-Sync and H-Sync pulses from the video.
    * **Analog Switch:** A **CD4053** chip to route the video signal (either normal, or to the inverter).
    * **Inverter:** A standard **Op-Amp** circuit.

This solution remains fully analog, adds virtually zero latency, and uses only a few dollars' worth of components.