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

export function formatFileSize(bytes: number): string {
    if (bytes === 0) return "0 o";
    const units = ["o", "Ko", "Mo", "Go", "To"];
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    const value = bytes / Math.pow(1024, i);
    return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${units[i]}`;
}

export default StringHelper;
