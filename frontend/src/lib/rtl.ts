// Mirrors app/tools/language.py's RTL_LANGUAGE_CODES / is_rtl — kept in sync by
// hand since the frontend has no access to backend constants at build time.
const RTL_LANGUAGE_CODES = new Set(['ar', 'he', 'fa', 'ur'])

export function isRtlLanguage(languageCode: string | null | undefined): boolean {
  if (!languageCode) return false
  const base = languageCode.split('-')[0].toLowerCase()
  return RTL_LANGUAGE_CODES.has(base)
}
