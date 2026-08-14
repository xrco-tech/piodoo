/** @odoo-module **/

import { Component, useState, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

/**
 * Agent WebRTC softphone (systray).
 *
 * Registers the agent's endpoint to Asterisk over WSS via JsSIP and
 * AUTO-ANSWERS the incoming agent leg the dialer bridge originates when a
 * human answers. Agents don't dial from here — the dialer drives origination;
 * this is the receive + in-call controls (mute / hangup) surface.
 *
 * Stays completely inert until an Asterisk account + the user's SIP endpoint
 * are provisioned (get_softphone_config returns enabled:false).
 */
export class DialerSoftphone extends Component {
    static template = "comm_dialer.Softphone";
    static props = {};

    setup() {
        this.orm = useService("orm");
        this.audioRef = useRef("audio");
        this.state = useState({
            enabled: false,
            status: "idle", // idle | connecting | registered | unregistered | failed | ringing | incall
            caller: "",
            muted: false,
        });
        this.ua = null;
        this.session = null;
        onMounted(() => this._init());
        onWillUnmount(() => this._teardown());
    }

    async _init() {
        let cfg;
        try {
            cfg = await this.orm.call("comm.dialer.agent.session", "get_softphone_config", []);
        } catch {
            return; // not provisioned / no access — stay idle, no noise
        }
        if (!cfg || !cfg.enabled) {
            return;
        }
        if (typeof window.JsSIP === "undefined") {
            this.state.enabled = true;
            this.state.status = "failed";
            return;
        }
        this.cfg = cfg;
        this.state.enabled = true;
        this._connect();
    }

    _connect() {
        const JsSIP = window.JsSIP;
        this.state.status = "connecting";
        try {
            const socket = new JsSIP.WebSocketInterface(this.cfg.ws_url);
            this.ua = new JsSIP.UA({
                sockets: [socket],
                uri: `sip:${this.cfg.ext}@${this.cfg.domain}`,
                password: this.cfg.secret,
                register: true,
                session_timers: false,
            });
            this.ua.on("registered", () => (this.state.status = "registered"));
            this.ua.on("unregistered", () => (this.state.status = "unregistered"));
            this.ua.on("registrationFailed", () => (this.state.status = "failed"));
            this.ua.on("disconnected", () => (this.state.status = "failed"));
            this.ua.on("newRTCSession", (e) => this._onSession(e));
            this.ua.start();
        } catch {
            this.state.status = "failed";
        }
    }

    _onSession(e) {
        const session = e.session;
        // The dialer bridges INTO the agent — we only take incoming legs.
        if (session.direction !== "incoming") {
            return;
        }
        this.session = session;
        const ri = session.remote_identity;
        this.state.caller = (ri && ri.uri && ri.uri.user) || "Call";
        this.state.status = "ringing";
        this.state.muted = false;

        session.on("accepted", () => (this.state.status = "incall"));
        session.on("confirmed", () => (this.state.status = "incall"));
        session.on("ended", () => this._onEnded());
        session.on("failed", () => this._onEnded());
        session.on("peerconnection", (ev) => this._attachAudio(ev.peerconnection));

        // Auto-answer: the leg only reaches us once a human has answered.
        session.answer({
            mediaConstraints: { audio: true, video: false },
            pcConfig: { iceServers: this.cfg.ice || [] },
        });
        if (session.connection) {
            this._attachAudio(session.connection);
        }
    }

    _attachAudio(pc) {
        if (!pc || !this.audioRef.el) {
            return;
        }
        pc.addEventListener("track", (ev) => {
            if (ev.streams && ev.streams[0]) {
                this.audioRef.el.srcObject = ev.streams[0];
                this.audioRef.el.play().catch(() => {});
            }
        });
    }

    _onEnded() {
        this.session = null;
        this.state.caller = "";
        this.state.muted = false;
        this.state.status = this.ua && this.ua.isRegistered() ? "registered" : "unregistered";
    }

    toggleMute() {
        if (!this.session) {
            return;
        }
        if (this.state.muted) {
            this.session.unmute({ audio: true });
            this.state.muted = false;
        } else {
            this.session.mute({ audio: true });
            this.state.muted = true;
        }
    }

    hangup() {
        if (this.session) {
            try {
                this.session.terminate();
            } catch {
                // already gone
            }
        }
    }

    _teardown() {
        try {
            if (this.session) {
                this.session.terminate();
            }
        } catch {
            // ignore
        }
        try {
            if (this.ua) {
                this.ua.stop();
            }
        } catch {
            // ignore
        }
    }

    get dotClass() {
        return {
            registered: "o_sp_ok",
            incall: "o_sp_incall",
            ringing: "o_sp_ring",
            connecting: "o_sp_wait",
            unregistered: "o_sp_off",
            failed: "o_sp_err",
            idle: "o_sp_off",
        }[this.state.status] || "o_sp_off";
    }

    get statusLabel() {
        return {
            registered: "Softphone ready",
            incall: "On call",
            ringing: "Incoming call",
            connecting: "Connecting…",
            unregistered: "Not registered",
            failed: "Softphone error",
            idle: "Idle",
        }[this.state.status] || "Softphone";
    }
}

registry.category("systray").add(
    "comm_dialer.softphone",
    { Component: DialerSoftphone },
    { sequence: 20 }
);
