/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { Many2ManyTagsField } from "@web/views/fields/many2many_tags/many2many_tags_field";
import { useX2ManyCrud } from "@web/views/fields/relational_utils";

class SafeMany2ManyTagsField extends Many2ManyTagsField {
    static props = {
        ...Many2ManyTagsField.props,
        onUpdate: { type: Function, optional: true },
        style: { type: [String, Object], optional: true },
    };

    setup() {
        super.setup();
        
        const { saveRecord: originalSaveRecord } = useX2ManyCrud(
            () => this.props.record.data[this.props.name],
            true
        );
        
        this.saveRecord = async (recordlist) => {
            if (!recordlist) return;
            
            const records = Array.isArray(recordlist) ? recordlist : [recordlist];
            const processedRecords = records.map(record => {
                const recordData = record || {};
                return {
                    id: record.id,
                    resId: record.id,
                    data: {
                        display_name: recordData.display_name || recordData.name || '',
                        name: recordData.display_name || '',
                        work_phone: recordData.work_phone || false,
                        identification_id: recordData.identification_id || false
                    }
                };
            });

            try {
                const result = await originalSaveRecord(processedRecords);
                const storedRecords = this.props.record.data[this.props.name]?.records || [];
                const currentIds = this.props.record.data[this.props.name]?.currentIds || [];
                
                if (this.props.onUpdate) {
                    this.props.onUpdate({
                        detail: {
                            records: storedRecords,
                            currentIds: currentIds
                        }
                    });
                }
                
                return result;
            } catch (error) {
                console.error("Error saving records:", error);
                throw error;
            }
        };
        
        this.update = this.saveRecord;
    }
}

class PayinSheetReportJS extends Component {
    static template = "payin_sheet_report_template";
    static components = { Many2ManyTagsField: SafeMany2ManyTagsField };

    setup() {
        this.orm = useService("orm");
        this.rpc = useService("rpc");
        this.actionService = useService("action");

        const self = this;

        this.state = useState({
            loading: false,
            employees: [],
            selectedEmployee: [],
            report_data: [],
            showTable: false,
            dummyRecord: {
                data: {
                    employee_ids: {
                        records: [],
                        currentIds: [],
                        fields: {
                            display_name: { string: "Name", type: "char" },
                            work_phone: { string: "Phone", type: "char" },
                            identification_id: { string: "ID Member", type: "char" }
                        },
                        model: "hr.employee",
                        get(resId) { 
                            const record = this.records.find(r => r.resId === resId);
                            return record ? {
                                ...record,
                                data: {
                                    ...record.data,
                                    identification_id: record.data.identification_id || false
                                }
                            } : null;
                        },
                        forget: async function(record) {
                            const removeId = record.resId || record.id;
                            this.records = (this.records || []).filter(r => r.resId !== removeId);
                            this.currentIds = (this.currentIds || []).filter(id => id !== removeId);
                            try {
                                await self.loadData();
                            } catch (error) {
                                console.error("Error in loadData after forget:", error);
                            }
                        },
                        add: async function(records) {
                            if (!Array.isArray(this.records)) this.records = [];
                            if (!Array.isArray(this.currentIds)) this.currentIds = [];
                            
                            const recordsToAdd = Array.isArray(records) ? records : [records];
                            for (const record of recordsToAdd) {
                                const recordData = record.add || {};
                                this.records.push({
                                    id: recordData[0].id,
                                    resId: recordData[0].resId,
                                    data: {
                                        display_name: recordData[0].data.display_name || recordData[0].data.name || '',
                                        name: recordData[0].data.name || '',
                                        work_phone: recordData.work_phone || false,
                                        identification_id: recordData.identification_id || false
                                    }
                                });
                                this.currentIds.push(recordData[0].id);
                            }
                        },
                        remove: async function(records) {
                            const recordsToRemove = Array.isArray(records) ? records : [records];
                            const removeIds = recordsToRemove.map(r => r.resId || r.id);
                            this.records = (this.records || []).filter(r => !removeIds.includes(r.resId));
                            this.currentIds = (this.currentIds || []).filter(id => !removeIds.includes(id));
                        },
                        addAndRemove: async function(recordsToAdd, recordsToRemove) {
                            const addRecords = recordsToAdd ? (Array.isArray(recordsToAdd) ? recordsToAdd : [recordsToAdd]) : [];
                            const removeRecords = recordsToRemove ? (Array.isArray(recordsToRemove) ? recordsToRemove : [recordsToRemove]) : [];
                            
                            if (!Array.isArray(this.records)) this.records = [];
                            if (!Array.isArray(this.currentIds)) this.currentIds = [];
                            
                            try {
                                if (addRecords.length) await this.add.call(this, addRecords);
                                if (removeRecords.length) await this.remove.call(this, removeRecords);
                            } catch (error) {
                                console.error("Error in addAndRemove:", error);
                                throw error;
                            }
                        }
                    },
                },
                fields: {
                    employee_ids: {
                        relation: "hr.employee",
                        type: "many2many",
                        string: "Members",
                    },
                },
                evalContext: {},
                isInEdition: true,
                save: async () => {},
                update: async () => {},
            },
        });

        this.toggleTable = () => {
            this.state.showTable = !this.state.showTable;
        };

        onWillStart(async () => {
            await this.loadEmployees();
        });
    }

