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
        });
        let ua = null;
        let session = null;
        let audioEl = null;

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
            });
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

            s.on("accepted", () => (state.status = "incall"));
            s.on("confirmed", () => (state.status = "incall"));
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
            session = null;
            state.caller = "";
            state.muted = false;
            state.status = ua && ua.isRegistered() ? "registered" : "unregistered";
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
        return { state, toggleMute, hangup, accept, decline };
    },
};

registry.category("services").add("dialer_softphone", softphoneService);
