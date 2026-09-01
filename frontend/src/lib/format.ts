// Shared number/currency formatting for the study report and chat cards.

export function formatNumber(n: number | null | undefined, maximumFractionDigits = 1): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return n.toLocaleString(undefined, { maximumFractionDigits })
}

export function formatCurrency(
  n: number | null | undefined,
  currency = 'USD',
  maximumFractionDigits = 0,
): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  try {
    return n.toLocaleString(undefined, {
      style: 'currency',
      currency,
      maximumFractionDigits,
    })
  } catch {
    // Unknown/invalid currency code — fall back to a plain number + code.
    return `${formatNumber(n, maximumFractionDigits)} ${currency}`
  }
}

export function formatPercent(n: number | null | undefined, maximumFractionDigits = 1): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return `${formatNumber(n, maximumFractionDigits)}%`
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' })
}
