/** @odoo-module **/

/**
 * WhatsApp calling service: the WebRTC pipeline, and the state the phone
 * card (phone_card.js / phone_card.xml) draws from.
 *
 * Registered as a service so bus_service can be resolved via the standard
 * dependency injection, and so a call can ring in from anywhere in the app.
 *
 * Flow:
 *   1. Meta webhook stores SDP offer on whatsapp.call.log.
 *   2. Server pushes { call_log_id, sdp_offer, partner_name, ... } over
 *      the whatsapp_incoming_call bus channel.
 *   3. The phone card shows the Incoming screen with Accept/Decline.
 *   4. On Accept: getUserMedia → RTCPeerConnection → setRemoteDescription
 *      (offer) → createAnswer → setLocalDescription → wait for ICE →
 *      POST answer to /whatsapp/call/answer/<id>.
 *   5. Server forwards answer to Meta.
 *   6. Meta establishes DTLS-SRTP; remote audio arrives via ontrack and
 *      plays through a hidden <audio autoplay>.
 *
 * The view never touches the pipeline's objects: the functions the pipeline
 * calls to show something (showPopup, showHud, hideHud, renderScriptPanel…)
 * only copy what the card needs into `state`.
 */

import { reactive } from "@odoo/owl";
import { registry } from "@web/core/registry";

const AUDIO_ID = "comm_whatsapp_calling_remote_audio";
const LOG_TAG = "[wa-call]";

const ICE_SERVERS = [
    { urls: "stun:stun.l.google.com:19302" },
    { urls: "stun:stun1.l.google.com:19302" },
];

const PRESENCE_LABELS = { available: "Available", away: "Away", dnd: "Do not disturb" };

function log(...args) {
    try { console.log(LOG_TAG, ...args); } catch (e) {}
}
function warn(...args) {
    try { console.warn(LOG_TAG, ...args); } catch (e) {}
}

function callRpc(url, params = {}) {
    const body = JSON.stringify({
        jsonrpc: "2.0",
        method: "call",
        params,
        id: Math.floor(Math.random() * 1e9),
    });
    return fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body,
    })
        .then((r) => r.json())
        .then((data) => {
            if (data.error) {
                throw new Error(
                    (data.error.data && data.error.data.message) ||
                    data.error.message || "RPC error"
                );
            }
            return data.result;
        });
}

function waitForIceGathering(pc, timeoutMs) {
    if (pc.iceGatheringState === "complete") return Promise.resolve();
    return new Promise((resolve) => {
        let done = false;
        function check() {
            if (done) return;
            if (pc.iceGatheringState === "complete") {
                done = true;
                pc.removeEventListener("icegatheringstatechange", check);
                resolve();
            }
        }
        pc.addEventListener("icegatheringstatechange", check);
        setTimeout(() => {
            if (!done) {
                done = true;
                pc.removeEventListener("icegatheringstatechange", check);
                resolve();
            }
        }, timeoutMs || 4000);
    });
}

function ensureRemoteAudioEl() {
    let el = document.getElementById(AUDIO_ID);
    if (el) return el;
    el = document.createElement("audio");
    el.id = AUDIO_ID;
    el.autoplay = true;
    el.setAttribute("playsinline", "");
    el.style.position = "fixed";
    el.style.left = "-9999px";
    document.body.appendChild(el);
    return el;
}

// ── Service ──────────────────────────────────────────────────────────

