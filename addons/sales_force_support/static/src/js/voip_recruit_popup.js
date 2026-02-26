/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

console.log("this is voip_recruit_popup");

function hangupAction(env, action) {
    console.log("HANGUP Button Clicked!");

    const voipService = env.services.voip;
    const userAgent = env.services["voip.user_agent"];
    const notification = env.services.notification;
   

    if (!voipService || !userAgent) {
        console.error("VoIP service or user agent not found!");
        notification.add("VoIP Service Not Available", { type: "danger" });
        return;
    }

    if (voipService.softphone.selectedCorrespondence?.call?.isInProgress) {
        userAgent.hangup();
        notification.add("Call Ended Successfully", { type: "warning" });
        // Close the dialer after 5 seconds
         // Close VoIP Dialog Immediately
         setTimeout(() => {
            if (voipService.softphone) {
                voipService.softphone.hide(); // Equivalent to onClickClose()
            }
        }, 5000);

    } else {
        notification.add("No Active Call", { type: "warning" });
    }
}


// Function to handle verification and open the next view
// Function to handle verification and open the next view
// async function verifyAddress(env, action, event) {
//     console.log("VERIFY Address Button Clicked!", action);

//     if (event) {
//         event.stopPropagation();
//         event.preventDefault();
//     }

//     const notification = env.services.notification;

//     try {
//         const activeId = action.context?.active_id;
//         if (!activeId) {
//             throw new Error("Invalid action context: missing active_id");
//         }

//         // Show success message
//         notification.add("Address Verified Successfully", { type: "success" });

//         // Open the form view inside the modal
     

//     } catch (error) {
//         console.error("Verification Error:", error);
//         notification.add("Verification Failed!", { type: "danger" });
//     }
// }


// Register both actions in Odoo
registry.category("actions").add("botle_buhle_custom.hangup_action", hangupAction);
// registry.category("actions").add("botle_buhle_custom.verify_address_action", verifyAddress);

// Attach event listeners for both buttons
document.addEventListener("click", function (event) {
    if (event.target.classList.contains("oe_hang_up")) {
        hangupAction();
    }
    // if (event.target.classList.contains("o_verify")) {
    //     verifyAddress();
    // }
});
