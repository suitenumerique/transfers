/**
 * Helper class for string operations.
 */
export class StringHelper {
    /**
     * Lowercase a string and remove accents to ease string comparison for search purposes.
     * Also replaces common ligatures (e.g., œ → oe, æ → ae, ß → ss).
     */
    static normalizeForSearch(str: string) {
        const ligatureMap: Record<string, string> = {
            'œ': 'oe',
            'æ': 'ae',
            'ß': 'ss',
        };
        return str
            .toLowerCase()
            .replace(/[œŒæÆß]/g, match => ligatureMap[match] || match)
            .normalize("NFD").replace(/[̀-ͯ]/g, "");
    }
}

import i18n from "i18next";

const UNIT_KEYS = [
    "unit_byte",
    "unit_kilobyte",
    "unit_megabyte",
    "unit_gigabyte",
    "unit_terabyte",
];

export function formatFileSize(bytes: number): string {
    if (bytes === 0) return `0 ${i18n.t(UNIT_KEYS[0])}`;
    const i = Math.min(
        Math.floor(Math.log(bytes) / Math.log(1024)),
        UNIT_KEYS.length - 1,
    );
    const value = bytes / Math.pow(1024, i);
    const unit = i18n.t(UNIT_KEYS[i]);
    return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${unit}`;
}

export default StringHelper;
