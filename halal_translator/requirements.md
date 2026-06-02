# RELAY — Requirements Specification (SRS)

**Status:** Draft for sign-off · **Phase:** 1 (Requirements) · **Scope:** Launch (v1.0)

---

## 1. Purpose & scope

RELAY captures the speech of a single on-site speaker, translates it to a target language in near-real-time while preserving the speaker's tone and emphasis, and broadcasts the translated audio to on-premise listeners over the local network. It records both the original and translated audio for later publication.

**In scope for launch (v1.0):**
- One language pair: **Arabic → English**
- Audio only (no video)
- On-premise, LAN-only broadcast over local WiFi
- Live English subtitles in the listener app (from the translation transcript)
- Recording of original and translated audio, exported as MP3
- Post-event generation of a structured English article + summary from the transcript
- Operator start/stop of a session

**Explicitly out of scope for v1.0 (future):**
- Additional / selectable target languages
- Video capture and broadcast
- Public-internet exposure of the live stream
- Automated upload to the public website

## 2. Stakeholders

| Role | Interest |
|---|---|
| Speaker | Speaks Arabic; expects faithful translation including tone |
| Listener | On WiFi; tunes in to English audio via a web page, no install |
| Operator | Starts/stops the session, retrieves recordings after the event |
| Publisher | Posts the recordings to the existing public website |
| Maintainer | Runs and updates the self-hosted system |

## 3. Functional requirements

| ID | Requirement | Priority |
|---|---|---|
| FR-1 | The system shall capture live audio from a single on-site speaker via a **phone** running the capture web page (picking up the speaker through the room / loudspeakers). | Must |
| FR-2 | The system shall translate spoken Arabic to English in near-real-time using OpenAI `gpt-realtime-translate`, preserving tone and emphasis. | Must |
| FR-3 | The system shall broadcast the translated English audio to listeners over the local network using LL-HLS. | Must |
| FR-4 | Listeners shall access the live stream through a web page on the local WiFi, with no software install. | Must |
| FR-5 | The system shall support the target concurrent-listener count (see NFR-1) without degradation. | Must |
| FR-6 | The system shall record the full-session original (untranslated) audio. | Must |
| FR-7 | The system shall record the full-session translated (English) audio. | Must |
| FR-8 | The system shall store both recordings locally with metadata: event name, start/stop time, duration, language pair, file paths. | Must |
| FR-9 | An operator shall be able to retrieve/export both recordings after an event as **MP3** files for manual upload to the public website. | Must |
| FR-10 | An operator shall be able to start and stop a translation session. | Must |
| FR-11 | The system shall indicate session state (idle / live / error) to the operator. | Should |
| FR-12 | The listener page shall show connection status (live / not live / reconnecting). | Should |
| FR-13 | The listener page shall display live English subtitles, driven by the translation transcript deltas. | Must |
| FR-14 | After an event, the system shall generate a structured English article with a short summary from the translated transcript, using a text AI model, for publishing alongside the audio. | Should |
| FR-15 | At session start the operator shall be able to set two independent per-event opt-out flags on the speaker's behalf: **save recording** and **generate article** (both default on). When *save recording* is off, the system shall not persist the original or translated recordings (FR-6/FR-7/FR-8); when *generate article* is off, the system shall not generate the post-event article (FR-14). The server must honor both flags. | Must |
| FR-F1 | *(Future)* Support additional target languages, selectable per listener. | Future |
| FR-F3 | *(Future)* Capture and broadcast video. | Future |
| FR-F4 | *(Future)* Automated publishing of recordings to the public website. | Future |

## 4. Non-functional requirements

