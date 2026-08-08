// On-device PII redaction. Runs before a turn escalates to the cloud, so
// sensitive spans are stripped on the device and never leave it even when the
// request does. This is the JS-native, in-browser counterpart to Microsoft
// Presidio (which is Python and server-side): pattern-based detectors for the
// common high-risk entities, no model download, no network.
//
// Like Presidio, this is best-effort detection, not a guarantee. It covers the
// entities that leak most often; extend RECOGNIZERS for your domain.

export type PiiType = "email" | "phone" | "ssn" | "credit_card" | "ip" | "api_key";

export interface RedactionEntity {
  type: PiiType;
  count: number;
}

export interface RedactionResult {
  redacted: string;
  entities: RedactionEntity[];
  redactedChars: number;   // characters removed = sensitive bytes kept on device
}

interface Recognizer {
  type: PiiType;
  re: RegExp;
  validate?: (m: string) => boolean;
}

const RECOGNIZERS: Recognizer[] = [
  { type: "email", re: /\b[\w.+-]+@[\w-]+\.[\w.-]+\b/g },
  { type: "ssn", re: /\b\d{3}-\d{2}-\d{4}\b/g },
  { type: "credit_card", re: /\b(?:\d[ -]?){13,16}\b/g, validate: luhn },
  { type: "phone", re: /\b(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}\b/g },
  { type: "ip", re: /\b(?:\d{1,3}\.){3}\d{1,3}\b/g },
  { type: "api_key", re: /\b(?:sk|pk|ghp|xox[baprs])[-_][A-Za-z0-9]{16,}\b/g },
];

export function redact(text: string): RedactionResult {
  const counts = new Map<PiiType, number>();
  let redactedChars = 0;
  let out = text;

  // Order matters: run credit_card before phone so a 16-digit card is not
  // partially eaten by the phone pattern.
  for (const r of RECOGNIZERS) {
    out = out.replace(r.re, (m) => {
      if (r.validate && !r.validate(m.replace(/[ -]/g, ""))) return m;
      counts.set(r.type, (counts.get(r.type) ?? 0) + 1);
      redactedChars += m.length;
      return `[${r.type.toUpperCase()}]`;
    });
  }

  const entities = [...counts.entries()].map(([type, count]) => ({ type, count }));
  return { redacted: out, entities, redactedChars };
}

export function hasPii(text: string): boolean {
  return redact(text).entities.length > 0;
}

// Luhn check so random 16-digit strings are not flagged as cards.
function luhn(num: string): boolean {
  if (!/^\d{13,16}$/.test(num)) return false;
  let sum = 0;
  let alt = false;
  for (let i = num.length - 1; i >= 0; i--) {
    let d = num.charCodeAt(i) - 48;
    if (alt) {
      d *= 2;
      if (d > 9) d -= 9;
    }
    sum += d;
    alt = !alt;
  }
  return sum % 10 === 0;
}
