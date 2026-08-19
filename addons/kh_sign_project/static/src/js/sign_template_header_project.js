import { patch } from "@web/core/utils/patch";
import { SignTemplateHeaderTags } from "@sign/backend_components/sign_template/sign_template_header_tags";
import { Many2OneField } from "@web/views/fields/many2one/many2one_field";

Object.assign(SignTemplateHeaderTags.components, { Many2OneField });

patch(SignTemplateHeaderTags.prototype, {
    setup() {
        super.setup();
        this.signTemplateFieldsGet = {
            ...this.signTemplateFieldsGet,
            project_id: {
                related: {
                    activeFields: { display_name: { type: "char" } },
                    fields: { display_name: { name: "display_name", type: "char" } },
                },
            },
        };
    },

    getMany2OneProps(record, fieldName) {
        return {
            name: fieldName,
            id: fieldName,
            record,
            readonly: this.props.hasSignRequests,
        };
    },
});
