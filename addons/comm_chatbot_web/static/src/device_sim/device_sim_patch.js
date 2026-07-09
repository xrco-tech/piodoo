/** @odoo-module **/

/**
 * Adds a "Device preview" tab to the bot flow viewer.
 *
 * The tab renders the embeddable web widget inside a phone / tablet /
 * desktop frame — an actual iframe pointed at
 * /comm_chatbot_web/embed/<bot_id>?preview=1 so the widget runs against
 * a real preview session (force_shadow, skip LLM).
 *
 * Patched into the existing BotFlowAction via Owl xml() so we don't fork
 * the whole template.
 */
import { patch } from "@web/core/utils/patch";
import { xml } from "@odoo/owl";
import { BotFlowAction } from "@comm_chatbot/js/bot_flow_widget";

const DEVICES = [
    { key: "iphone",   label: "iPhone",  cssClass: "o_bf_device_iphone"  },
    { key: "pixel",    label: "Pixel",   cssClass: "o_bf_device_pixel"   },
    { key: "ipad",     label: "iPad",    cssClass: "o_bf_device_ipad"    },
    { key: "desktop",  label: "Desktop", cssClass: "o_bf_device_desktop" },
];

patch(BotFlowAction.prototype, {
    setup() {
        super.setup(...arguments);
        this.state.deviceSim = {
            active: "iphone",
        };
        this._devices = DEVICES;
    },

    _pickDevice(key) {
        this.state.deviceSim.active = key;
    },

    _deviceEmbedUrl() {
        if (!this.state.botId) return "";
        return `/comm_chatbot_web/embed/${this.state.botId}?preview=1&_ts=${Date.now()}`;
    },

    _activeDevice() {
        return this._devices.find(d => d.key === this.state.deviceSim.active)
                || this._devices[0];
    },
});

