odoo.define('kh_approvals.dashboard', function (require) {
    "use strict";

    var AbstractAction = require('web.AbstractAction');
    var core = require('web.core');
    var rpc = require('web.rpc');

    var ApprovalDashboard = AbstractAction.extend({
        template: 'kh_approvals.dashboard_template',

        init: function (parent, context) {
            this._super(parent, context);
            this.rules = [];
        },

        willStart: function () {
            var self = this;
            return this._super().then(function () {
                return rpc.query({
                    route: '/kh_approvals/dashboard',
                }).then(function (data) {
                    self.rules = data;
                });
            });
        },

        start: function () {
            var self = this;
            return this._super().then(function () {
                self.$el.html(core.qweb.render('kh_approvals.dashboard_template', {
                    widget: self,
                    rules: self.rules
                }));
            });
        },
    });

    core.action_registry.add('kh_approvals.dashboard', ApprovalDashboard);

    return ApprovalDashboard;
});