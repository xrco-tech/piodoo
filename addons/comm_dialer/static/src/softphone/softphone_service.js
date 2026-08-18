/** @odoo-module **/

import { reactive } from "@odoo/owl";
import { registry } from "@web/core/registry";

/**
 * Softphone service — owns the JsSIP UserAgent and the reactive call state, so
 * both the systray status icon and the floating call bar share one connection.
 *
 * The agent doesn't dial from here — the dialer bridge originates the agent leg
 * and this AUTO-ANSWERS it. Stays inert until an Asterisk account + the user's
 * SIP endpoint are provisioned (get_softphone_config returns enabled:false).
 */
export const softphoneService = {
    dependencies: ["orm"],
    start(env, { orm }) {
        const state = reactive({
            enabled: false,
            status: "idle", // idle | connecting | registered | unregistered | failed | ringing | incall
            caller: "",
            muted: false,
            manual: false, // ring with Accept/Decline instead of auto-answering
            recording: false,
            autoRecord: false,
        });
        let ua = null;
        let session = null;
        let audioEl = null;
        // Recording (client-side, like comm_whatsapp_calling): mix both tracks
        // and MediaRecorder them, then upload to the call on stop.
        let recorder = null;
        let recChunks = [];
        let recCtx = null;
        let recStartedAt = 0;
        let callId = null; // comm.voip.call id, read from the INVITE header

        function ensureAudio() {
            if (!audioEl) {
                audioEl = document.createElement("audio");
                audioEl.autoplay = true;
                audioEl.setAttribute("data-dialer-softphone", "1");
                document.body.appendChild(audioEl);
            }
            return audioEl;
        }

        function attachAudio(pc) {
            if (!pc) {
                return;
            }
            pc.addEventListener("track", (ev) => {
                if (ev.streams && ev.streams[0]) {
                    ensureAudio().srcObject = ev.streams[0];
                    ensureAudio().play().catch(() => {});
                }
                // Remote media is now flowing — safe to auto-record.
                maybeAutoRecord();
            });
        }

        function maybeAutoRecord() {
            if (state.autoRecord && !recorder && state.status === "incall") {
                startRecording();
            }
        }

        function onSession(e) {
            const s = e.session;
            if (s.direction !== "incoming") {
                return; // the dialer bridges IN to us
            }
            session = s;
            const ri = s.remote_identity;
            state.caller = (ri && ri.uri && ri.uri.user) || "Call";
            state.status = "ringing";
            state.muted = false;
            state.recording = false;
            // The ARI bridge stamps the comm.voip.call id on the agent leg so
            // the recording attaches to the right call.
            try {
                callId = (e.request && e.request.getHeader && e.request.getHeader("X-Voip-Call-Id")) || null;
            } catch {
                callId = null;
            }

            console.log("[softphone] incoming call, X-Voip-Call-Id =", callId, "autoRecord =", state.autoRecord);
            const onIncall = () => {
                state.status = "incall";
                maybeAutoRecord(); // starts now if remote media is already up
            };
            s.on("accepted", onIncall);
            s.on("confirmed", onIncall);
            s.on("ended", onEnded);
            s.on("failed", onEnded);
            s.on("peerconnection", (ev) => attachAudio(ev.peerconnection));

            // Auto-answer by default (the customer is already on the line). In
            // manual mode we leave it ringing until the agent clicks Accept.
            if (!state.manual) {
                doAnswer();
            }
        }

        function doAnswer() {
            if (!session) {
                return;
            }
            session.answer({
                mediaConstraints: { audio: true, video: false },
                pcConfig: { iceServers: state._ice || [] },
            });
            if (session.connection) {
                attachAudio(session.connection);
            }
        }

        function accept() {
            if (session && state.status === "ringing") {
                doAnswer();
            }
        }

        function decline() {
            hangup();
        }

        function onEnded() {
            if (recorder) {
                stopRecordingAndUpload();
            }
            session = null;
            state.caller = "";
            state.muted = false;
            state.status = ua && ua.isRegistered() ? "registered" : "unregistered";
        }

        // ── Recording ────────────────────────────────────────────────────
        function startRecording() {
            if (recorder || !session || !session.connection) {
                return;
            }
            try {
                const pc = session.connection;
                const localTracks = pc.getSenders().map((s) => s.track).filter((t) => t && t.kind === "audio");
                const remoteTracks = pc.getReceivers().map((r) => r.track).filter((t) => t && t.kind === "audio");
                console.log("[softphone] startRecording tracks — local:", localTracks.length, "remote:", remoteTracks.length);
                if (!localTracks.length || !remoteTracks.length) {
                    return; // media not up yet — will retry on the track event
                }
                const AudioCtx = window.AudioContext || window.webkitAudioContext;
                recCtx = new AudioCtx();
                const dest = recCtx.createMediaStreamDestination();
                recCtx.createMediaStreamSource(new MediaStream(localTracks)).connect(dest);
                recCtx.createMediaStreamSource(new MediaStream(remoteTracks)).connect(dest);

                recChunks = [];
                recorder = new MediaRecorder(dest.stream);
                recorder.ondataavailable = (ev) => {
                    if (ev.data && ev.data.size) {
                        recChunks.push(ev.data);
                    }
                };
                recorder.start();
                recStartedAt = Date.now();
                state.recording = true;
                console.log("[softphone] recording started");
            } catch (err) {
                console.warn("[softphone] startRecording failed:", err);
                recorder = null;
                state.recording = false;
            }
        }

        async function stopRecordingAndUpload() {
            const rec = recorder;
            const chunks = recChunks;
            const ctx = recCtx;
            const startedAt = recStartedAt;
            const targetCall = callId;
            recorder = null;
            recChunks = [];
            recCtx = null;
            state.recording = false;
            if (!rec) {
                return;
            }
            await new Promise((resolve) => {
                rec.addEventListener("stop", resolve, { once: true });
                try {
                    rec.stop();
                } catch {
                    resolve();
                }
            });
            try {
                if (ctx) {
                    ctx.close();
                }
            } catch {
                // ignore
            }
            console.log("[softphone] stopRecording — chunks:", chunks.length, "callId:", targetCall);
            if (!chunks.length || !targetCall) {
                return; // nothing recorded, or no call to attach to
            }
            const durationSeconds = startedAt ? Math.round((Date.now() - startedAt) / 1000) : 0;
            const form = new FormData();
            form.append("recording", new Blob(chunks, { type: "audio/webm" }), "voip_recording.webm");
            form.append("duration", String(durationSeconds));
            try {
                const resp = await fetch(`/voip/call/upload_recording/${targetCall}`, {
                    method: "POST",
                    credentials: "same-origin",
                    body: form,
                });
                console.log("[softphone] recording upload status:", resp.status);
            } catch (err) {
                console.warn("[softphone] recording upload failed:", err);
            }
        }

        function toggleRecord() {
            if (state.status !== "incall") {
                return;
            }
            if (state.recording) {
                stopRecordingAndUpload();
            } else {
                startRecording();
            }
        }

        function connect(cfg) {
            const JsSIP = window.JsSIP;
            state.status = "connecting";
            try {
                const socket = new JsSIP.WebSocketInterface(cfg.ws_url);
                ua = new JsSIP.UA({
                    sockets: [socket],
                    uri: `sip:${cfg.ext}@${cfg.domain}`,
                    password: cfg.secret,
                    register: true,
                    session_timers: false,
                });
                ua.on("registered", () => (state.status = "registered"));
                ua.on("unregistered", () => (state.status = "unregistered"));
                ua.on("registrationFailed", () => (state.status = "failed"));
                ua.on("disconnected", () => (state.status = "failed"));
                ua.on("newRTCSession", onSession);
                ua.start();
            } catch {
                state.status = "failed";
            }
        }

        async function init() {
            let cfg;
            try {
                cfg = await orm.call("comm.dialer.agent.session", "get_softphone_config", []);
            } catch {
                return; // not provisioned / no access — stay idle
            }
            if (!cfg || !cfg.enabled) {
                return;
            }
            state.enabled = true;
            state._ice = cfg.ice || [];
            state.manual = !!cfg.manual_answer;
            state.autoRecord = !!cfg.auto_record;
            if (typeof window.JsSIP === "undefined") {
                state.status = "failed";
                return;
            }
            connect(cfg);
        }

        function toggleMute() {
            if (!session) {
                return;
            }
            if (state.muted) {
                session.unmute({ audio: true });
                state.muted = false;
            } else {
                session.mute({ audio: true });
                state.muted = true;
            }
        }

        function hangup() {
            if (session) {
                try {
                    session.terminate();
                } catch {
                    // already gone
                }
            }
        }

        init();
        return { state, toggleMute, hangup, accept, decline, toggleRecord };
    },
};

registry.category("services").add("dialer_softphone", softphoneService);
