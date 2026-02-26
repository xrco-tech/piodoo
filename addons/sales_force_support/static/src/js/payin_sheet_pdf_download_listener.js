// odoo.define('bb_payin.ManageFileDownloads', function (require) {
// "use strict";
//
// /**
//  * The purpose of this file is to add the support of Odoo actions of type
//  * 'ir.actions.act_window' to the Pay-In Report Downloads.
//  */
//
// let ActionManager = require('web.ActionManager');
// let core = require('web.core');
// let rpc = require('web.rpc');
// let framework = require('web.framework');
// let session = require('web.session');
//
// var download = require('web.download');
// var contentdisposition = require('web.contentdisposition');
//
// function get_file(options) {
//     var xhr = new XMLHttpRequest();
//     var data;
//     if (options.form) {
//         xhr.open(options.form.method, options.form.action);
//         data = new FormData(options.form);
//     } else {
//         xhr.open('POST', options.url);
//         data = new FormData();
//         _.each(options.data || {}, function(v, k) {
//             data.append(k, v);
//         });
//     }
//     data.append('token', 'dummy-because-api-expects-one');
//     if (core.csrf_token) {
//         data.append('csrf_token', core.csrf_token);
//     }
//     xhr.responseType = 'blob';
//     xhr.onload = function() {
//         var mimetype = xhr.response.type;
//         if (xhr.status === 200 && mimetype !== 'text/html') {
//             var header = (xhr.getResponseHeader('Content-Disposition') || '').replace(/;$/, '');
//
//
//             var filename = header ? contentdisposition.parse(header).parameters.filename : null;
//
//             if (options.filename) {
//                 filename = options.filename
//             }
//
//             download(xhr.response, filename, mimetype);
//             if (options.success) {
//                 options.success();
//             }
//             return true;
//         }
//         if (!options.error) {
//             return true;
//         }
//         var decoder = new FileReader();
//         decoder.onload = function() {
//             var contents = decoder.result;
//             var err;
//             var doc = new DOMParser().parseFromString(contents, 'text/html');
//             var nodes = doc.body.children.length === 0 ? doc.body.childNodes : doc.body.children;
//             try {
//                 var node = nodes[1] || nodes[0];
//                 err = JSON.parse(node.textContent);
//             } catch (e) {
//                 err = {
//                     message: nodes.length > 1 ? nodes[1].textContent : '',
//                     data: {
//                         name: String(xhr.status),
//                         title: nodes.length > 0 ? nodes[0].textContent : '',
//                     }
//                 };
//             }
//             options.error(err);
//         }
//         ;
//         decoder.readAsText(xhr.response);
//     }
//     ;
//     xhr.onerror = function() {
//         if (options.error) {
//             options.error({
//                 message: _t("Something happened while trying to contact the server, check that the server is online and that you still have a working network connection."),
//                 data: {
//                     title: _t("Could not connect to the server")
//                 }
//             });
//         }
//     }
//     ;
//     if (options.complete) {
//         xhr.onloadend = function() {
//             options.complete();
//         }
//         ;
//     }
//     xhr.send(data);
//     return true;
// }
//
// ActionManager.include({
//     custom_events: _.extend({}, ActionManager.prototype.custom_events, {
//         execute_action: '_onExecuteAction',
//         switch_view: '_onSwitchView',
//     }),
//
//     /**
//      * Downloads a PDF report for the given url. It blocks the UI during the
//      * report generation and download.
//      *
//      * @param {Array} url_list
//      * @param {string} type
//      * @returns {Promise} resolved when the report has been downloaded ;
//      *   rejected if something went wrong during the report generation
//      */
// _downloadReport: function (urlList, type) {
//     let self = this;
//     let batchSize = 10;
//
//     framework.blockUI();
//     return new Promise(function (resolve, reject) {
//         let index = 0;
//
//         function printBatch() {
//             let batchUrls = urlList.slice(index, index + batchSize);
//             let promises = batchUrls.map(function (urlObj) {
//                 let filename = urlObj['filename'];
//                 let url_ = urlObj[type];
//                 let type_ = 'qweb-' + type;
//                 return new Promise(function (resolve, reject) {
//                     let blocked = !get_file({
//                         url: '/report/download',
//                         data: {
//                             data: JSON.stringify([url_, type_,]),
//                             context: JSON.stringify(session.user_context),
//                         },
//                         filename: filename,
//                         success: resolve,
//                         error: (error) => {
//                             self.call('crash_manager', 'rpc_error', error);
//                             reject();
//                         },
//                         complete: framework.unblockUI,
//                     });
//                     if (blocked) {
//                         let message = _t('A popup window with your report was blocked. You ' +
//                             'may need to change your browser settings to allow ' +
//                             'popup windows for this page.');
//                         self.do_warn(_t('Warning'), message, true);
//                     }
//                 });
//             });
//
//             Promise.allSettled(promises)
//                 .then(function () {
//                     index += batchSize;
//                     if (index < urlList.length) {
//                         // pause for 20 seconds before printing the next batch
//                         setTimeout(printBatch, 15000);
//                     } else {
//                         resolve();
//                     }
//                 })
//                 .catch(reject);
//
//         }
//         printBatch();
//     });
// },
//
//     /**
//      * Add: split reports into individual files for each active (selected) record ID
//      *
//      * @private
//      * @param {Object} action the description of the action to execute
//      * @param {Object} options @see doAction for details
//      * @returns {Promise} resolved when the action has been executed
//      */
//     _triggerDownload: function (action, options, type){
//         let self = this;
//
//         const active_ids = action.context.active_ids
//         let list_size = active_ids.length;
//
//         let reportUrlsList = []
//
//         if(action.xml_id === "bb_payin.action_report_new_payin_sheets_by_distribution"){
//             return self._rpc({
//             model: 'bb.payin.sheet',
//             method: 'read',
//             args: [active_ids, ['period', 'distributor_id']],
//             }).then(function(data) {
//
//                 const grouped_data = {};
//
//                 data.forEach(item => {
//                     const distributor_id = item.distributor_id[0];
//                     if (!grouped_data[distributor_id]) {
//                         grouped_data[distributor_id] = [];
//                     }
//                     grouped_data[distributor_id].push(item);
//                 });
//
//                 // Convert the grouped data object into an array of groups
//                 const result = Object.values(grouped_data);
//
//                 const chunkSize = 20; // Change this to the desired chunk size
//                     const chunkedArray = [];
//                     for (let i = 0; i < result[0].length; i += chunkSize) {
//                       const chunk = result[0].slice(i, i + chunkSize);
//                       chunkedArray.push(chunk);
//                     }
//
//                 for (let i = 0; i < chunkedArray.length; i++) {
// //                    console.log("result["+i+"]= " + JSON.stringify(chunkedArray[i]))
//                     let distribution_report_name = chunkedArray[i][0]['period'].replace(/\./g, "_") + " - " + chunkedArray[i][0]['distributor_id'][1].replace(/\./g, "_") + " - Pay-In Sheets Forms - Part-" + i;
//
//
//                     const id_list = chunkedArray[i].map(item => item.id);
//
//                     let action_copy = JSON.parse(JSON.stringify(action));
//                     action_copy["name"] = action.display_name;
//                     action_copy["display_name"] = action.display_name;
//                     action_copy["context"]["active_id"] = id_list[0];
//                     action_copy["context"]["active_ids"] = id_list;
//
//                     let reportUrls = self._makeReportUrls(action_copy);
//                     reportUrls['filename'] = distribution_report_name;
//
//                     action_copy["context"]["active_ids"] = id_list;
//                     reportUrlsList.push(reportUrls);
//                 }
//
//                 return self._downloadReport(reportUrlsList, type).then(function () {
//                     if (action.close_on_report_download) {
//                         let closeAction = { type: 'ir.actions.act_window_close' };
//                         return self.doAction(closeAction, _.pick(options, 'on_close'));
//                     } else {
//                         return options.on_close();
//                     }
//                 });
//             });
//         }
//
//         const payin_reports_whitelist = [
//             "bb_payin.report_new_payin_sheets",
//             "bb_payin.report_blank_payin_sheets",
//             "bb_payin.report_captured_payin_sheets",
//             "bb_payin.report_new_distributor",
//             "bb_payin.report_new_distributor_blank",
//             "bb_payin.report_new_distributor_captured"
//         ]
//
//         if (payin_reports_whitelist.includes(action.report_name)){
//             for (let i = 0; i < list_size; i++) {
//                 let report_name = action.display_name;
//
//                 let action_copy = JSON.parse(JSON.stringify(action));
//                 action_copy["name"] = report_name;
//                 action_copy["display_name"] = report_name;
//                 action_copy["context"]["active_id"] = active_ids[i];
//                 action_copy["context"]["active_ids"] = [active_ids[i]];
//
//                 let reportUrls = this._makeReportUrls(action_copy);
//                 reportUrlsList.push(reportUrls);
//             }
//         }
//         else{
//             let reportUrls = this._makeReportUrls(action);
//             reportUrlsList.push(reportUrls);
//         }
//
//         return this._downloadReport(reportUrlsList, type).then(function () {
//             if (action.close_on_report_download) {
//                 let closeAction = { type: 'ir.actions.act_window_close' };
//                 return self.doAction(closeAction, _.pick(options, 'on_close'));
//             } else {
//                 return options.on_close();
//             }
//         }
//
//         );
//     },
//
// })
// })
