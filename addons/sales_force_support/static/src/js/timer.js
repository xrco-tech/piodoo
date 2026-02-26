/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { parseFloatTime } from "@web/views/fields/parsers";
import { useInputField } from "@web/views/fields/input_field_hook";
import { useRecordObserver } from "@web/model/relational_model/utils";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component, useState, onWillUpdateProps, onWillStart, onWillDestroy } from "@odoo/owl";

function formatMinutes(value) {
    
    if (value === false) {
        return "";
    }
    const isNegative = value < 0;
    if (isNegative) {
        value = Math.abs(value);
    }
    
    let totalSeconds = Math.floor(value * 3600); // Convert hours to seconds properly
    let hours = Math.floor(totalSeconds / 3600);
    let minutes = Math.floor((totalSeconds % 3600) / 60);
    let seconds = totalSeconds % 60; // Direct remainder ensures correct seconds

    hours = `${hours}`.padStart(2, "0");
    minutes = `${minutes}`.padStart(2, "0");
    seconds = `${seconds}`.padStart(2, "0");

    return `${isNegative ? "-" : ""}${hours}:${minutes}:${seconds}`;
}

export class TimerWidget extends Component {
    static template = "sales_force_support.TimerWidget";
    static props = {
        value: { type: Number },
        ongoing: { type: Boolean, optional: true },
    };
    static defaultProps = { ongoing: false };

    setup() {
        
        this.state = useState({
            duration: this.props.value,
        });
        this.lastDateTime = Date.now();
        this.ongoing = this.props.ongoing;
        onWillStart(() => {
            
            if (this.ongoing) {
                this._runTimer();
                // this._runSleepTimer();
            }
        });
        onWillUpdateProps((nextProps) => {            
            
            const rerun = !this.ongoing && nextProps.ongoing;
            
            this.ongoing = nextProps.ongoing;
            if (rerun) {
                
                this.state.duration = nextProps.value;
                this._runTimer();
                // this._runSleepTimer();
            }
        });
        onWillDestroy(() => clearTimeout(this.timer));
    }

    get durationFormatted() {
        return formatMinutes(this.state.duration);
    }

    _runTimer() {
        
        this.timer = setTimeout(() => {
            if (this.ongoing) {
                this.state.duration += 1 / 3600; // Add one second in minutes
                this._runTimer();
            }
        }, 1000);
    }
    
    //updates the time when the computer wakes from sleep mode
    _runSleepTimer() {
        
        this.timer = setTimeout(async () => {
            const diff = Date.now() - this.lastDateTime - 10000;
            if (diff > 1000) {
                this.state.duration += diff / (1000 * 60);
            }
            this.lastDateTime = Date.now();
            this._runSleepTimer();
        }, 10000);
    }
}

class PayinSheetTimerWidget extends Component {
    static template = "sales_force_support.TimerWidgetField";
    static components = { TimerWidget };
    static props = standardFieldProps;

    setup() {
        this.orm = useService("orm");
        useInputField({
            getValue: () => this.durationFormatted,
            refName: "numpadDecimal",
            parse: (v) => parseFloatTime(v),
        });

        useRecordObserver(async (record) => {
            
            
            this.duration = record.data.capture_time
            // await this.orm.call(
            //     "bb.payin.sheet",
            //     "get_duration",
            //     [this.props.record.resId]
            // );
          
        });

        onWillDestroy(() => clearTimeout(this.timer));
    }

    get durationFormatted() {        
        return formatMinutes(this.duration);
    }

    get ongoing() {
        return this.props.record.data.started;
    }
}

export const PayinSheetTimerField = {
    component: PayinSheetTimerWidget,
    supportedTypes: ["float"],
};

registry.category("fields").add("timesheet_timer", PayinSheetTimerField);
registry.category("formatters").add("timesheet_timer", formatMinutes);
