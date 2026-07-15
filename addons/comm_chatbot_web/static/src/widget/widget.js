/**
 * Comm Chatbot — embeddable web chat widget.
 *
 * Usage on any website:
 *   <link rel="stylesheet" href="https://YOUR.ODOO/comm_chatbot_web/widget.css">
 *   <script>
 *     window.COMM_CHATBOT_WEB = { botId: 42, baseUrl: "https://YOUR.ODOO" };
 *   </script>
 *   <script src="https://YOUR.ODOO/comm_chatbot_web/widget.js"></script>
 *
 * Puts a floating chat bubble bottom-right. Click to open the panel.
 * Self-contained: no dependencies, ~600 lines of vanilla JS.
 */
(function () {
    "use strict";

    const CFG = Object.assign({
        botId: null,
        preview: false,
        baseUrl: "",         // Odoo origin. Empty = same-origin.
        autoOpen: false,     // Open panel on load
        personaName: "",
        personaMobile: "",
        storageKey: "comm_chatbot_web_token",
        // Lets a channel-specific embed page (e.g. comm_whatsapp_chatbot_web)
        // point session calls at its own controller/model instead of the
        // generic comm.bot one, and rename the id param it expects.
        endpointPrefix: "/comm_chatbot_web",
        botIdKey: "bot_id",
    }, window.COMM_CHATBOT_WEB || {});

    if (!CFG.botId) {
        console.warn("[comm_chatbot_web] window.COMM_CHATBOT_WEB.botId not set");
        return;
    }

    // ── State ────────────────────────────────────────────────────────
    const state = {
        token: null,
        botName: "",
        messages: [],
        waiting: "none",
        currentOptions: [],
        userInput: "",
        loading: false,
        open: !!CFG.autoOpen,
    };

    // ── Root elements ────────────────────────────────────────────────
    let rootEl, panelEl, bubbleEl, transcriptEl, promptEl, inputEl, sendBtn;

    // ── HTTP helper ─────────────────────────────────────────────────
    async function rpc(path, body) {
        const url = (CFG.baseUrl || "") + path;
        const resp = await fetch(url, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({jsonrpc: "2.0", method: "call",
                                   params: body || {}}),
            credentials: "include",
        });
        if (!resp.ok) throw new Error("HTTP " + resp.status);
        const json = await resp.json();
        if (json.error) throw new Error(json.error.data
                                          ? json.error.data.message
                                          : json.error.message);
        return json.result;
    }

    // ── Session lifecycle ───────────────────────────────────────────
    async function startSession() {
        state.loading = true;
        render();
        try {
            const data = await rpc(CFG.endpointPrefix + "/session/start", {
                [CFG.botIdKey]: CFG.botId,
                referer: window.location.href,
                user_agent: navigator.userAgent,
                preview: CFG.preview,
                persona_name: CFG.personaName,
                persona_mobile: CFG.personaMobile,
            });
            if (data.error) throw new Error(data.error);
            _applyResponse(data);
            if (!CFG.preview) {
                try { localStorage.setItem(CFG.storageKey, data.token); }
                catch (e) {}
            }
        } catch (e) {
            _showError(e.message);
        } finally {
            state.loading = false;
            render();
        }
    }

    async function sendMessage(body, optionValue) {
        if (!state.token) return;
        state.loading = true;
        render();
        try {
            const data = await rpc(CFG.endpointPrefix + "/session/message", {
                token: state.token,
                body: body,
                option_value: optionValue,
            });
            if (data.error && data.error !== 'conversation closed')
                throw new Error(data.error);
            _applyResponse(data);
        } catch (e) {
            _showError(e.message);
        } finally {
            state.loading = false;
            state.userInput = "";
            render();
        }
    }

    function _applyResponse(data) {
        state.token = data.token || state.token;
        state.botName = data.bot_name || state.botName;
        state.messages = data.messages || [];
        state.waiting = data.waiting || "none";
        state.currentOptions = data.current_options || [];
    }

    function _showError(msg) {
        state.messages.push({
            direction: "outbound",
            body: "⚠️ " + msg,
            step_name: "error",
        });
    }

    // ── Rendering ───────────────────────────────────────────────────
    function render() {
        if (!panelEl) return;
        panelEl.classList.toggle("o_ccw_open", state.open);
        panelEl.querySelector(".o_ccw_title").textContent =
            state.botName || "Chat";

        // Transcript
        transcriptEl.innerHTML = "";
        for (const m of state.messages) {
            const bubble = document.createElement("div");
            bubble.className = "o_ccw_bubble_msg o_ccw_dir_" + m.direction;
            const meta = document.createElement("div");
            meta.className = "o_ccw_msg_meta";
            meta.textContent = m.direction === "outbound"
                ? "🤖 " + (state.botName || "Bot")
                : "You";
            bubble.appendChild(meta);

            const body = document.createElement("div");
            body.className = "o_ccw_msg_body";
            body.textContent = m.body || "";
            bubble.appendChild(body);

            // Media
            if (m.media && m.media.length) {
                for (const media of m.media) {
                    if (media.kind === "image" && media.url) {
                        const img = document.createElement("img");
                        img.src = media.url;
                        img.alt = media.alt || "";
                        img.className = "o_ccw_msg_media";
                        bubble.appendChild(img);
                    } else if (media.kind === "video" && media.url) {
                        const vid = document.createElement("video");
                        vid.src = media.url;
                        vid.controls = true;
                        vid.className = "o_ccw_msg_media";
                        bubble.appendChild(vid);
                    } else if (media.kind === "audio" && media.url) {
                        const aud = document.createElement("audio");
                        aud.src = media.url;
                        aud.controls = true;
                        bubble.appendChild(aud);
                    } else if (media.kind === "document" && media.url) {
                        const a = document.createElement("a");
                        a.href = media.url;
                        a.target = "_blank";
                        a.textContent = "📎 " + (media.alt || "Attachment");
                        a.className = "o_ccw_msg_doc";
                        bubble.appendChild(a);
                    }
                }
            }
            transcriptEl.appendChild(bubble);
        }
        transcriptEl.scrollTop = transcriptEl.scrollHeight;

        // Prompt / options
        promptEl.innerHTML = "";
        if (state.waiting === "menu" && state.currentOptions.length) {
            const wrap = document.createElement("div");
            wrap.className = "o_ccw_options";
            for (const opt of state.currentOptions) {
                const btn = document.createElement("button");
                btn.className = "o_ccw_option_btn";
                btn.textContent = opt.label;
                btn.onclick = () => sendMessage(opt.label, opt.value);
                wrap.appendChild(btn);
            }
            promptEl.appendChild(wrap);
        } else if (state.waiting === "done") {
            const done = document.createElement("div");
            done.className = "o_ccw_ended";
            done.textContent = "Conversation ended";
            promptEl.appendChild(done);
        }

        // Input row
        const inputRow = panelEl.querySelector(".o_ccw_input_row");
        inputRow.style.display = state.waiting === "done" ? "none" : "flex";
        inputEl.disabled = state.loading;
        sendBtn.disabled = state.loading;
    }

    // ── DOM build ──────────────────────────────────────────────────
    function mount() {
        rootEl = document.createElement("div");
        rootEl.className = "o_ccw_widget";
        rootEl.innerHTML = `
            <div class="o_ccw_bubble">💬</div>
            <div class="o_ccw_panel">
                <div class="o_ccw_header">
                    <span class="o_ccw_title"></span>
                    <button class="o_ccw_close" title="Close">✕</button>
                </div>
                <div class="o_ccw_transcript"></div>
                <div class="o_ccw_prompt"></div>
                <div class="o_ccw_input_row">
                    <input type="text" class="o_ccw_input"
                           placeholder="Type your message…"/>
                    <button class="o_ccw_send">Send</button>
                </div>
            </div>
        `;
        document.body.appendChild(rootEl);

        panelEl = rootEl.querySelector(".o_ccw_panel");
        bubbleEl = rootEl.querySelector(".o_ccw_bubble");
        transcriptEl = rootEl.querySelector(".o_ccw_transcript");
        promptEl = rootEl.querySelector(".o_ccw_prompt");
        inputEl = rootEl.querySelector(".o_ccw_input");
        sendBtn = rootEl.querySelector(".o_ccw_send");

        // Wire events
        bubbleEl.onclick = async () => {
            state.open = !state.open;
            if (state.open && !state.token) {
                await startSession();
            } else {
                render();
            }
        };
        rootEl.querySelector(".o_ccw_close").onclick = () => {
            state.open = false;
            render();
        };
        inputEl.oninput = (e) => { state.userInput = e.target.value; };
        inputEl.onkeydown = (e) => {
            if (e.key === "Enter" && state.userInput.trim()) {
                sendMessage(state.userInput.trim());
            }
        };
        sendBtn.onclick = () => {
            if (state.userInput.trim()) sendMessage(state.userInput.trim());
        };

        // Auto-open
        if (CFG.autoOpen) {
            state.open = true;
            startSession();
        } else {
            render();
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", mount);
    } else {
        mount();
    }
})();
