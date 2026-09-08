// Manual Checkin Request Form JS
frappe.ui.form.on("Manual Checkin Request", {

    refresh(frm) {
        if (frm.doc.docstatus === 0) {
            frm.dashboard.add_comment(
                __("This is a draft request. <b>Submit</b> it to create or update the employee check-in."),
                "blue",
                true
            );
        } else if (frm.doc.docstatus === 1) {
            if (frm.doc.applied_checkin) {
                frm.dashboard.add_comment(
                    __("Check-in <b>{0}</b> has been applied to the attendance records.", [frm.doc.applied_checkin]),
                    "green",
                    true
                );
            }
        }
    }

});