// Inject the extra panel via a template patch — appended to the right-side
// panel as a third tab option ("Device preview").
BotFlowAction.template = xml`
<div class="o_bot_flow_action">
    <div class="o_bot_flow_toolbar">
        <div class="o_bf_toolbar_left">
            <button class="btn btn-sm btn-light o_bf_back_btn"
                    t-on-click="() => this._goBack()">
                <i class="fa fa-chevron-left"/>
            </button>
            <span class="o_bot_flow_title" t-esc="state.botName"/>
        </div>
        <div class="o_bf_toolbar_right">
            <button class="btn btn-sm btn-light o_bf_zoom_btn"
                    t-on-click="() => this._setZoom(state.zoom - 0.1)">−</button>
            <span class="o_bf_zoom_label" t-esc="zoomLabel"/>
            <button class="btn btn-sm btn-light o_bf_zoom_btn"
                    t-on-click="() => this._setZoom(state.zoom + 0.1)">+</button>
            <button class="btn btn-sm btn-light ms-2"
                    t-on-click="() => this._togglePanel()">
                <i t-att-class="state.panelVisible ? 'fa fa-angle-double-right' : 'fa fa-angle-double-left'"/>
            </button>
        </div>
    </div>

    <div class="o_bot_flow_body">
        <div class="o_bot_flow_canvas_wrap">
            <div t-if="state.loading" class="o_bot_flow_loading">
                <div class="o_bf_loading_spinner"/>
            </div>
            <div t-else="" class="o_bot_flow_canvas" t-ref="canvas">
                <div class="o_bf_grid" t-ref="grid"
                     t-attf-style="transform: scale({{state.zoom}}); transform-origin: 0 0; width: #{_gridWidth()}px; height: #{_gridHeight()}px;">
                    <svg class="o_bf_svg" t-ref="svg"/>
                    <t t-foreach="state.nodes" t-as="node" t-key="node.id">
                        <div t-att-data-id="node.id"
                             t-attf-class="o_bf_card o_bf_kind_#{node.kind} #{state.selectedStepId === node.id ? 'o_bf_card_selected' : ''} #{state.sim.currentStepId === node.id ? 'o_bf_sim_current' : ''}"
                             t-attf-style="position: absolute; #{_nodePosStyle(node)} width: 220px; background:#{_typeCfg(node.kind).bg}; border-color:#{_typeCfg(node.kind).border};"
                             t-on-click="() => this._selectStep(node.id)"
                             t-on-dblclick="() => this._openStepForm(node.id)">
                            <div class="o_bf_card_head"
                                 t-attf-style="color:#{_typeCfg(node.kind).color};">
                                <span class="o_bf_card_type_icon" t-esc="_typeCfg(node.kind).icon"/>
                                <span class="o_bf_card_name" t-esc="node.name"/>
                                <span class="o_bf_card_badge"
                                      t-attf-style="background:#{_typeCfg(node.kind).color};"
                                      t-esc="_typeCfg(node.kind).label"/>
                            </div>
                            <div class="o_bf_card_content" t-if="node.preview">
                                <t t-esc="node.preview"/>
                            </div>
                        </div>
                    </t>
                </div>
            </div>
        </div>

        <div t-att-class="'o_bot_flow_props' + (state.panelVisible ? '' : ' o_bot_flow_props_collapsed')"
             t-if="!state.loading">
            <div class="o_bf_panel_tabs">
                <button t-att-class="'o_bf_panel_tab' + (state.panelMode === 'props' ? ' active' : '')"
                        t-on-click="() => this._setPanelMode('props')">
                    <i class="fa fa-info-circle me-1"/>Properties
                </button>
                <button t-att-class="'o_bf_panel_tab' + (state.panelMode === 'sim' ? ' active' : '')"
                        t-on-click="() => this._setPanelMode('sim')">
                    <i class="fa fa-play-circle me-1"/>Simulator
                </button>
                <button t-att-class="'o_bf_panel_tab' + (state.panelMode === 'device' ? ' active' : '')"
                        t-on-click="() => this._setPanelMode('device')">
                    <i class="fa fa-mobile me-1"/>Device
                </button>
            </div>

            <t t-if="state.panelMode === 'props'">
                <t t-set="step" t-value="_selectedStep()"/>
                <div class="o_bf_props_content">
                    <t t-if="!step">
                        <div class="text-muted p-3">Click a step to view its properties.</div>
                    </t>
                    <t t-if="step">
                        <div class="o_bf_prop_row">
                            <div class="o_bf_prop_label">Name</div>
                            <div class="o_bf_prop_value" t-esc="step.name"/>
                        </div>
                        <div class="o_bf_prop_row">
                            <div class="o_bf_prop_label">Kind</div>
                            <div class="o_bf_prop_value">
                                <span t-esc="_typeCfg(step.kind).icon"/>
                                <span t-esc="_typeCfg(step.kind).label"/>
                            </div>
                        </div>
                        <div class="o_bf_prop_row" t-if="step.body">
                            <div class="o_bf_prop_label">Body</div>
                            <div class="o_bf_prop_value">
                                <pre t-esc="step.body" class="o_bf_prop_pre"/>
                            </div>
                        </div>
                        <button class="btn btn-sm btn-primary mt-3"
                                t-on-click="() => this._openStepForm(step.id)">
                            <i class="fa fa-external-link me-1"/>Open step form
                        </button>
                    </t>
                </div>
            </t>

            <t t-if="state.panelMode === 'sim'">
                <div t-attf-class="o_bf_sim o_bf_sim_#{state.sim.channel}">
                    <t t-if="!state.sim.started">
                        <div class="o_bf_sim_persona_form">
                            <div class="o_bf_sim_persona_title">Run as a contact</div>
                            <div class="o_bf_sim_persona_help">
                                The bot will run against this test persona in
                                shadow mode — nothing is actually sent.
                            </div>
                            <label class="o_bf_sim_persona_label">Channel</label>
                            <select class="o_bf_sim_persona_input" t-model="state.sim.channel">
                                <t t-foreach="state.channels" t-as="ch" t-key="ch.code">
                                    <option t-att-value="ch.code" t-esc="ch.name"/>
                                </t>
                            </select>
                            <label class="o_bf_sim_persona_label">Name</label>
                            <input type="text" class="o_bf_sim_persona_input"
                                   t-model="state.sim.personaName"/>
                            <label class="o_bf_sim_persona_label">Mobile</label>
                            <input type="tel" class="o_bf_sim_persona_input"
                                   t-model="state.sim.personaMobile"/>
                            <button class="btn btn-primary mt-3 w-100"
                                    t-on-click="() => this._startSim()">
                                <i class="fa fa-play me-1"/>Start simulation
                            </button>
                        </div>
                    </t>
                    <t t-if="state.sim.started">
                        <div class="o_bf_sim_transcript">
                            <t t-foreach="state.sim.messages" t-as="msg" t-key="msg_index">
                                <div t-attf-class="o_bf_sim_bubble o_bf_sim_bubble_#{msg.direction}">
                                    <pre class="o_bf_sim_bubble_body" t-esc="msg.body"/>
                                </div>
                            </t>
                        </div>
                        <div class="o_bf_sim_input_row" t-if="state.sim.waiting !== 'done'">
                            <input type="text" class="o_bf_sim_input"
                                   t-model="state.sim.userInput"
                                   t-on-keydown="ev => ev.key === 'Enter' &amp;&amp; this._sendSimReply()"/>
                            <button class="btn btn-primary btn-sm ms-1"
                                    t-on-click="() => this._sendSimReply()">Send</button>
                        </div>
                        <div class="o_bf_sim_footer">
                            <button class="btn btn-sm btn-light"
                                    t-on-click="() => this._resetSim()">Reset</button>
                        </div>
                    </t>
                </div>
            </t>

            <t t-if="state.panelMode === 'device'">
                <div class="o_bf_device_sim">
                    <div class="o_bf_device_picker">
                        <t t-foreach="_devices" t-as="dev" t-key="dev.key">
                            <button t-att-class="state.deviceSim.active === dev.key ? 'active' : ''"
                                    t-on-click="() => this._pickDevice(dev.key)"
                                    t-esc="dev.label"/>
                        </t>
                    </div>
                    <div t-attf-class="o_bf_device_shell #{_activeDevice().cssClass}">
                        <t t-if="_activeDevice().key === 'desktop'">
                            <div class="o_bf_browser_bar">
                                <span/><span/><span/>
                            </div>
                        </t>
                        <iframe t-att-src="_deviceEmbedUrl()"
                                title="Web widget preview"/>
                    </div>
                </div>
            </t>
        </div>
    </div>
</div>
`;
