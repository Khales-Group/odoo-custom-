import { Component, useEffect, useRef, useState } from "@odoo/owl";
import { AutoComplete } from "@web/core/autocomplete/autocomplete";
import { deserializeDate, serializeDate } from "@web/core/l10n/dates";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { getFieldDomain } from "@web/model/relational_model/utils";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

const NUMERIC_TYPES = ["integer", "float", "monetary"];
const AVATAR_MODELS = ["res.users", "res.partner"];

/**
 * Reads a number the way people actually type it on a card: "2,000,000 AED",
 * "1.250.000" (dots as thousand separators), Arabic digits... Same rules as
 * _kh_safe_float on the Python side of kh_projects_dashboard.
 *
 * @returns {number|null} null when nothing sensible can be read
 */
export function parseLooseNumber(text) {
    let value = String(text ?? "")
        .replace(/[\u0660-\u0669]/g, (d) => String(d.charCodeAt(0) - 0x0660))
        .replace(/[\u06f0-\u06f9]/g, (d) => String(d.charCodeAt(0) - 0x06f0))
        .replace(/\u066b/g, ".")
        .replace(/\u066c/g, ",")
        .replace(/[^0-9.,-]/g, "");
    if ((value.match(/\./g) || []).length > 1) {
        value = value.replace(/\./g, "");
    }
    value = value.replace(/,/g, "");
    if (!value) {
        // An emptied box means 0; letters with no digits at all are a typo.
        return String(text ?? "").trim() ? null : 0;
    }
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
}

// Always plain "1,234.56" (never the user's locale separators or a currency
// symbol): whatever is shown in the box has to read back through
// parseLooseNumber unchanged when the user edits it.
function formatPlainNumber(value, type) {
    if (value === false || value === null || value === undefined) {
        return "";
    }
    const digits = type === "integer" ? 0 : 2;
    return Number(value).toLocaleString("en-US", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
    });
}

/**
 * Saves a change straight from a Kanban card (no form, no Save button).
 * If the field is the one the Kanban is grouped by, the whole view is
 * reloaded so the card moves to its new column right away.
 */
async function saveFromCard(component, changes) {
    const { record, name } = component.props;
    await record.update(changes, { save: true });
    const groupBy = record.model.root.groupBy || [];
    if (groupBy.some((spec) => spec.split(":")[0] === name)) {
        await record.model.root.load();
    }
}

export class KhInlineField extends Component {
    static template = "kh_inline_edit.InlineField";
    static components = { AutoComplete };
    static props = {
        ...standardFieldProps,
        placeholder: { type: String, optional: true },
        required: { type: Boolean, optional: true },
        multiline: { type: Boolean, optional: true },
        context: { type: Object, optional: true },
        domain: { type: [Array, Function], optional: true },
    };

    setup() {
        this.orm = useService("orm");
        // Bumped to rebuild the many2one search box, which puts the current
        // value back after the user typed something without picking a result.
        this.state = useState({ autocompleteKey: 0 });
        // What the user is typing in a text/number box. Kept outside the
        // record so an unrelated save on the same card (which re-renders it)
        // doesn't wipe it mid-typing.
        this.draft = null;
        this.textareaRef = useRef("textarea");
        useEffect(() => this.fitTextarea());
    }

    get field() {
        return this.props.record.fields[this.props.name];
    }

    get type() {
        return this.field.type;
    }

    get value() {
        return this.props.record.data[this.props.name];
    }

    get isNumeric() {
        return NUMERIC_TYPES.includes(this.type);
    }

    get placeholder() {
        return this.props.placeholder || this.field.string;
    }

    get formattedValue() {
        const formatter = registry.category("formatters").get(this.type, String);
        return formatter(this.value, { field: this.field, data: this.props.record.data });
    }

    // ---- text / number -------------------------------------------------

    // Long titles wrap onto several lines (and the box grows with them)
    // instead of being cut off with "...".
    get isMultiline() {
        return this.type === "text" || (this.type === "char" && Boolean(this.props.multiline));
    }

    fitTextarea() {
        const el = this.textareaRef.el;
        if (!el) {
            return;
        }
        el.style.height = "auto";
        // 0 while the card isn't laid out yet (e.g. folded column) - keep
        // the one-line default rather than collapsing the box.
        if (el.scrollHeight) {
            el.style.height = `${el.scrollHeight + el.offsetHeight - el.clientHeight}px`;
        }
    }

    get textValue() {
        if (this.draft !== null) {
            return this.draft;
        }
        if (this.isNumeric) {
            return formatPlainNumber(this.value, this.type);
        }
        return this.value || "";
    }

    onTextFocus(ev) {
        this.draft = ev.target.value;
        if (this.isNumeric) {
            ev.target.select();
        }
    }

    onTextInput(ev) {
        this.draft = ev.target.value;
        this.fitTextarea();
    }

    onTextBlur() {
        this.draft = null;
    }

    onTextKeydown(ev) {
        // Enter saves; only real multi-line text fields keep Enter for a new
        // line (Ctrl+Enter saves those).
        if (ev.key === "Enter" && (this.type !== "text" || ev.ctrlKey)) {
            ev.preventDefault();
            ev.target.blur();
        } else if (ev.key === "Escape") {
            this.draft = null;
            ev.target.value = this.textValue;
            ev.target.blur();
        }
    }

