import { useState } from 'react';
import api from './api';

/**
 * Enroll / enable / disable TOTP 2FA from the user's profile.
 * Props:
 *   me       — the current user profile (/api/me response)
 *   onChange — called after a successful enable/disable so the parent can
 *              refresh `me` from the server.
 */
export default function Enable2FA({ me, onChange }) {
  const [setup, setSetup] = useState(null);  // { secret, otpauth_url, qr_png_data_url }
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);

  if (!me) return null;

  const startSetup = async () => {
    setMsg(null); setBusy(true);
    try {
      const r = await api.post('/api/2fa/setup');
      setSetup(r.data);
    } catch (err) {
      setMsg(err?.response?.data?.detail || 'Помилка');
    } finally {
      setBusy(false);
    }
  };

  const confirmEnable = async (e) => {
    e.preventDefault();
    setMsg(null); setBusy(true);
    try {
      await api.post('/api/2fa/enable', { code });
      setSetup(null); setCode('');
      setMsg('2FA успішно увімкнено');
      onChange?.();
    } catch (err) {
      setMsg(err?.response?.data?.detail || 'Невірний код');
    } finally {
      setBusy(false);
    }
  };

  const disable = async (e) => {
    e.preventDefault();
    setMsg(null); setBusy(true);
    try {
      await api.post('/api/2fa/disable', { password });
      setPassword('');
      setMsg('2FA вимкнено');
      onChange?.();
    } catch (err) {
      setMsg(err?.response?.data?.detail || 'Помилка');
    } finally {
      setBusy(false);
    }
  };

  // ─── UI ───────────────────────────────────────────────────────────────
  return (
    <div className="bg-white p-4 rounded-lg shadow mb-6">
      <h3 className="font-semibold mb-2">Двофакторна автентифікація (TOTP)</h3>

      {me.is_2fa_enabled ? (
        <>
          <p className="text-sm text-green-600 mb-3">
            2FA увімкнено. При кожному вході ви вводите код з Google Authenticator.
          </p>
          <form onSubmit={disable} className="flex gap-2 items-center">
            <input
              type="password"
              placeholder="Поточний пароль для підтвердження"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="border px-3 py-1 rounded flex-grow text-sm"
              required
            />
            <button
              type="submit"
              disabled={busy}
              className="bg-red-500 text-white px-3 py-1 rounded hover:bg-red-600 disabled:bg-red-300 text-sm"
            >
              Вимкнути 2FA
            </button>
          </form>
        </>
      ) : setup ? (
        <>
          <p className="text-sm text-gray-600 mb-2">
            Відскануйте QR-код у Google Authenticator / Authy, потім введіть
            шестизначний код, щоб підтвердити.
          </p>
          <div className="flex gap-4 items-center mb-3">
            <img src={setup.qr_png_data_url} alt="TOTP QR" className="w-40 h-40" />
            <div className="text-xs text-gray-500 break-all">
              <div className="mb-2"><strong>Secret:</strong> <code>{setup.secret}</code></div>
              <div><strong>URI:</strong> <code>{setup.otpauth_url}</code></div>
            </div>
          </div>
          <form onSubmit={confirmEnable} className="flex gap-2 items-center">
            <input
              type="text"
              inputMode="numeric"
              pattern="\d{6}"
              maxLength={6}
              placeholder="123456"
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
              className="border px-3 py-1 rounded w-28 text-center tracking-widest text-sm"
              required
            />
            <button
              type="submit"
              disabled={busy || code.length !== 6}
              className="bg-blue-600 text-white px-3 py-1 rounded hover:bg-blue-700 disabled:bg-blue-300 text-sm"
            >
              Підтвердити
            </button>
            <button
              type="button"
              onClick={() => setSetup(null)}
              className="text-sm text-gray-500 hover:underline"
            >
              Скасувати
            </button>
          </form>
        </>
      ) : (
        <>
          <p className="text-sm text-gray-500 mb-3">
            2FA вимкнено. Увімкніть, щоб вхід до акаунта вимагав код з мобільного застосунку.
          </p>
          <button
            onClick={startSetup}
            disabled={busy}
            className="bg-blue-600 text-white px-3 py-1 rounded hover:bg-blue-700 disabled:bg-blue-300 text-sm"
          >
            Увімкнути 2FA
          </button>
        </>
      )}

      {msg && <div className="text-sm mt-3 text-gray-700">{msg}</div>}
    </div>
  );
}
