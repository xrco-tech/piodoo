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
            dialerOpen: false, // manual click-to-dial panel visible
        });
        let ua = null;
        let session = null;
        let audioEl = null;
        // Recording (client-side, like comm_whatsapp_calling): mix both tracks
        // and MediaRecorder them, then upload to the call on stop.
        let recorder = null;
        let recChunks = [];
        let recNodes = []; // keep graph nodes referenced so they aren't GC'd
        let recStartedAt = 0;
        // Per-speaker mono recorders (agent = local mic, caller = remote), fed
        // to the backend for a speaker-labelled transcript. Best-effort: if they
        // fail the mixed recording (and single-file transcription) still works.
        let recorderAgent = null;
        let recChunksAgent = [];
        let recorderCaller = null;
        let recChunksCaller = [];
        let callId = null; // comm.voip.call this call is logged as
        let myExt = "";    // this agent's own SIP extension
        let myDomain = ""; // SIP domain, for outbound INVITEs

        // One shared AudioContext, primed/kept-running by real user gestures so
        // the browser autoplay policy can't leave it suspended (which yields
        // silent, zero-size MediaRecorder chunks).
        let sharedCtx = null;
        function primeAudioContext() {
            try {
                if (!sharedCtx) {
                    const AudioCtx = window.AudioContext || window.webkitAudioContext;
                    sharedCtx = new AudioCtx();
                }
                if (sharedCtx.state === "suspended" && sharedCtx.resume) {
                    sharedCtx.resume().catch(() => {});
                }
            } catch {
                // ignore
            }
            return sharedCtx;
        }
        ["pointerdown", "keydown"].forEach((evt) =>
            document.addEventListener(evt, primeAudioContext, { capture: true, passive: true }));

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
            session = s;
            const outgoing = s.direction === "outgoing";
            const ri = s.remote_identity;
            const peer = (ri && ri.uri && ri.uri.user) || "";
            state.caller = peer || "Call";
            state.status = outgoing ? "calling" : "ringing";
            state.muted = false;
            state.recording = false;
            state.dialerOpen = false;
            callId = null;

            // Incoming legs from the ARI bridge carry the comm.voip.call id.
            let headerId = null;
            if (!outgoing) {
                try {
                    headerId = (e.request && e.request.getHeader && e.request.getHeader("X-Voip-Call-Id")) || null;
                } catch {
                    headerId = null;
                }
            }
            console.debug("[softphone]", outgoing ? "outgoing" : "incoming",
                          "call, peer =", peer, "call-id =", headerId, "autoRecord =", state.autoRecord);

            let callStarted = false;
            const onIncall = async () => {
                state.status = "incall";
                if (!callStarted) {
                    callStarted = true;
                    try {
                        // Resolve/create the call record (fills from/to/start/state).
                        callId = await orm.call("comm.dialer.agent.session", "softphone_call_start", [
                            headerId,
                            outgoing ? myExt : peer,   // from
                            outgoing ? peer : myExt,   // to
                            outgoing ? "outgoing" : "incoming",
                        ]);
                    } catch {
                        callId = headerId ? parseInt(headerId, 10) || null : null;
                    }
                }
                maybeAutoRecord(); // starts once remote media is up
            };
            s.on("accepted", onIncall);
            s.on("confirmed", onIncall);
            s.on("ended", onEnded);
            s.on("failed", onEnded);
            s.on("peerconnection", (ev) => attachAudio(ev.peerconnection));

            if (outgoing) {
                // ua.call() already set up local media; hook audio when the pc appears.
                if (s.connection) {
                    attachAudio(s.connection);
                }
            } else if (!state.manual) {
                // Auto-answer inbound (the customer is already on the line).
                doAnswer();
            }
        }

        function dial(number) {
            number = (number || "").trim();
            if (!ua || !number) {
                return;
            }
            if (["ringing", "calling", "incall"].includes(state.status)) {
                return; // already on a call
            }
            try {
                ua.call("sip:" + number + "@" + myDomain, {
                    mediaConstraints: { audio: true, video: false },
                    pcConfig: { iceServers: state._ice || [] },
                });
                // onSession fires for the outgoing session and wires the rest.
            } catch (err) {
                console.warn("[softphone] dial failed:", err);
            }
        }

        function toggleDialer() {
            if (state.status === "registered") {
                state.dialerOpen = !state.dialerOpen;
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
            const endedCall = callId;
            if (recorder) {
                stopRecordingAndUpload(); // captures callId synchronously
            }
            if (endedCall) {
                // Close out the call record (end_time + duration + state).
                orm.call("comm.dialer.agent.session", "softphone_call_end", [endedCall]).catch(() => {});
            }
            callId = null;
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
                console.debug("[softphone] startRecording tracks — local:", localTracks.length, "remote:", remoteTracks.length);
                if (!localTracks.length || !remoteTracks.length) {
                    return; // media not up yet — will retry on the track event
                }
                const ctx = primeAudioContext();
                if (!ctx) {
                    return;
                }
                const dest = ctx.createMediaStreamDestination();
                const localNode = ctx.createMediaStreamSource(new MediaStream(localTracks));
                const remoteNode = ctx.createMediaStreamSource(new MediaStream(remoteTracks));
                localNode.connect(dest);
                remoteNode.connect(dest);
                recNodes = [localNode, remoteNode, dest];

                recChunks = [];
                recorder = new MediaRecorder(dest.stream);
                recorder.ondataavailable = (ev) => {
                    if (ev.data && ev.data.size) {
                        recChunks.push(ev.data);
                    }
                };
                // Timeslice → emit a chunk each second (robust against stop timing).
                recorder.start(1000);
                recStartedAt = Date.now();
                state.recording = true;
                console.debug("[softphone] recording started");

                // Per-speaker mono recorders (best-effort — never break the mix).
                try {
                    const destAgent = ctx.createMediaStreamDestination();
                    localNode.connect(destAgent);
                    recChunksAgent = [];
                    recorderAgent = new MediaRecorder(destAgent.stream);
                    recorderAgent.ondataavailable = (ev) => {
                        if (ev.data && ev.data.size) { recChunksAgent.push(ev.data); }
                    };
                    recorderAgent.start(1000);

                    const destCaller = ctx.createMediaStreamDestination();
                    remoteNode.connect(destCaller);
                    recChunksCaller = [];
                    recorderCaller = new MediaRecorder(destCaller.stream);
                    recorderCaller.ondataavailable = (ev) => {
                        if (ev.data && ev.data.size) { recChunksCaller.push(ev.data); }
                    };
                    recorderCaller.start(1000);
                    recNodes.push(destAgent, destCaller);
                } catch (chanErr) {
                    console.warn("[softphone] per-channel recorders failed:", chanErr);
                    recorderAgent = null;
                    recorderCaller = null;
                }
            } catch (err) {
                console.warn("[softphone] startRecording failed:", err);
                recorder = null;
                state.recording = false;
            }
        }

        async function stopRecordingAndUpload() {
            const rec = recorder;
            const chunks = recChunks;
            const nodes = recNodes;
            const startedAt = recStartedAt;
            const targetCall = callId;
            const recAgent = recorderAgent;
            const chunksAgent = recChunksAgent;
            const recCaller = recorderCaller;
            const chunksCaller = recChunksCaller;
            recorder = null;
            recChunks = [];
            recNodes = [];
            recorderAgent = null;
            recChunksAgent = [];
            recorderCaller = null;
            recChunksCaller = [];
            state.recording = false;
            if (!rec) {
                return;
            }
            const stopOne = (r) => new Promise((resolve) => {
                if (!r) { resolve(); return; }
                r.addEventListener("stop", resolve, { once: true });
                try { r.stop(); } catch { resolve(); }
            });
            await Promise.all([stopOne(rec), stopOne(recAgent), stopOne(recCaller)]);
            // Tear down the graph nodes but keep the shared AudioContext alive.
            try {
                nodes.forEach((n) => n.disconnect && n.disconnect());
            } catch {
                // ignore
            }
            console.debug("[softphone] stopRecording — chunks:", chunks.length, "callId:", targetCall);
            if (!chunks.length || !targetCall) {
                return; // nothing recorded, or no call to attach to
            }
            const durationSeconds = startedAt ? Math.round((Date.now() - startedAt) / 1000) : 0;
            const form = new FormData();
            form.append("recording", new Blob(chunks, { type: "audio/webm" }), "voip_recording.webm");
            form.append("duration", String(durationSeconds));
            // Per-speaker mono streams for a speaker-labelled transcript.
            if (chunksAgent && chunksAgent.length) {
                form.append("recording_agent", new Blob(chunksAgent, { type: "audio/webm" }), "agent.webm");
            }
            if (chunksCaller && chunksCaller.length) {
                form.append("recording_caller", new Blob(chunksCaller, { type: "audio/webm" }), "caller.webm");
            }
            try {
                const resp = await fetch(`/voip/call/upload_recording/${targetCall}`, {
                    method: "POST",
                    credentials: "same-origin",
                    body: form,
                });
                console.debug("[softphone] recording upload status:", resp.status);
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
            myExt = cfg.ext || "";
            myDomain = cfg.domain || "";
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
        return {
            state, toggleMute, hangup, accept, decline, toggleRecord, dial, toggleDialer,
            // The comm.voip.call id of the current call (for the Transfer wizard).
            get callId() { return callId; },
        };
    },
};

registry.category("services").add("dialer_softphone", softphoneService);
