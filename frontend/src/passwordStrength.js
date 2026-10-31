// Client-side password-strength evaluator.
// Scores 0..4 and reports which lab-policy rules pass/fail.
// (Server still enforces the policy — this is UX only.)

const WEAK = new Set([
  'password', 'password1', 'password123', 'qwerty', 'qwerty123',
  '12345678', '123456789', 'letmein', 'welcome', 'admin', 'admin123',
  'root', 'iloveyou', 'monkey', 'dragon', 'passw0rd', 'password1!',
]);

export function evaluate(pw) {
  const checks = {
    length:  pw.length >= 8,
    lower:   /[a-z]/.test(pw),
    upper:   /[A-Z]/.test(pw),
    digit:   /\d/.test(pw),
    special: /[^A-Za-z0-9]/.test(pw),
    notCommon: !WEAK.has(pw.toLowerCase()),
  };

  const passes = checks.length && checks.lower && checks.upper
              && checks.digit && checks.special && checks.notCommon;

  // Score 0..4: base from rule count, bonuses for length/entropy
  let score = [checks.length, checks.lower, checks.upper, checks.digit, checks.special]
    .filter(Boolean).length - 1;        // 0..4
  if (pw.length >= 12) score += 1;
  if (pw.length >= 16) score += 1;
  if (!checks.notCommon) score = 0;
  score = Math.max(0, Math.min(4, score));

  const labels = ['Дуже слабкий', 'Слабкий', 'Середній', 'Сильний', 'Дуже сильний'];
  const colors = ['bg-red-500', 'bg-orange-500', 'bg-yellow-500', 'bg-lime-500', 'bg-green-500'];

  const issues = [];
  if (!checks.length)    issues.push('мінімум 8 символів');
  if (!checks.lower)     issues.push('мала літера');
  if (!checks.upper)     issues.push('велика літера');
  if (!checks.digit)     issues.push('цифра');
  if (!checks.special)   issues.push('спецсимвол');
  if (!checks.notCommon) issues.push('пароль занадто поширений');

  return {
    score,
    label: labels[score],
    color: colors[score],
    passes,
    issues,
    checks,
  };
}
