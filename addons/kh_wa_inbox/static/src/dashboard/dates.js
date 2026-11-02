/** @odoo-module **/

// The dashboard always reads in Arabic, in Dubai time, with Latin digits -
// whatever the user's Odoo language is.
export const ZONE = "Asia/Dubai";

function arabic(dt) {
    return dt.reconfigure({ locale: "ar", numberingSystem: "latn" });
}

/** "2026-11-02 06:45:00" (UTC, as Odoo sends date-times) -> luxon in Dubai. */
export function fromUtc(value) {
    return value ? arabic(luxon.DateTime.fromSQL(value, { zone: "utc" }).setZone(ZONE)) : null;
}

/** "2026-11-02" -> luxon date in Dubai. */
export function fromDay(value) {
    return value ? arabic(luxon.DateTime.fromISO(value, { zone: ZONE })) : null;
}

export function dubaiToday() {
    return luxon.DateTime.now().setZone(ZONE).toISODate();
}

/** الأحد 2 نوفمبر، 10:45 */
export function formatDateTime(value) {
    const dt = fromUtc(value);
    return dt ? dt.toFormat("cccc d LLLL، HH:mm") : "";
}

export function formatTime(value) {
    const dt = fromUtc(value);
    return dt ? dt.toFormat("HH:mm") : "";
}

/** الأحد 2 نوفمبر */
export function formatDay(value) {
    const dt = fromDay(value);
    return dt ? dt.toFormat("cccc d LLLL") : "";
}

/** الأحد 2 نوفمبر 2026 */
export function formatLongDay(value) {
    const dt = fromDay(value);
    return dt ? dt.toFormat("cccc d LLLL yyyy") : "";
}

/** "اليوم 10:45", "أمس 10:45", or the full date and time. */
export function formatMoment(value) {
    const dt = fromUtc(value);
    if (!dt) {
        return "";
    }
    const today = luxon.DateTime.now().setZone(ZONE).startOf("day");
    const day = dt.startOf("day");
    if (+day === +today) {
        return `اليوم ${dt.toFormat("HH:mm")}`;
    }
    if (+day === +today.minus({ days: 1 })) {
        return `أمس ${dt.toFormat("HH:mm")}`;
    }
    return dt.toFormat("cccc d LLLL، HH:mm");
}
