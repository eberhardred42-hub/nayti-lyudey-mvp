const SENSITIVE_KEYS = new Set([
  "authorization",
  "auth",
  "token",
  "access_token",
  "refresh_token",
  "admin_token",
  "user_token",
  "password",
  "otp",
  "otp_code",
  "code",
  "secret",
]);

function maskEmail(s: string): string {
  const at = s.indexOf("@");
  if (at <= 1) return "[redacted-email]";
  const name = s.slice(0, at);
  const domain = s.slice(at + 1);
  const maskedName = name[0] + "***";
  const dot = domain.lastIndexOf(".");
  const maskedDomain = dot > 0 ? domain.slice(0, 1) + "***" + domain.slice(dot) : domain.slice(0, 1) + "***";
  return `${maskedName}@${maskedDomain}`;
}

function maskPhoneLike(s: string): string {
  const digits = s.replace(/\D/g, "");
  if (digits.length < 10) return s;
  const tail = digits.slice(-2);
  return `[redacted-phone-**${tail}]`;
}

function looksLikeEmail(s: string): boolean {
  return /[^\s@]+@[^\s@]+\.[^\s@]+/.test(s);
}

function looksLikeBearer(s: string): boolean {
  return /^bearer\s+\S+/i.test(s);
}

function looksLikeTokenish(s: string): boolean {
  // Heuristic: long base64/jwt-ish strings
  if (s.length < 24) return false;
  if (s.includes(".")) {
    const parts = s.split(".");
    if (parts.length >= 3 && parts.every((p) => p.length >= 8)) return true;
  }
  return /^[A-Za-z0-9_\-+=/]+$/.test(s);
}

function maskStringValue(s: string): string {
  if (!s) return s;
  if (looksLikeBearer(s)) return "Bearer [redacted]";
  if (looksLikeEmail(s)) return maskEmail(s);
  const phoneMasked = maskPhoneLike(s);
  if (phoneMasked !== s) return phoneMasked;
  if (looksLikeTokenish(s)) return "[redacted-token]";
  return s;
}

export function maskSensitive(value: unknown, parentKey?: string): unknown {
  if (value === null || value === undefined) return value;

  if (typeof value === "string") {
    if (parentKey && SENSITIVE_KEYS.has(parentKey.toLowerCase())) return "[redacted]";
    return maskStringValue(value);
  }

  if (typeof value === "number" || typeof value === "boolean") return value;

  if (Array.isArray(value)) return value.map((v) => maskSensitive(v, parentKey));

  if (typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      if (SENSITIVE_KEYS.has(k.toLowerCase())) {
        out[k] = "[redacted]";
      } else {
        out[k] = maskSensitive(v, k);
      }
    }
    return out;
  }

  return value;
}