| ID | Requirement |
|---|---|
| NFR-1 | **Capacity:** support up to **500** concurrent listeners on the local network (confirm in OQ-2). |
| NFR-2 | **Latency:** speaker→listener end-to-end target ≤ ~5s (HLS-bound). Translation inference itself is sub-second; the budget is dominated by HLS segmenting. |
| NFR-3 | **Audio quality:** translated audio is speech-grade (24 kHz from the API). The original is captured via phone in-room; recordings are exported as MP3 (≥192 kbps recommended). A direct line feed from the sound board is the future upgrade path for cleaner source audio (see Risks). |
| NFR-4 | **Locality:** all stored data resides on-premise at launch. The only external data flow is the audio sent to / returned from the OpenAI API during a live session. |
| NFR-5 | **Cost:** the OpenAI API is the only paid dependency. All other components are open-source and self-hosted. |
| NFR-6 | **Portability / migration-readiness:** the system is containerized and uses an S3-compatible storage API (MinIO), so it can move to a public/cloud deployment without a rewrite. |
| NFR-7 | **Security-readiness:** the OpenAI API key is held server-side only and never exposed to clients. The design must allow adding TLS and authentication before any public exposure. |
| NFR-8 | **Privacy:** speaker audio is recorded and later published; a consent/notice process is required (see OQ-7). |
| NFR-9 | **Reliability:** the system should survive a single listener disconnect/reconnect without affecting others; a warm-spare server is recommended for live events. |
| NFR-10 | **Usability:** a listener should be able to join with a single URL/QR code and start hearing audio within a few seconds. |

## 5. Constraints & assumptions

**Constraints**
- Self-hosted on organization-owned Linux PCs.
- Only the OpenAI API may incur cost.
- Launch is LAN-only but must be architected toward later internet exposure.

**Assumptions**
- Listeners do not understand the source language, so HLS latency is acceptable.
- One speaker and one event at a time at launch.
- Adequate, stable WiFi/network exists at the venue; the server is wired to the network via gigabit ethernet.

**Risks**
- **Phone capture quality:** a phone picks up room acoustics, loudspeaker coloration, and audience noise, which can reduce translation accuracy and archive quality. Mitigation / upgrade path: tap a clean line-out / aux from the sound board into a small capture device later. (No feedback-loop risk — the phone only captures; it never feeds back into the system.)
- **Subtitle/audio drift:** transcript text and translated audio may not be perfectly aligned; acceptable for v1, revisit if distracting.

## 6. Acceptance criteria (v1.0 / MVP gate)

1. An Arabic speaker talks near the capture phone; translated English audio is audible on a listener's phone browser over the venue WiFi within ~5 seconds.
2. Live English subtitles appear on the listener page, roughly tracking the audio.
3. Tone is preserved: an emphatic or calm delivery is reflected in the English audio (validated by a bilingual reviewer).
4. At session end, both the original and translated recordings exist locally as MP3 with correct metadata and are retrievable by the operator.
5. A structured English article + summary is generated from the transcript after the event.
6. The system sustains the target listener count (NFR-1) in a load test without audio dropouts.

## 7. Open questions — *what I need from you to finalize requirements*

| ID | Question | Why it matters |
|---|---|---|
| OQ-1 | ✅ **Resolved:** Capture via **phone** running the capture page (picks up the speaker through the room / loudspeakers). Sound-board line feed is a later quality upgrade. | — |
| OQ-2 | Confirm the concurrent-listener number to design and load-test against (500 ceiling?). | Sizing and test plan |
| OQ-3 | ✅ **Resolved:** **Yes** — live English subtitles at launch (FR-13), plus a post-event AI-generated article + summary from the transcript (FR-14). | — |
| OQ-4 | ✅ **Resolved:** Listener access is **open to anyone on the WiFi** — no event code, no login — keeping the simple tune-in model. The nginx auth hook stays reserved for later public exposure (M5). | — |
| OQ-5 | ✅ **Resolved:** Export both recordings as **MP3**, saved locally; operator manually uploads to the (likely WordPress) public site. Automated publishing deferred (FR-F4). | — |
| OQ-6 | Typical event duration? | File sizes, storage planning, session limits |
| OQ-7 | ✅ **Resolved:** The speaker is **informed verbally** that they are being recorded and published. The speaker may opt out of (a) saving the recording and (b) generating the post-event article; these are two independent per-event flags the operator sets at session start and the server honors (FR-15). | — |
| OQ-8 | Is there a human operator running start/stop, or should the system auto-detect when the speaker begins? | Operator UX |
| OQ-9 | Should listeners also be able to hear the **original Arabic**, or English only? | Stream count, listener UI |

> None of these block starting the design doc and scaffold — I'll proceed with the assumptions above and mark anything dependent on these answers as TBD.