    async loadEmployees() {
        try {
            this.state.loading = true;
            const employees = await this.orm.searchRead(
                "hr.employee", 
                [], 
                ["id", "name", "work_phone", "identification_id", "display_name"]
            );
            
            const selectedIds = this.state.dummyRecord.data.employee_ids.currentIds || [];
            this.state.employees = employees
                .filter(emp => !selectedIds.includes(emp.id))
                .map(emp => ({
                    ...emp,
                    display_name: emp.display_name || emp.name,
                    identification_id: emp.identification_id || false
                }));
        } catch (error) {
            console.error("Error loading employees:", error);
            this.state.employees = [];
        } finally {
            this.state.loading = false;
        }
    }

    onEmployeeChange = (event) => {
        const currentIds = [...this.state.dummyRecord.data.employee_ids.currentIds];
        const records = this.state.dummyRecord.data.employee_ids.records.map(r => ({
            id: r.id,
            name: r.data.name,
            display_name: r.data.display_name,
            identification_id: r.data.identification_id
        }));
        
        this.state.employees = this.state.employees.filter(emp => 
            !currentIds.includes(emp.id)
        );
        
        this.state.selectedEmployee = this.state.employees.filter(emp => 
            currentIds.includes(emp.id)
        ).map(emp => ({
            ...emp,
            identification_id: emp.identification_id || 'No data available'
        }));

        this.loadData();
    }

    async loadData() {        
        try {
            this.state.loading = true;
            const employeeIDs = this.state.dummyRecord.data.employee_ids.records.map(emp => emp.id);
            
            const data = await this.rpc("/web/dataset/call_kw/bb.payin.sheets.enquiry.report/get_payin_sheet_sql", {
                model: "bb.payin.sheets.enquiry.report",
                method: "get_payin_sheet_sql",
                args: [{ partner_code: employeeIDs }],
                kwargs: {},
            });
            
            this.state.report_data = Array.isArray(data) ? 
                data.map(item => ({
                    ...item,
                    identification_id: item.identification_id || 'No data available'
                })) : 
                [];
        } catch (error) {
            console.error("Error loading report data:", error);
            this.state.report_data = [];
        } finally {
            this.state.loading = false;
        }
    }

    triggerOpenPayinSheet = (event) => {
        const payinSheetId = event.target.closest("[data-id]")?.dataset.id;
        if (!payinSheetId) return;

        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Payin Sheet Details",
            res_model: "bb.payin.sheet",
            view_mode: "form",
            res_id: parseInt(payinSheetId, 10),
            target: "current",
            views: [[false, "form"]],
        }).catch(console.error);
    };
}

registry.category("actions").add("payin_sheet_report", PayinSheetReportJS);