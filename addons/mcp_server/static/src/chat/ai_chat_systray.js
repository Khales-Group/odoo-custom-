/** @odoo-module **/

import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, onWillStart } from "@odoo/owl";

export class AiChatSystray extends Component {
    static template = "mcp_server.AiChatSystray";
    static props = {};

    setup() {
        this.action = useService("action");
        this.state = useState({ hasAccess: false });

        onWillStart(async () => {
            try {
                this.state.hasAccess = await user.hasGroup(
                    "mcp_server.group_mcp_user"
                );
            } catch (error) {
                this.state.hasAccess = false;
            }
        });
    }

    openChat() {
        this.action.doAction({
            type: "ir.actions.client",
            tag: "mcp_server.ai_chat_action",
            name: "Claude",
            target: "current",
        });
    }
}

registry.category("systray").add(
    "mcp_server.AiChatSystray",
    { Component: AiChatSystray },
    { sequence: 1 }
);
