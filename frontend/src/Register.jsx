import { useEffect, useMemo, useRef, useState } from 'react';
import ReCAPTCHA from 'react-google-recaptcha';
import api from './api';
import { evaluate } from './passwordStrength';

export default function Register({ switchToLogin }) {
  const [form, setForm] = useState({ username: '', email: '', password: '' });
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [busy, setBusy] = useState(false);
  const [captcha, setCaptcha] = useState({ enabled: false, site_key: null });
  const [captchaToken, setCaptchaToken] = useState(null);
  const captchaRef = useRef(null);

  const strength = useMemo(() => evaluate(form.password), [form.password]);

  useEffect(() => {
    api.get('/api/captcha')
      .then((r) => setCaptcha(r.data))
      .catch(() => setCaptcha({ enabled: false, site_key: null }));
  }, []);

  const handleChange = (field) => (e) =>
    setForm((s) => ({ ...s, [field]: e.target.value }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null); setSuccess(null);
    if (!strength.passes) {
      setError('Пароль не відповідає політиці: ' + strength.issues.join(', '));
      return;
    }
    if (captcha.enabled && !captchaToken) {
      setError('Будь ласка, підтвердіть, що ви не робот.');
      return;
    }
    setBusy(true);
    try {
      await api.post('/api/register', { ...form, captcha_token: captchaToken });
      setSuccess(
        'Реєстрація успішна! Ми надіслали посилання для активації на вашу пошту. ' +
        '(У dev-режимі листи доступні у MailHog: http://localhost:8025)'
      );
      setForm({ username: '', email: '', password: '' });
      setCaptchaToken(null);
      captchaRef.current?.reset();
    } catch (err) {
      setError(err?.response?.data?.detail || 'Помилка реєстрації');
      setCaptchaToken(null);
      captchaRef.current?.reset();
    } finally {
      setBusy(false);
    }
  };

  const Rule = ({ ok, children }) => (
    <li className={ok ? 'text-green-600' : 'text-gray-500'}>
      {ok ? '✓' : '•'} {children}
    </li>
  );

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-100">
      <div className="bg-white p-8 rounded-lg shadow-md w-[28rem]">
        <h1 className="text-2xl font-bold mb-6 text-gray-800 text-center">
          Реєстрація
        </h1>

        <form onSubmit={handleSubmit} className="space-y-3">
          <input
            type="text"
            placeholder="Ім'я користувача"
            value={form.username}
            onChange={handleChange('username')}
            className="w-full border px-3 py-2 rounded"
            autoComplete="username"
            required
          />
          <input
            type="email"
            placeholder="Електронна пошта"
            value={form.email}
            onChange={handleChange('email')}
            className="w-full border px-3 py-2 rounded"
            autoComplete="email"
            required
          />
          <input
            type="password"
            placeholder="Пароль"
            value={form.password}
            onChange={handleChange('password')}
            className="w-full border px-3 py-2 rounded"
            autoComplete="new-password"
            required
          />

          {form.password && (
            <div>
              <div className="flex gap-1 mb-2">
                {[0, 1, 2, 3, 4].map((i) => (
                  <div
                    key={i}
                    className={`h-2 flex-1 rounded ${
                      i <= strength.score ? strength.color : 'bg-gray-200'
                    }`}
                  />
                ))}
              </div>
              <p className="text-xs text-gray-600 mb-2">
                Складність: <strong>{strength.label}</strong>
              </p>
              <ul className="text-xs space-y-0.5">
                <Rule ok={strength.checks.length}>мінімум 8 символів</Rule>
                <Rule ok={strength.checks.lower}>мала латинська літера</Rule>
                <Rule ok={strength.checks.upper}>велика латинська літера</Rule>
                <Rule ok={strength.checks.digit}>цифра</Rule>
                <Rule ok={strength.checks.special}>спецсимвол (не літера й не цифра)</Rule>
                <Rule ok={strength.checks.notCommon}>не з переліку поширених паролів</Rule>
              </ul>
            </div>
          )}

          {captcha.enabled && captcha.site_key && (
            <div className="flex justify-center">
              <ReCAPTCHA
                ref={captchaRef}
                sitekey={captcha.site_key}
                onChange={(tok) => setCaptchaToken(tok)}
                onExpired={() => setCaptchaToken(null)}
              />
            </div>
          )}

          <button
            type="submit"
            disabled={busy || !strength.passes || (captcha.enabled && !captchaToken)}
            className="w-full bg-blue-600 text-white py-2 rounded hover:bg-blue-700 disabled:bg-blue-300 transition"
          >
            {busy ? 'Реєстрація…' : 'Зареєструватися'}
          </button>
        </form>

        {error && <div className="text-red-600 text-sm mt-3 text-center">{error}</div>}
        {success && <div className="text-green-600 text-sm mt-3 text-center">{success}</div>}

        <p className="text-sm text-gray-500 mt-6 text-center">
          Вже маєте акаунт?{' '}
          <button
            type="button"
            onClick={switchToLogin}
            className="text-blue-600 hover:underline"
          >
            Увійти
          </button>
        </p>
      </div>
    </div>
  );
}
