/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { DateTimeField } from "@web/views/fields/datetime/datetime_field";

patch(DateTimeField.prototype, {
    setup() {
        super.setup();

        // Apply only to the "received_date" field
        if (this.props?.name === "received_date") {
            
            const currentDate = new Date();
           

            // Get the first day of the previous month
            let previousMonth = currentDate.getMonth() - 1;
            let previousYear = currentDate.getFullYear();

            // Handle January (month 0)
            if (previousMonth < 0) {
                previousYear--;
                previousMonth = 11; // December
            }

            // Create minDate correctly
            const minDate = new Date(previousYear, previousMonth, 1).toISOString().split("T")[0];

            const maxDate = currentDate.toISOString().split("T")[0];

            // Update the props to enforce the date range
            this.props.minDate = minDate;
            this.props.maxDate = maxDate;

            // Optional: If you want to force it to always be a range
            // this.props.alwaysRange = true;
        }
    },
});