    async onTextChange(ev) {
        const input = ev.target;
        this.draft = null;
        let newValue;
        if (this.isNumeric) {
            newValue = parseLooseNumber(input.value);
            if (newValue === null) {
                input.value = this.textValue;
                return;
            }
            if (this.type === "integer") {
                newValue = Math.round(newValue);
            }
            input.value = formatPlainNumber(newValue, this.type);
            if (newValue === (this.value || 0)) {
                return;
            }
        } else {
            newValue = input.value.trim() || false;
            if (!newValue && this.props.required) {
                input.value = this.textValue;
                return;
            }
            if (newValue === (this.value || false)) {
                return;
            }
        }
        await saveFromCard(this, { [this.props.name]: newValue });
    }

    // ---- selection -----------------------------------------------------

    get selectionOptions() {
        return this.field.selection.filter(([, label]) => label !== "");
    }

    async onSelectChange(ev) {
        const raw = ev.target.value;
        const option = this.selectionOptions.find(([key]) => String(key) === raw);
        const newValue = option ? option[0] : false;
        if (newValue === this.value) {
            return;
        }
        await saveFromCard(this, { [this.props.name]: newValue });
    }

    // ---- date / datetime -----------------------------------------------

    get dateInputValue() {
        if (!this.value) {
            return "";
        }
        return this.type === "date"
            ? serializeDate(this.value)
            : this.value.toFormat("yyyy-MM-dd'T'HH:mm");
    }

    async onDateChange(ev) {
        const raw = ev.target.value;
        let newValue = false;
        if (raw) {
            newValue = this.type === "date" ? deserializeDate(raw) : luxon.DateTime.fromISO(raw);
            if (!newValue.isValid) {
                ev.target.value = this.dateInputValue;
                return;
            }
        } else if (this.props.required) {
            ev.target.value = this.dateInputValue;
            return;
        }
        await saveFromCard(this, { [this.props.name]: newValue });
    }

    // ---- boolean -------------------------------------------------------

    async onCheckboxChange(ev) {
        await saveFromCard(this, { [this.props.name]: ev.target.checked });
    }

    // ---- many2one ------------------------------------------------------

    get many2oneName() {
        return this.value ? this.value.display_name || "" : "";
    }

    get avatarUrl() {
        const { relation } = this.field;
        if (this.value && AVATAR_MODELS.includes(relation)) {
            return `/web/image/${relation}/${this.value.id}/avatar_128`;
        }
        return false;
    }

    get autocompleteSources() {
        return [
            {
                placeholder: _t("Loading..."),
                options: (request) => this.searchRecords(request),
            },
        ];
    }

    async searchRecords(request) {
        const records = await this.orm.call(this.field.relation, "web_name_search", [], {
            name: request,
            operator: "ilike",
            domain: getFieldDomain(this.props.record, this.props.name, this.props.domain),
            // Short lists (sources, owners, companies) fit entirely, so
            // nothing is hidden behind typing; long ones scroll.
            limit: 20,
            context: this.props.context || {},
            specification: { display_name: {} },
        });
        if (!records.length) {
            return [{ label: _t("No results") }];
        }
        return records.map((rec) => ({
            label: rec.display_name,
            onSelect: () => this.selectRecord(rec),
        }));
    }

    async selectRecord(rec) {
        if (this.value && this.value.id === rec.id) {
            return;
        }
        await saveFromCard(this, {
            [this.props.name]: { id: rec.id, display_name: rec.display_name },
        });
    }

    async onAutocompleteChange({ inputValue, isOptionSelected }) {
        if (isOptionSelected) {
            return;
        }
        const text = inputValue.trim();
        if (!text && this.value && !this.props.required) {
            await saveFromCard(this, { [this.props.name]: false });
        } else if (text !== this.many2oneName) {
            // Typed without picking a result - show the real value again.
            this.state.autocompleteKey++;
        }
    }
}

export const khInlineField = {
    component: KhInlineField,
    displayName: _t("Editable on card"),
    supportedTypes: [
        "char",
        "text",
        "integer",
        "float",
        "monetary",
        "selection",
        "many2one",
        "date",
        "datetime",
        "boolean",
    ],
    supportedOptions: [
        {
            label: _t("Wrap long text"),
            name: "multiline",
            type: "boolean",
        },
    ],
    extractProps({ attrs, options }, dynamicInfo) {
        return {
            placeholder: attrs.placeholder,
            multiline: Boolean(options.multiline),
            // Only the field's own readonly rule counts here, not the
            // "Kanban is read-only" one - that's the whole point.
            readonly: dynamicInfo.readonly,
            required: dynamicInfo.required,
            context: dynamicInfo.context,
            domain: dynamicInfo.domain,
        };
    },
};

registry.category("fields").add("kh_inline", khInlineField);

export class KhStatusDot extends Component {
    static template = "kh_inline_edit.StatusDot";
    static props = { ...standardFieldProps };

    get options() {
        return this.props.record.fields[this.props.name].selection;
    }

    get value() {
        return this.props.record.data[this.props.name];
    }

    get label() {
        const option = this.options.find(([key]) => key === this.value);
        return option ? option[1] : "";
    }

    async onChange(ev) {
        const option = this.options.find(([key]) => String(key) === ev.target.value);
        if (!option || option[0] === this.value) {
            return;
        }
        await saveFromCard(this, { [this.props.name]: option[0] });
    }
}

export const khStatusDot = {
    component: KhStatusDot,
    displayName: _t("Status dot (editable on card)"),
    supportedTypes: ["selection"],
    extractProps(fieldInfo, dynamicInfo) {
        return { readonly: dynamicInfo.readonly };
    },
};

registry.category("fields").add("kh_status_dot", khStatusDot);