const waCallService = {
    dependencies: ["bus_service", "notification", "orm", "action"],
    start(env, { bus_service, notification, orm, action }) {
        log("service starting");

        // One active call at a time. Key = call_log_id.
        let activeCall = null;
        // { sessionId, chatbotName, bubbles, terminated } while a suggested
        // voice script is being followed for the current accepted call.
        let scriptSession = null;

        // ── What the phone card shows ────────────────────────────────
        // Each key is one screen (or part of one) and holds only what that
        // screen prints. The card picks the screen in this order:
        // permission, picker, incoming, call, transferRequest, connecting,
        // wrapup, then the three tabs.
        const state = reactive({
            open: false,            // the card is on screen
            tab: "recent",          // recent | keypad | activities
            presence: "available",  // available | away | dnd
            missed: 0,              // count on the Recent tab and the systray icon
            incoming: null,         // { callLogId, name, number, partnerId, scriptName }
            transferRequest: null,  // { by, name, number }
            connecting: null,       // { label, name, number } while a call is being set up
            call: null,             // { callLogId, name, number, partnerId, startTime, muted, recording }
            script: null,           // { name, bubbles, terminated, loading }
            scriptOpen: false,      // the script follower is in front of the call screen
            picker: null,           // { kind: script|campaign, title, items, owner }
            transfer: null,         // { callLogId, teams, teamId }
            permission: null,       // { name, number, chip, message, hint, canTry, canRequest }
            wrapup: null,           // { callLogId, name, dispositions, dispositionId, note }
            keypad: {
                number: "",
                accounts: [],       // [{ id, label }]
                accountId: null,
                chatbotId: null,
                chatbotName: "",
                contact: null,      // { name, partnerId } matched on the number
                permission: null,   // granted | pending | declined | expired
            },
        });
        // The bus payloads and callbacks behind those screens stay out of
        // `state`, so the pipeline is handed back the very objects it gave.
        let incomingPayload = null;
        let transferPayload = null;
        let pickerSelect = null;
        let permissionAnswer = null;   // resolves confirmDialWithoutPermission
        let permissionRequest = null;  // { toNumber, accountId, partnerName, partnerId }
        let pendingDial = null;        // arguments of the outbound call being set up
        let wrapupSeq = 0;
        let connectingSeq = 0;
        let openScriptWhenReady = false;

        function openCard(tab) {
            if (tab) state.tab = tab;
            state.open = true;
            refreshMissed();
            if (state.tab === "keypad") loadAccounts();
        }

        function toggleCard() {
            if (state.open) {
                state.open = false;
            } else {
                openCard();
            }
        }

        function minimise() {
            state.open = false;
        }

        // ── Presence (Available / Away / Do not disturb) ─────────────
        // Away and DND users are skipped when the inbound webhook
        // broadcasts a ringing event, so their browsers stay quiet.
        async function loadPresence() {
            try {
                const data = await callRpc("/whatsapp/call/presence/get", {});
                if (data && data.presence) state.presence = data.presence;
            } catch (e) {
                warn("presence fetch failed:", e);
            }
        }

        async function setPresence(next) {
            if (!PRESENCE_LABELS[next] || next === state.presence) return;
            const previous = state.presence;
            state.presence = next;
            try {
                const result = await callRpc("/whatsapp/call/presence/set", { presence: next });
                if (!result?.success) {
                    throw new Error(result?.error || "unknown");
                }
                notify(`Presence: ${PRESENCE_LABELS[next]}`, "info");
            } catch (e) {
                // Roll back so the dot shows what the server actually has.
                state.presence = previous;
                notify("Could not update presence: " + (e?.message || e), "danger");
            }
        }

        // Missed calls since midnight (this browser's day), so the badge
        // is today's backlog and clears itself overnight.
        async function refreshMissed() {
            try {
                const midnight = new Date();
                midnight.setHours(0, 0, 0, 0);
                const since = midnight.toISOString().slice(0, 19).replace("T", " ");
                state.missed = await orm.searchCount("whatsapp.call.log", [
                    ["is_missed", "=", true],
                    ["create_date", ">=", since],
                ]);
            } catch (e) {
                state.missed = 0;
            }
        }

        // ── Pickers (script, campaign) ───────────────────────────────
        // A picker sits in front of the screen it was opened from, and goes
        // away with it: `owner` is incoming | call | keypad.
        function pickerOwner() {
            return state.incoming ? "incoming" : state.call ? "call" : "keypad";
        }

        function ownerGone(owner) {
            return (owner === "incoming" && !state.incoming) || (owner === "call" && !state.call);
        }

        function openPicker(kind, title, items, onSelect, owner) {
            pickerSelect = onSelect;
            state.picker = { kind, title, items, owner };
            state.open = true;
        }

        function closePicker() {
            pickerSelect = null;
            state.picker = null;
        }

        function pick(id) {
            const item = state.picker && state.picker.items.find((i) => i.id === id);
            const select = pickerSelect;
            closePicker();
            if (item && select && !item.already) select(item.id, item.name);
        }

        function notify(message, type) {
            try {
                notification.add(message, { type: type || "info" });
            } catch (e) {
                log(message);
            }
        }

        // ── Ringing (audio + tab-title flash + desktop notification) ──
        // So the agent notices an incoming call even from a different
        // browser tab or a different window entirely, not just when
        // this Odoo tab happens to already be focused.
        let ringAudioCtx = null;
        let ringIntervalId = null;
        let titleFlashIntervalId = null;
        let originalTitle = null;
        let ringNotification = null;

        function playRingTone() {
            try {
                if (!ringAudioCtx) return;
                const now = ringAudioCtx.currentTime;
                // Two-burst "brring" pattern, roughly like a classic phone ring.
                [0, 0.35].forEach((offset) => {
                    const osc = ringAudioCtx.createOscillator();
                    const gain = ringAudioCtx.createGain();
                    osc.type = "sine";
                    osc.frequency.value = 950;
                    gain.gain.setValueAtTime(0, now + offset);
                    gain.gain.linearRampToValueAtTime(0.25, now + offset + 0.02);
                    gain.gain.linearRampToValueAtTime(0, now + offset + 0.3);
                    osc.connect(gain);
                    gain.connect(ringAudioCtx.destination);
                    osc.start(now + offset);
                    osc.stop(now + offset + 0.32);
                });
            } catch (e) {
                warn("playRingTone failed:", e);
            }
        }

        function startRinging(payload) {
            try {
                if (!ringAudioCtx) {
                    const AudioCtx = window.AudioContext || window.webkitAudioContext;
                    ringAudioCtx = new AudioCtx();
                }
                // Background tabs can leave a freshly-created context
                // suspended until a gesture resumes it — worth trying
                // every time rather than assuming it's already running.
                if (ringAudioCtx.state === "suspended") {
                    ringAudioCtx.resume().catch(() => {});
                }
                if (!ringIntervalId) {
                    playRingTone();
                    ringIntervalId = setInterval(playRingTone, 2000);
                }
            } catch (e) {
                warn("startRinging audio failed:", e);
            }

            if (!titleFlashIntervalId) {
                originalTitle = document.title;
                const ringTitle = `📞 ${payload?.partner_name || "Incoming call"}…`;
                let flashOn = false;
                titleFlashIntervalId = setInterval(() => {
                    document.title = flashOn ? originalTitle : ringTitle;
                    flashOn = !flashOn;
                }, 1000);
            }

            // Desktop notification only when this tab isn't the one the
            // agent is looking at — the on-screen popup already covers
            // the focused-tab case.
            if (document.hidden && typeof Notification !== "undefined") {
                const show = () => {
                    try {
                        ringNotification = new Notification("Incoming WhatsApp call", {
                            body: payload?.partner_name || payload?.from_number || "Unknown caller",
                            tag: "wa-incoming-call",
                        });
                        ringNotification.onclick = () => {
                            window.focus();
                            if (ringNotification) ringNotification.close();
                        };
                    } catch (e) { /* notifications not available — ignore */ }
                };
                if (Notification.permission === "granted") {
                    show();
                } else if (Notification.permission === "default") {
                    Notification.requestPermission().then((perm) => {
                        if (perm === "granted") show();
                    }).catch(() => {});
                }
            }
        }

        function stopRinging() {
            if (ringIntervalId) {
                clearInterval(ringIntervalId);
                ringIntervalId = null;
            }
            if (titleFlashIntervalId) {
                clearInterval(titleFlashIntervalId);
                titleFlashIntervalId = null;
                if (originalTitle !== null) {
                    document.title = originalTitle;
                    originalTitle = null;
                }
            }
            if (ringNotification) {
                try { ringNotification.close(); } catch (e) {}
                ringNotification = null;
            }
        }

        // ── Incoming screen ──────────────────────────────────────────
        function hidePopup() {
            stopRinging();
            incomingPayload = null;
            state.incoming = null;
            if (state.picker && state.picker.owner === "incoming") closePicker();
        }

        function showPopup(payload) {
            hidePopup();
            incomingPayload = payload;
            state.incoming = {
                callLogId: payload.call_log_id,
                name: payload.partner_name || "Unknown",
                number: payload.from_number || "",
                partnerId: payload.partner_id || null,
                scriptName: payload.suggested_chatbot_id ? (payload.suggested_chatbot_name || "") : "",
            };
            state.open = true;
            startRinging(payload);
        }

        // Between Accept (or Call) and the call being up there is no call to
        // show or end yet, only this screen.
        function showConnecting(label, name, number) {
            state.connecting = { label, name: name || number || "", number: number || "" };
            state.open = true;
            return ++connectingSeq;
        }

        function hideConnecting(seq) {
            if (seq === connectingSeq) state.connecting = null;
        }

        async function acceptIncoming() {
            const payload = incomingPayload;
            if (!payload) return;
            const seq = activeCall ? 0 : showConnecting("Connecting", payload.partner_name, payload.from_number);
            try {
                await acceptCall(payload);
            } finally {
                hideConnecting(seq);
            }
        }

        function declineIncoming() {
            if (incomingPayload) declineCall(incomingPayload.call_log_id);
        }

        function toggleMute() {
            if (!activeCall || !activeCall.localStream) return;
            activeCall.muted = !activeCall.muted;
            activeCall.localStream.getAudioTracks().forEach((t) => { t.enabled = !activeCall.muted; });
        }

        // `activeCall` is a one-at-a-time module singleton, cleared only
        // by teardownCall() — which the existing onconnectionstatechange
        // handlers only trigger on "failed"/"closed". "disconnected" is
        // a valid, transient ICE state (common after a brief network
        // blip) that can persist indefinitely without ever escalating to
        // "failed", especially on flaky mobile networks — left
        // unwatched, that leaves activeCall stuck, silently blocking
        // every future dial/accept on this tab until a manual refresh.
        // Give it a grace period to self-recover (normal per WebRTC
        // guidance), then force a teardown if it never does. Uses
        // addEventListener (not the onconnectionstatechange property) so
        // this coexists with each call site's own handler instead of
        // replacing it.
        function watchForStuckConnection(pc) {
            const GRACE_MS = 12000;
            let timer = null;
            pc.addEventListener("connectionstatechange", () => {
                if (pc.connectionState === "disconnected") {
                    if (timer) return;
                    timer = setTimeout(() => {
                        timer = null;
                        if (pc.connectionState === "disconnected" && activeCall?.pc === pc) {
                            warn("connection stuck in 'disconnected' for", GRACE_MS, "ms — forcing teardown");
                            teardownCall(false);
                        }
                    }, GRACE_MS);
                } else if (timer) {
                    clearTimeout(timer);
                    timer = null;
                }
            });
        }

        // ── Recording (client-side — WhatsApp calls are end-to-end
        // encrypted between the browser and Meta, so there's nothing
        // server-side to record; the browser mixes both live audio
        // tracks itself and uploads the result once the call ends). ──
        function startRecording(call) {
            if (!call || !call.localStream || !call.remoteStream) {
                notify("Recording needs both sides of the call connected first.", "warning");
                return false;
            }
            try {
                const AudioCtx = window.AudioContext || window.webkitAudioContext;
                const audioCtx = new AudioCtx();
                // Created outside a tap, so phones start it paused, and a
                // paused context records nothing.
                if (audioCtx.state !== "running") audioCtx.resume().catch(() => {});
                const dest = audioCtx.createMediaStreamDestination();
                const localNode = audioCtx.createMediaStreamSource(call.localStream);
                const remoteNode = audioCtx.createMediaStreamSource(call.remoteStream);
                localNode.connect(dest);
                remoteNode.connect(dest);

                const chunks = [];
                const recorder = new MediaRecorder(dest.stream);
                recorder.ondataavailable = (ev) => {
                    if (ev.data && ev.data.size) chunks.push(ev.data);
                };
                // A chunk each second, so a recording that captures nothing
                // shows up while the call is still on.
                recorder.start(1000);

                // Per-speaker mono recorders (agent = local, caller = remote) for
                // a speaker-labelled transcript. Best-effort — never break the mix.
                try {
                    const destAgent = audioCtx.createMediaStreamDestination();
                    localNode.connect(destAgent);
                    const chunksAgent = [];
                    const recorderAgent = new MediaRecorder(destAgent.stream);
                    recorderAgent.ondataavailable = (ev) => {
                        if (ev.data && ev.data.size) chunksAgent.push(ev.data);
                    };
                    recorderAgent.start(1000);

                    const destCaller = audioCtx.createMediaStreamDestination();
                    remoteNode.connect(destCaller);
                    const chunksCaller = [];
                    const recorderCaller = new MediaRecorder(destCaller.stream);
                    recorderCaller.ondataavailable = (ev) => {
                        if (ev.data && ev.data.size) chunksCaller.push(ev.data);
                    };
                    recorderCaller.start(1000);

                    call.recorderAgent = recorderAgent;
                    call.chunksAgent = chunksAgent;
                    call.recorderCaller = recorderCaller;
                    call.chunksCaller = chunksCaller;
                } catch (chanErr) {
                    warn("per-channel recorders failed:", chanErr);
                }

                call.audioContext = audioCtx;
                call.mediaRecorder = recorder;
                call.recordedChunks = chunks;
                call.recording = true;
                call.recordingStartedAt = Date.now();
                notify("Recording this call.", "info");
                checkRecordingCaptures(call, recorder, chunks, audioCtx);
                return true;
            } catch (err) {
                warn("startRecording failed:", err);
                notify("Could not start recording: " + (err?.message || err), "danger");
                return false;
            }
        }

        // Phones can pause the audio engine mid-call, leaving a recording
        // that captures nothing. Try to wake it, and tell the agent if that
        // fails rather than letting them find out after the call.
        function checkRecordingCaptures(call, recorder, chunks, audioCtx) {
            setTimeout(async () => {
                if (call.mediaRecorder !== recorder || chunks.length) return;
                try { await audioCtx.resume(); } catch (e) {}
                setTimeout(() => {
                    if (call.mediaRecorder !== recorder || chunks.length) return;
                    notification.add(
                        "This call is NOT being recorded. Take notes, or try the record button again.",
                        { type: "danger", sticky: true, title: "Recording failed" });
                    callRpc("/whatsapp/call/recording_problem", {
                        kind: "whatsapp", call_id: call.id, detail: `audio ${audioCtx.state}`,
                    }).catch(() => {});
                    // Let the agent retry with the record button.
                    stopRecordingAndUpload(call);
                    if (activeCall === call && lastHudPayload) showHud(lastHudPayload);
                }, 4000);
            }, 6000);
        }

        // Start recording once both sides are connected, when the number is
        // set to record every call.
        function maybeAutoRecord(call) {
            if (call && call.autoRecord && call.startTime && !call.mediaRecorder
                    && call.localStream && call.remoteStream && activeCall === call) {
                startRecording(call);
                if (lastHudPayload) showHud(lastHudPayload);
            }
        }

        async function stopRecordingAndUpload(call) {
            if (!call || !call.mediaRecorder) return;
            const recorder = call.mediaRecorder;
            const chunks = call.recordedChunks || [];
            const audioCtx = call.audioContext;
            const startedAt = call.recordingStartedAt;
            const recAgent = call.recorderAgent;
            const chunksAgent = call.chunksAgent || [];
            const recCaller = call.recorderCaller;
            const chunksCaller = call.chunksCaller || [];
            call.mediaRecorder = null;
            call.recorderAgent = null;
            call.recorderCaller = null;
            call.recording = false;

            const stopOne = (r) => new Promise((resolve) => {
                if (!r) { resolve(); return; }
                r.addEventListener("stop", resolve, { once: true });
                try { r.stop(); } catch (e) { resolve(); }
            });
            await Promise.all([stopOne(recorder), stopOne(recAgent), stopOne(recCaller)]);
            try { audioCtx && audioCtx.close(); } catch (e) {}

            if (!chunks.length || !call.id) return;
            const durationSeconds = startedAt ? Math.round((Date.now() - startedAt) / 1000) : 0;
            const blob = new Blob(chunks, { type: "audio/webm" });
            const form = new FormData();
            form.append("recording", blob, "call_recording.webm");
            form.append("duration", String(durationSeconds));
            form.append("csrf_token", odoo.csrf_token);
            // Per-speaker mono streams for a speaker-labelled transcript.
            if (chunksAgent.length) {
                form.append("recording_agent", new Blob(chunksAgent, { type: "audio/webm" }), "agent.webm");
            }
            if (chunksCaller.length) {
                form.append("recording_caller", new Blob(chunksCaller, { type: "audio/webm" }), "caller.webm");
            }
            try {
                await fetch(`/whatsapp/call/upload_recording/${call.id}`, {
                    method: "POST", credentials: "same-origin", body: form,
                });
                log("recording uploaded for call", call.id);
            } catch (err) {
                warn("recording upload failed:", err);
                notify("Could not save the recording.", "warning");
            }
        }

        async function toggleRecording() {
            if (!activeCall) return;
            if (activeCall.recording) {
                await stopRecordingAndUpload(activeCall);
            } else {
                startRecording(activeCall);
            }
        }

        // ── In-call screen ───────────────────────────────────────────
        // The pipeline calls showHud whenever something the screen prints
        // has changed (answered, muted, recording started or failed).
        let lastHudPayload = null;
        function showHud(payload) {
            lastHudPayload = payload;
            // A new call brings the card up; a redraw leaves a minimised card alone.
            if (!state.call) state.open = true;
            state.call = {
                callLogId: payload.call_log_id,
                name: payload.partner_name || "In call",
                number: payload.from_number || "",
                partnerId: payload.partner_id || null,
                startTime: (activeCall && activeCall.startTime) || null,
                muted: !!(activeCall && activeCall.muted),
                recording: !!(activeCall && activeCall.recording),
            };
        }

        function hideHud() {
            state.call = null;
            state.transfer = null;
            state.scriptOpen = false;
            openScriptWhenReady = false;
            if (state.picker && state.picker.owner === "call") closePicker();
        }

        function hangupFromCard() {
            if (state.call) hangupCall(state.call.callLogId);
        }

        function muteFromCard() {
            toggleMute();
            if (activeCall && lastHudPayload) showHud(lastHudPayload);
        }

        async function recordFromCard() {
            await toggleRecording();
            if (activeCall && lastHudPayload) showHud(lastHudPayload);
        }

        // ── Transfer request (target agent side) ─────────────────────
        function showTransferRequestPopup(payload) {
            if (activeCall) {
                // Don't interrupt an active call.
                notify(`Transfer request from ${payload.transferred_from_name} ignored (in call)`,
                       "info");
                return;
            }
            transferPayload = payload;
            state.transferRequest = {
                by: payload.transferred_from_name || "Someone",
                name: payload.partner_name || "Caller",
                number: payload.from_number || "",
            };
            state.open = true;

            // If the transfer request stales (someone else accepted, the
            // source call ended, etc.), drop it after 60s.
            setTimeout(() => {
                if (transferPayload === payload) declineTransferRequest();
            }, 60000);
        }

        function declineTransferRequest() {
            transferPayload = null;
            state.transferRequest = null;
        }

        async function acceptTransferRequest() {
            const payload = transferPayload;
            if (!payload) return;
            declineTransferRequest();
            // Dial the customer back via the standard outbound path: a cold
            // transfer carries no continuity from Meta, so this is a fresh
            // outbound call.
            await placeCall({
                toNumber:    payload.from_number,
                partnerId:   payload.partner_id || null,
                partnerName: payload.partner_name || payload.from_number,
                accountId:   payload.account_id || null,
            });
        }

        // ── Transfer to a team ───────────────────────────────────────
        async function openTransferPicker(callLogId) {
            let teams = [];
            try {
                const result = await callRpc("/whatsapp/call/teams", {});
                teams = result?.teams || [];
            } catch (err) {
                notify("Could not load teams: " + (err?.message || err),
                       "danger");
                return;
            }
            if (!teams.length) {
                notify("No call teams configured.", "warning");
                return;
            }
            if (!state.call || state.call.callLogId !== callLogId) return; // call ended while loading
            state.transfer = {
                callLogId,
                teamId: null,
                teams: teams.map((t) => ({
                    id: t.id, name: t.name, available: t.available_count, members: t.member_count,
                })),
            };
        }

        function closeTransfer() {
            state.transfer = null;
        }

        async function transferToTeam() {
            const transfer = state.transfer;
            if (!transfer || !transfer.teamId) return;
            const callLogId = transfer.callLogId;
            const teamId = transfer.teamId;
            state.transfer = null;
            try {
                const result = await callRpc(
                    `/whatsapp/call/transfer/${callLogId}`,
                    { team_id: teamId },
                );
                if (!result?.success) {
                    throw new Error(result?.error || "Transfer failed");
                }
                notify(`Transferring — ${result.targets_notified} agent(s) notified`,
                       "success");
                // hangupCall, not a bare teardownCall — this source call was
                // already answered, so closing the local RTCPeerConnection
                // alone leaves it "ongoing" from Meta's side (Meta was never
                // told to terminate it). That's exactly what then blocks the
                // receiving agent's "Call back" with "A call with this number
                // is already ongoing" — Meta sees an existing open session
                // with that customer and refuses the new one.
                hangupCall(callLogId);
            } catch (err) {
                notify("Transfer failed: " + (err?.message || err),
                       "danger");
            }
        }

        // ── Call script picker (before accepting, on the keypad, mid-call) ──
        // onSelect(chatbotId, chatbotName) fires when a script is chosen.
        async function showChatbotPicker(title, onSelect) {
            const owner = pickerOwner();
            let chatbots = [];
            try {
                chatbots = await orm.searchRead(
                    "whatsapp.chatbot",
                    [["channel", "=", "voice"], ["status", "=", "published"]],
                    ["name"],
                );
            } catch (err) {
                notify("Could not load voice scripts: " + (err?.message || err), "danger");
                return;
            }
            if (!chatbots.length) {
                notify("No published voice scripts available.", "warning");
                return;
            }
            if (ownerGone(owner)) return;
            openPicker(
                "script", title,
                chatbots.map((cb) => ({ id: cb.id, name: cb.name })),
                (chatbotId, chatbotName) => onSelect(chatbotId, chatbotName || "Voice script"),
                owner,
            );
        }

        async function openScriptPicker() {
            if (!activeCall) return;
            await showChatbotPicker(
                scriptSession ? "Change call script" : "Start a call script",
                (chatbotId, chatbotName) => {
                    // The agent asked for it, so the follower comes to the front.
                    openScriptWhenReady = true;
                    switchVoiceScript(chatbotId, chatbotName);
                }
            );
        }

        // Pre-accept: let the agent override which script will run once
        // they answer, before the call (and any voice session) exists yet.
        async function pickScriptForPopup(payload) {
            await showChatbotPicker("Choose a call script", (chatbotId, chatbotName) => {
                payload.suggested_chatbot_id = chatbotId;
                payload.suggested_chatbot_name = chatbotName;
                showPopup(payload);
            });
        }

        function scriptForIncoming() {
            if (incomingPayload) pickScriptForPopup(incomingPayload);
        }

        // Script button on the call screen: the follower when a script is
        // running, else the picker.
        function scriptFromCard() {
            if (state.script) {
                state.scriptOpen = true;
            } else {
                openScriptPicker();
            }
        }

        function showScript(open) {
            state.scriptOpen = !!open && !!state.script;
        }

        // ── Add caller to a campaign ─────────────────────────────────
        async function showCampaignPicker(partnerId) {
            if (!partnerId) {
                notify("No linked contact for this call.", "warning");
                return;
            }
            const owner = pickerOwner();
            let contacts = [];
            try {
                contacts = await orm.searchRead(
                    "contact.centre.contact", [["partner_id", "=", partnerId]],
                    ["id", "campaign_ids"], { limit: 1 },
                );
            } catch (err) {
                notify("Could not load the contact: " + (err?.message || err), "danger");
                return;
            }
            if (!contacts.length) {
                notify("This caller doesn't have a contact-centre record yet.", "warning");
                return;
            }
            const contact = contacts[0];
            let campaigns = [];
            try {
                campaigns = await orm.searchRead("contact.centre.campaign", [], ["name"]);
            } catch (err) {
                notify("Could not load campaigns: " + (err?.message || err), "danger");
                return;
            }
            if (!campaigns.length) {
                notify("No campaigns configured.", "warning");
                return;
            }
            if (ownerGone(owner)) return;
            const already = new Set(contact.campaign_ids || []);
            openPicker(
                "campaign", "Add to campaign",
                campaigns.map((camp) => ({ id: camp.id, name: camp.name, already: already.has(camp.id) })),
                async (campaignId) => {
                    try {
                        await orm.write("contact.centre.contact", [contact.id], {
                            campaign_ids: [[4, campaignId]],
                        });
                        notify("Added to campaign.", "success");
                    } catch (err) {
                        notify("Could not add to campaign: " + (err?.message || err), "danger");
                    }
                },
                owner,
            );
        }

        // ── Phone-number lookups (dial pad "Add to campaign" / "History") ──
        function normalizeDigits(s) {
            return String(s || "").replace(/[^0-9]/g, "");
        }

        async function resolveContactForNumber(rawNumber) {
            const digits = normalizeDigits(rawNumber);
            if (!digits) return null;
            // Match on the last 9 digits so formatting differences
            // (missing "+", country code, spaces) don't break the lookup.
            const suffix = digits.slice(-9);
            try {
                const contacts = await orm.searchRead(
                    "contact.centre.contact",
                    [["phone_number", "ilike", suffix]],
                    ["id", "name", "partner_id"],
                    { limit: 1 },
                );
                return contacts[0] || null;
            } catch (e) {
                return null;
            }
        }

        // ── Recent tab: call history, plus matching contacts on a search ──
        async function recentCalls(term) {
            const domain = [];
            const t = (term || "").trim();
            if (t) {
                const digits = normalizeDigits(t);
                const numberTerm = digits.length >= 3 ? digits.slice(-9) : t;
                domain.push("|", "|",
                    ["from_number", "ilike", numberTerm],
                    ["to_number", "ilike", numberTerm],
                    ["partner_id.name", "ilike", t]);
            }
            const logs = await orm.searchRead(
                "whatsapp.call.log", domain,
                ["call_direction", "call_status", "call_timestamp", "duration",
                 "is_missed", "from_number", "to_number", "partner_id", "contact_display",
                 "has_recording", "recording_ids"],
                { limit: 50, order: "call_timestamp desc" },
            );
            return logs.map((l) => {
                const number = (l.call_direction === "incoming" ? l.from_number : l.to_number) || "";
                return {
                    id: l.id,
                    at: l.call_timestamp || false,
                    name: l.contact_display || number || "Unknown",
                    number,
                    partnerId: l.partner_id ? l.partner_id[0] : null,
                    direction: l.call_direction,
                    status: l.call_status,
                    missed: !!l.is_missed,
                    duration: l.duration || 0,
                    recordingId: (l.has_recording && l.recording_ids && l.recording_ids[0]) || null,
                };
            });
        }

        // Contact-centre contacts matching a search. Empty when that app
        // isn't installed.
        async function matchingContacts(term) {
            const t = (term || "").trim();
            if (!t) return [];
            try {
                const contacts = await orm.searchRead(
                    "contact.centre.contact",
                    ["|", ["name", "ilike", t], ["phone_number", "ilike", t]],
                    ["name", "phone_number", "partner_id"],
                    { limit: 20, order: "name" },
                );
                return contacts.filter((ct) => ct.phone_number).map((ct) => ({
                    id: ct.id,
                    name: ct.name || ct.phone_number,
                    number: ct.phone_number,
                    partnerId: ct.partner_id ? ct.partner_id[0] : null,
                }));
            } catch (e) {
                return [];
            }
        }

        // The signed-in user's open phone-call activities, most overdue first.
        function activities() {
            return orm.call("whatsapp.call.log", "phone_card_activities", []);
        }

        async function switchVoiceScript(chatbotId, chatbotName) {
            if (!activeCall) return;
            if (scriptSession?.sessionId) {
                try {
                    await callRpc("/voice/end", { session_id: scriptSession.sessionId });
                } catch (e) {
                    // Best-effort — proceeding to start the new one regardless.
                }
            }
            scriptSession = null;
            hideScriptPanel();
            await startVoiceScript({
                suggested_chatbot_id: chatbotId,
                suggested_chatbot_name: chatbotName,
                partner_name: activeCall.partnerName,
                from_number: activeCall.fromNumber,
            });
        }

        // ── Jump to the caller's conversation in the Inbox ──────────
        async function openContactInboxFor(partnerId) {
            if (!partnerId) {
                notify("No linked contact for this call.", "warning");
                return;
            }
            let contacts = [];
            try {
                contacts = await orm.searchRead(
                    "contact.centre.contact", [["partner_id", "=", partnerId]], ["id"], { limit: 1 },
                );
            } catch (err) {
                notify("Could not open the Inbox: " + (err?.message || err), "danger");
                return;
            }
            if (!contacts.length) {
                notify("This caller doesn't have a contact-centre record yet.", "warning");
                return;
            }
            action.doAction({
                type: "ir.actions.client",
                tag: "contact_centre_inbox",
                target: "new",
                context: { dialog_size: "extra-large" },
                params: { contact_id: contacts[0].id },
            });
        }

        // ── Call script follower ─────────────────────────────────────
        // Same /voice/* endpoints as contact_centre_inbox's VoiceScriptPanel;
        // comm_whatsapp_calling doesn't depend on that app, so the follower
        // is a sheet of the phone card. A script that starts by itself
        // (suggested for the call) stays behind the call screen until the
        // agent opens it.
        function hideScriptPanel() {
            state.script = null;
            state.scriptOpen = false;
        }

        function renderScriptPanel() {
            if (!scriptSession) return;
            state.script = {
                name: scriptSession.chatbotName,
                bubbles: scriptSession.bubbles.slice(),
                terminated: !!scriptSession.terminated,
                loading: !!scriptSession.loading,
            };
            if (openScriptWhenReady) {
                openScriptWhenReady = false;
                state.scriptOpen = true;
            }
        }

        async function startVoiceScript(payload) {
            scriptSession = {
                sessionId: null, chatbotName: payload.suggested_chatbot_name || "Voice script",
                bubbles: [], terminated: false, loading: true,
            };
            renderScriptPanel();
            try {
                const result = await callRpc("/voice/start", {
                    chatbot_id: payload.suggested_chatbot_id,
                    contact_details: { name: payload.partner_name, mobile: payload.from_number },
                });
                if (!scriptSession) return; // call ended while starting
                if (result?.error || !result?.session_id) {
                    throw new Error(result?.error || "No session id returned");
                }
                scriptSession.sessionId = result.session_id;
                await sendScriptTurn(null);
            } catch (err) {
                warn("voice script start failed:", err);
                notify("Could not start the suggested script: " + (err?.message || err), "warning");
                scriptSession = null;
                hideScriptPanel();
            }
        }

        async function sendScriptTurn(userInput) {
            if (!scriptSession || !scriptSession.sessionId) return;
            scriptSession.loading = true;
            renderScriptPanel();
            try {
                const data = await callRpc("/voice/turn", {
                    session_id: scriptSession.sessionId,
                    user_input: userInput,
                    initial_variables: {},
                });
                if (!scriptSession) return; // call ended mid-turn
                scriptSession.bubbles = scriptSession.bubbles.concat(data.bubbles || []);
                scriptSession.terminated = !!data.terminate;
            } catch (err) {
                warn("voice script turn failed:", err);
                notify("Script error — the turn failed to advance.", "danger");
            } finally {
                if (scriptSession) {
                    scriptSession.loading = false;
                    renderScriptPanel();
                }
            }
        }

        async function endVoiceScript() {
            const session = scriptSession;
            scriptSession = null;
            hideScriptPanel();
            if (session?.sessionId) {
                try {
                    await callRpc("/voice/end", { session_id: session.sessionId });
                } catch (e) {
                    // Best-effort — the call itself still ends via hangupActive below.
                }
            }
            hangupActive();
        }

        async function acceptCall(payload) {
            if (!payload || !payload.call_log_id || !payload.sdp_offer) {
                notify("Cannot accept: missing SDP offer.", "danger");
                return;
            }
            if (activeCall) {
                notify("Another call is in progress.", "warning");
                return;
            }
            hidePopup();
            notify("Connecting…", "info");

            const call = {
                id: payload.call_log_id,
                pc: null, localStream: null, remoteStream: null,
                partnerName: payload.partner_name || payload.from_number,
                fromNumber: payload.from_number,
                partnerId: payload.partner_id || null,
                autoRecord: !!payload.auto_record,
                startTime: null, muted: false,
                recording: false, mediaRecorder: null, recordedChunks: [], audioContext: null,
                recordingStartedAt: null,
            };
            activeCall = call;

            try {
                const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
                call.localStream = stream;

                const pc = new RTCPeerConnection({ iceServers: ICE_SERVERS });
                call.pc = pc;
                watchForStuckConnection(pc);

                pc.onicecandidate = (ev) => {
                    if (!ev.candidate) log("ICE gathering complete");
                };
                pc.onconnectionstatechange = () => {
                    log("connection state:", pc.connectionState);
                    if (pc.connectionState === "failed" || pc.connectionState === "closed") {
                        teardownCall(false);
                    }
                };
                pc.oniceconnectionstatechange = () => log("ICE state:", pc.iceConnectionState);
                pc.ontrack = (ev) => {
                    log("ontrack:", ev.streams?.[0]);
                    const audio = ensureRemoteAudioEl();
                    if (ev.streams?.[0]) {
                        audio.srcObject = ev.streams[0];
                        call.remoteStream = ev.streams[0];
                        maybeAutoRecord(call);
                    }
                };

                stream.getAudioTracks().forEach((t) => pc.addTrack(t, stream));

                await pc.setRemoteDescription({ type: "offer", sdp: payload.sdp_offer });
                const answer = await pc.createAnswer();
                await pc.setLocalDescription(answer);
                await waitForIceGathering(pc, 4000);

                const result = await callRpc(
                    `/whatsapp/call/answer/${call.id}`,
                    { sdp_answer: pc.localDescription.sdp },
                );
                if (!result?.success) {
                    throw new Error(result?.error || "Accept failed");
                }
                notify("Call connected.", "success");
                call.startTime = Date.now();
                showHud(payload);
                maybeAutoRecord(call);
                if (payload.suggested_chatbot_id) {
                    startVoiceScript(payload);
                }
            } catch (err) {
                warn("accept failed:", err);
                notify("Accept failed: " + (err?.message || err), "danger");
                teardownCall(false);
            }
        }

        function declineCall(callLogId) {
            hidePopup();
            callRpc(`/whatsapp/call/decline/${callLogId}`, {})
                .then(() => notify("Call declined.", "info"))
                .catch((err) => notify("Decline failed: " + (err?.message || err), "danger"));
        }

        function hangupCall(callLogId) {
            const wrapupName = activeCall?.partnerName;
            teardownCall(true);
            callRpc(`/whatsapp/call/decline/${callLogId}`, {}).catch(() => {});
            showDispositionWrapup(callLogId, wrapupName);
        }

        // ── Wrap-up ──────────────────────────────────────────────────
        // After a call ends, offer a disposition + note that writes to
        // whatsapp.call.log. Independent of the call's own teardown.
        async function showDispositionWrapup(callLogId, contactName) {
            if (!callLogId) return;
            let dispositions = [];
            try {
                dispositions = await orm.searchRead(
                    "comm.disposition", [], ["name"], { order: "sequence, name" });
            } catch (e) {
                return; // model missing / no access — silently skip
            }
            if (!dispositions.length) return;
            const seq = ++wrapupSeq;
            state.wrapup = {
                callLogId,
                name: contactName || "",
                dispositions: dispositions.map((d) => ({ id: d.id, name: d.name })),
                dispositionId: "",
                note: "",
            };
            state.open = true;
            // Don't linger forever if the agent walks away.
            setTimeout(() => {
                if (wrapupSeq === seq) skipWrapup();
            }, 90000);
        }

        function skipWrapup() {
            wrapupSeq++;
            state.wrapup = null;
        }

        async function saveWrapup() {
            const wrapup = state.wrapup;
            if (!wrapup) return;
            const seq = wrapupSeq;
            const dispId = parseInt(wrapup.dispositionId, 10) || false;
            const note = wrapup.note || "";
            try {
                await orm.call("whatsapp.call.log", "action_set_disposition",
                    [[wrapup.callLogId], dispId, note]);
                notify("Outcome saved.", "success");
            } catch (e) {
                notify("Could not save the outcome.", "danger");
            }
            if (wrapupSeq === seq) skipWrapup();
        }

        function teardownCall(userInitiated) {
            if (!activeCall) return;
            if (activeCall.recording) {
                // Fire-and-forget: don't block teardown on the upload,
                // and the call object is captured by reference so this
                // still has its streams even after activeCall is nulled.
                stopRecordingAndUpload(activeCall);
            }
            try { activeCall.pc?.close(); } catch (e) {}
            try {
                activeCall.localStream?.getTracks().forEach((t) => t.stop());
            } catch (e) {}
            const audio = document.getElementById(AUDIO_ID);
            if (audio) audio.srcObject = null;
            activeCall = null;
            hideHud();
            // Call ended via some other path (HUD hangup, remote hung up,
            // connection failure) while a script was in progress - end that
            // session too rather than leaving it dangling server-side.
            // endVoiceScript() itself calls hangupActive() (which re-enters
            // here), so this must clear scriptSession first to avoid a loop.
            if (scriptSession) {
                const session = scriptSession;
                scriptSession = null;
                hideScriptPanel();
                if (session.sessionId) {
                    callRpc("/voice/end", { session_id: session.sessionId }).catch(() => {});
                }
            }
            if (!userInitiated) notify("Call ended.", "info");
        }

        // ── Call permission ──────────────────────────────────────────
        // One screen, reached two ways: before ringing someone we know
        // hasn't allowed calls (confirmDialWithoutPermission), and after
        // WhatsApp refused a call or the permission lapsed
        // (offerCallPermissionRequest).
        const PERMISSION_CHIPS = {
            pending: "Asked, no reply yet",
            declined: "Declined calls",
            expired: "Permission expired",
        };

        function showPermission(status, screen) {
            screen.chip = PERMISSION_CHIPS[status?.state] || "No call permission yet";
            state.permission = screen;
            state.open = true;
        }

        // Closes the screen. `choice` is cancel | request | call.
        function answerPermission(choice) {
            const answer = permissionAnswer;
            const request = permissionRequest;
            permissionAnswer = null;
            permissionRequest = null;
            state.permission = null;
            if (answer) answer(choice === "call");
            if (choice === "request" && request) sendPermissionRequest(request);
        }

        async function sendPermissionRequest({ toNumber, accountId, partnerName, partnerId }) {
            notify("Sending call permission request…", "info");
            try {
                const result = await callRpc("/whatsapp/call/request_permission", {
                    to_number: toNumber, account_id: accountId || null,
                    partner_name: partnerName || null,
                    partner_id: partnerId || null,
                });
                if (result?.success) {
                    notify("Call permission request sent. You'll be told here when they reply.", "success");
                } else if (result?.error === "template_missing") {
                    notify("Call permission not granted by user. Ensure that the call permission template is available and try again.", "danger");
                } else {
                    notify("Failed to send permission request: " + (result?.error || "Unknown error"), "danger");
                }
            } catch (err) {
                notify("Failed to send permission request: " + (err?.message || err), "danger");
            }
        }

        // Offered after a "no permission" dial failure, or when the
        // permission we had has lapsed.
        function offerCallPermissionRequest(toNumber, accountId, partnerName, partnerId, status) {
            answerPermission("cancel");
            permissionRequest = { toNumber, accountId, partnerName, partnerId };
            showPermission(status, {
                name: partnerName || toNumber,
                number: partnerName && partnerName !== toNumber ? toNumber : "",
                message: status?.message
                    || `${partnerName || toNumber} hasn't granted this number permission to call them on WhatsApp yet.`,
                hint: status?.declined_by_person
                    ? "Only ask again if they've told you they now want to be called."
                    : "Send a call permission request so they can approve it, then try calling again.",
                canRequest: true,
                canTry: false,
            });
        }

        // Warn before ringing someone we know hasn't allowed calls. Our record
        // can be out of date and Meta has the final say, so this never blocks.
        function confirmDialWithoutPermission(status) {
            return new Promise((resolve) => {
                answerPermission("cancel");
                const dial = pendingDial;
                permissionAnswer = resolve;
                permissionRequest = dial && {
                    toNumber: dial.toNumber, accountId: dial.accountId,
                    partnerName: dial.partnerName, partnerId: dial.partnerId,
                };
                showPermission(status, {
                    name: (dial && (dial.partnerName || dial.toNumber)) || "",
                    number: dial && dial.partnerName && dial.partnerName !== dial.toNumber ? dial.toNumber : "",
                    message: status.message,
                    hint: "WhatsApp will block the call unless they've allowed it since.",
                    canRequest: !!dial,
                    canTry: true,
                });
            });
        }

        // Every outbound call starts here: it puts the "Calling…" screen up
        // while dialCall sets the call up.
        async function placeCall(args) {
            let seq = 0;
            if (args && args.toNumber && !activeCall) {
                pendingDial = args;
                seq = showConnecting("Calling", args.partnerName, args.toNumber);
            }
            try {
                return await dialCall(args);
            } finally {
                if (pendingDial === args) pendingDial = null;
                hideConnecting(seq);
            }
        }

        // ── Outbound dial ─────────────────────────────────────────────
        async function dialCall({ toNumber, accountId, partnerName, partnerId, chatbotId, chatbotName }) {
            if (!toNumber) {
                notify("Enter a phone number to dial.", "warning");
                return;
            }
            if (activeCall) {
                notify("Another call is in progress.", "warning");
                return;
            }
            let permission = null;
            try {
                permission = await callRpc("/whatsapp/call/permission_status", {
                    to_number: toNumber, account_id: accountId || null,
                    partner_name: partnerName || null,
                });
            } catch (err) {
                warn("permission check failed, dialling anyway:", err);
            }
            if (permission?.state === "expired") {
                offerCallPermissionRequest(toNumber, accountId, partnerName, partnerId, permission);
                return;
            }
            if (["pending", "declined"].includes(permission?.state)
                    && !(await confirmDialWithoutPermission(permission))) {
                return;
            }
            if (activeCall) {
                notify("Another call is in progress.", "warning");
                return;
            }
            notify(`Dialling ${toNumber}…`, "info");

            const call = {
                id: null, pc: null, localStream: null,
                remoteStream: null, direction: "outgoing",
                partnerName: partnerName || toNumber,
                fromNumber: toNumber,
                partnerId: partnerId || null,
                chatbotId: chatbotId || null,
                chatbotName: chatbotName || "",
                startTime: null, muted: false,
                recording: false, mediaRecorder: null, recordedChunks: [], audioContext: null,
                recordingStartedAt: null,
            };
            activeCall = call;

            try {
                const stream = await navigator.mediaDevices.getUserMedia({
                    audio: true, video: false,
                });
                call.localStream = stream;

                const pc = new RTCPeerConnection({ iceServers: ICE_SERVERS });
                call.pc = pc;
                watchForStuckConnection(pc);

                pc.onicecandidate = (ev) => {
                    if (!ev.candidate) log("outbound ICE gathering complete");
                };
                pc.onconnectionstatechange = () => {
                    log("outbound connection state:", pc.connectionState);
                    if (pc.connectionState === "failed" || pc.connectionState === "closed") {
                        teardownCall(false);
                    }
                };
                pc.oniceconnectionstatechange = () =>
                    log("outbound ICE state:", pc.iceConnectionState);
                pc.ontrack = (ev) => {
                    log("outbound ontrack:", ev.streams?.[0]);
                    const audio = ensureRemoteAudioEl();
                    if (ev.streams?.[0]) {
                        audio.srcObject = ev.streams[0];
                        call.remoteStream = ev.streams[0];
                        maybeAutoRecord(call);
                    }
                };

                stream.getAudioTracks().forEach((t) => pc.addTrack(t, stream));

                // Create and set offer, wait for ICE.
                const offer = await pc.createOffer();
                await pc.setLocalDescription(offer);
                await waitForIceGathering(pc, 4000);

                const result = await callRpc("/whatsapp/call/dial", {
                    to_number:  toNumber,
                    sdp_offer:  pc.localDescription.sdp,
                    account_id: accountId || null,
                    partner_id: partnerId || null,
                    chatbot_id: chatbotId || null,
                });
                if (!result?.success) {
                    throw new Error(result?.error || "Dial failed");
                }
                call.id = result.call_log_id;
                call.autoRecord = !!result.auto_record;
                showHud({
                    call_log_id:  call.id,
                    partner_name: call.partnerName,
                    from_number:  call.fromNumber,
                    partner_id:   call.partnerId,
                });
                notify("Ringing…", "info");
                // Now wait for the whatsapp_outbound_answered bus event
                // to deliver the SDP answer.
            } catch (err) {
                warn("dial failed:", err);
                const message = err?.message || String(err);
                notify("Dial failed: " + message, "danger");
                teardownCall(false);
                if (/no approved call permission/i.test(message)) {
                    offerCallPermissionRequest(toNumber, accountId, partnerName, partnerId, permission);
                }
            }
        }

        async function handleOutboundAnswered(payload) {
            if (!activeCall || activeCall.direction !== "outgoing") {
                warn("outbound answered but no active outbound call");
                return;
            }
            if (activeCall.id && payload.call_log_id !== activeCall.id) {
                warn("outbound answered for a different call_log_id");
                return;
            }
            try {
                await activeCall.pc.setRemoteDescription({
                    type: "answer", sdp: payload.sdp_answer,
                });
                log("outbound remote description set — audio should establish");
                notify("Connected.", "success");
                activeCall.startTime = Date.now();
                showHud({
                    call_log_id:  activeCall.id,
                    partner_name: activeCall.partnerName || "In call",
                    from_number:  activeCall.fromNumber,
                    partner_id:   activeCall.partnerId,
                });
                maybeAutoRecord(activeCall);
                if (activeCall.chatbotId) {
                    startVoiceScript({
                        suggested_chatbot_id:   activeCall.chatbotId,
                        suggested_chatbot_name: activeCall.chatbotName,
                        partner_name:           activeCall.partnerName,
                        from_number:            activeCall.fromNumber,
                    });
                }
            } catch (err) {
                warn("setRemoteDescription failed:", err);
                notify("Media negotiation failed.", "danger");
                teardownCall(false);
            }
        }

        function hangupActive() {
            if (!activeCall) return false;
            const id = activeCall.id;
            teardownCall(true);
            if (id) {
                callRpc(`/whatsapp/call/decline/${id}`, {}).catch(() => {});
            }
            return true;
        }

        function isActive() {
            return !!activeCall;
        }

        // Browsers only honour Notification.requestPermission() when it's
        // called from within a genuine user gesture — calling it from the
        // whatsapp_incoming_call bus handler (startRinging) is too late,
        // since a bus event isn't a gesture and the browser silently
        // no-ops the prompt instead of showing it. Exposed so systray
        // components can call this from an actual click handler (presence
        // toggle, dial-pad icon) long before any call ever rings in.
        function ensureNotificationPermission() {
            try {
                if (typeof Notification !== "undefined" && Notification.permission === "default") {
                    Notification.requestPermission().catch(() => {});
                }
            } catch (e) { /* Notifications not available — ignore */ }
        }

        // ── Keypad tab ───────────────────────────────────────────────
        async function loadAccounts() {
            try {
                const result = await callRpc("/whatsapp/call/accounts", {});
                const accounts = result?.accounts || [];
                state.keypad.accounts = accounts.map((a) => ({
                    id: a.id,
                    label: (a.phone_number || a.name) + (a.is_default ? " (default)" : ""),
                }));
                if (!accounts.some((a) => a.id === state.keypad.accountId)) {
                    state.keypad.accountId = result?.default_id || (accounts[0] && accounts[0].id) || null;
                    // Call permission is per sending number.
                    lookupKeypadNumber();
                }
            } catch (e) {
                warn("account fetch failed:", e);
            }
        }

        // Opens the card on the keypad (the res.partner button, the inbox…).
        async function openDialPad() {
            if (activeCall) {
                notify("Another call is in progress.", "warning");
                return;
            }
            openCard("keypad");
        }

        function setKeypadNumber(number) {
            state.keypad.number = number || "";
            lookupKeypadNumber();
        }

        // Who the typed number belongs to and whether they allow calls, shown
        // under the number before dialling.
        let lookupSeq = 0;
        async function lookupKeypadNumber() {
            const seq = ++lookupSeq;
            const keypad = state.keypad;
            const number = keypad.number.trim();
            if (normalizeDigits(number).length < 9) {
                keypad.contact = null;
                keypad.permission = null;
                return;
            }
            const contact = await resolveContactForNumber(number);
            let permission = null;
            try {
                permission = await callRpc("/whatsapp/call/permission_status", {
                    to_number: number, account_id: keypad.accountId || null,
                    partner_name: (contact && contact.name) || null,
                });
            } catch (e) {
                // Unknown is fine: dialCall checks again before ringing.
            }
            if (seq !== lookupSeq) return; // the number changed meanwhile
            keypad.contact = contact
                ? { name: contact.name || number, partnerId: contact.partner_id ? contact.partner_id[0] : null }
                : null;
            keypad.permission = (permission && permission.state) || null;
        }

        async function dialFromKeypad() {
            const keypad = state.keypad;
            const to = keypad.number.trim();
            if (!to) {
                notify("Enter a number to dial.", "warning");
                return;
            }
            const args = {
                toNumber: to, accountId: keypad.accountId || null,
                chatbotId: keypad.chatbotId || null, chatbotName: keypad.chatbotName,
            };
            if (keypad.contact) {
                args.partnerId = keypad.contact.partnerId;
                args.partnerName = keypad.contact.name;
            }
            await placeCall(args);
            if (activeCall) {
                // The call is up: start the next one from a clean keypad.
                Object.assign(keypad, { number: "", chatbotId: null, chatbotName: "", contact: null, permission: null });
            }
        }

        function scriptForKeypad() {
            showChatbotPicker("Choose a call script", (chatbotId, chatbotName) => {
                state.keypad.chatbotId = chatbotId;
                state.keypad.chatbotName = chatbotName;
            });
        }

        async function campaignForKeypad() {
            const to = state.keypad.number.trim();
            if (!to) {
                notify("Enter a number first.", "warning");
                return;
            }
            const contact = await resolveContactForNumber(to);
            if (!contact) {
                notify("No matching contact found for this number.", "warning");
                return;
            }
            showCampaignPicker(contact.partner_id ? contact.partner_id[0] : false);
        }

        // The comm.voip.call / whatsapp.call.log id of the current active call
        // (used by the call monitor to know if a Listen request is for us).
        function getActiveCallId() {
            return activeCall ? activeCall.id : null;
        }

        // Build a one-off mixed stream (agent mic + customer) of the active
        // call for a supervisor to listen to. Returns {stream, ctx} — the caller
        // closes ctx when the monitor ends. Null if we don't own that call.
        function buildMonitorMix(callLogId) {
            if (!activeCall || activeCall.id !== callLogId
                    || !activeCall.localStream || !activeCall.remoteStream) {
                return null;
            }
            try {
                const AudioCtx = window.AudioContext || window.webkitAudioContext;
                const ctx = new AudioCtx();
                const dest = ctx.createMediaStreamDestination();
                ctx.createMediaStreamSource(activeCall.localStream).connect(dest);
                ctx.createMediaStreamSource(activeCall.remoteStream).connect(dest);
                return { stream: dest.stream, ctx };
            } catch (e) {
                warn("buildMonitorMix failed:", e);
                return null;
            }
        }

        // BARGE: mix a supervisor's audio into the agent's uplink to Meta, so
        // the customer hears the supervisor too. We replaceTrack the mic sender
        // on the live Meta PC with (agent mic + supervisor) — no renegotiation.
        function injectMonitorUplink(callLogId, supStream) {
            if (!activeCall || activeCall.id !== callLogId || !activeCall.pc
                    || !activeCall.localStream || !supStream) {
                return null;
            }
            try {
                const AudioCtx = window.AudioContext || window.webkitAudioContext;
                const ctx = new AudioCtx();
                const dest = ctx.createMediaStreamDestination();
                ctx.createMediaStreamSource(activeCall.localStream).connect(dest);
                ctx.createMediaStreamSource(supStream).connect(dest);
                const mixedTrack = dest.stream.getAudioTracks()[0];
                const sender = activeCall.pc.getSenders()
                    .find((s) => s.track && s.track.kind === "audio");
                if (!sender) { ctx.close(); return null; }
                const origTrack = sender.track;
                sender.replaceTrack(mixedTrack);
                activeCall._monitorUplink = { ctx, sender, origTrack };
                return true;
            } catch (e) {
                warn("injectMonitorUplink failed:", e);
                return null;
            }
        }

        function clearMonitorUplink(callLogId) {
            if (!activeCall || (callLogId && activeCall.id !== callLogId) || !activeCall._monitorUplink) {
                return;
            }
            const u = activeCall._monitorUplink;
            try { u.sender && u.origTrack && u.sender.replaceTrack(u.origTrack); } catch (e) { /* */ }
            try { u.ctx && u.ctx.close(); } catch (e) { /* */ }
            activeCall._monitorUplink = null;
        }

        // Public API for other components (res.partner button, inbox,
        // Agent Workspace, call monitor, etc.). dialCall goes through
        // placeCall so every outbound call shows in the card from the start.
        const publicApi = {
            dialCall: placeCall, hangupActive, isActive, openDialPad, ensureNotificationPermission,
            getActiveCallId, buildMonitorMix, injectMonitorUplink, clearMonitorUplink,
            // For the phone card and its systray icon only.
            state,
            card: {
                toggleCard, openCard, minimise, setPresence, refreshMissed,
                acceptIncoming, declineIncoming, scriptForIncoming,
                acceptTransferRequest, declineTransferRequest,
                hangup: hangupFromCard, mute: muteFromCard, record: recordFromCard,
                openTransfer: openTransferPicker, closeTransfer, transferToTeam,
                script: scriptFromCard, showScript, changeScript: openScriptPicker,
                scriptAnswer: sendScriptTurn, endScript: endVoiceScript,
                campaign: showCampaignPicker, inbox: openContactInboxFor,
                pick, closePicker, answerPermission, saveWrapup, skipWrapup,
                recentCalls, matchingContacts, activities, placeCall,
                loadAccounts, setKeypadNumber, lookupKeypadNumber, dialFromKeypad,
                scriptForKeypad, campaignForKeypad,
            },
        };
        env.services.comm_whatsapp_calling = publicApi;

        loadPresence();
        refreshMissed();

        // ── Bus wiring ────────────────────────────────────────────────
        try {
            log("bus_service keys:", Object.keys(bus_service));
            if (typeof bus_service.subscribe !== "function") {
                warn("bus_service.subscribe is not a function — API changed?");
                return publicApi;
            }
            bus_service.subscribe("whatsapp_incoming_call", (payload) => {
                log("bus event received:", payload?.type, "id:", payload?.call_log_id);
                if (payload?.type === "whatsapp_incoming_call") {
                    showPopup(payload);
                }
            });
            bus_service.subscribe("whatsapp_call_permission", (payload) => {
                notification.add(payload.message, {
                    title: "WhatsApp call permission", sticky: true,
                    type: payload.state === "granted" ? "success" : "warning",
                });
            });
            bus_service.subscribe("whatsapp_outbound_answered", (payload) => {
                log("outbound answered:", payload?.call_log_id);
                handleOutboundAnswered(payload);
            });
            bus_service.subscribe("whatsapp_transfer_request", (payload) => {
                log("transfer request received:", payload?.source_call_log_id);
                showTransferRequestPopup(payload);
            });
            bus_service.subscribe("whatsapp_call_taken", (payload) => {
                // Fired when: (a) another agent accepted / declined /
                // hung up, or (b) the remote side ended the call
                // (verb === "remote_ended"). We do THREE things here:
                //  1. Drop our Incoming screen if it's for this call.
                //  2. If our active call matches this id, tear it down —
                //     stops audio, closes the PC, clears the call screen.
                //  3. Skip step 1 (but NOT step 2) for the session that
                //     initiated the action so the accepting/hanging-up
                //     agent's own UI isn't clobbered before their flow
                //     completes.
                if (!payload || !payload.call_log_id) return;
                const myUid = env.services.user && env.services.user.userId;
                const isSelf = payload.taken_by_uid
                    && myUid && payload.taken_by_uid === myUid;

                // (1) popup dismissal — skip for the acting user.
                if (!isSelf) {
                    if (state.incoming && state.incoming.callLogId === payload.call_log_id) {
                        log("call taken elsewhere, hiding popup:", payload);
                        hidePopup();
                    }
                }

                // (2) HUD + PC teardown when the remote hung up on us.
                // This runs for the active session too — if the caller
                // dropped, our audio needs to stop regardless of who
                // triggered the event.
                const isRemoteEnd = payload.verb === "remote_ended";
                if (isRemoteEnd
                        && activeCall
                        && activeCall.id === payload.call_log_id) {
                    log("remote party ended the call; tearing down");
                    const wrapupName = activeCall.partnerName;
                    const wrapupId = activeCall.id;
                    teardownCall(false);
                    showDispositionWrapup(wrapupId, wrapupName);
                }
                refreshMissed();
            });
            if (typeof bus_service.start === "function") {
                bus_service.start();
            }
            log("bus subscribed and started");
        } catch (e) {
            warn("bus subscribe failed:", e && e.message ? e.message : e);
        }

        return publicApi;
    },
};

registry.category("services").add("comm_whatsapp_calling", waCallService);
