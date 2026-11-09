import { useState } from 'react';
import api from './api';

/**
 * Beszel-style "Add System" modal.
 *
 * Flow:
 *   1. User fills Name / Host-IP / Port.
 *   2. We POST /api/hosts — backend creates the host, returns a fresh
 *      api_token + a generated ssh-ed25519-looking public key + a
 *      ready-to-paste docker-compose.yml.
 *   3. We display the result and a "Copy docker-compose" button.
 *
 * NOTE: The Public Key and the "Port" are shown for UX parity with
 * typical real-world agent install modals. Our architecture is Push
 * (agent → backend over HTTP), so neither is actually used for auth.
 */
export default function AddSystemModal({ open, onClose, onCreated }) {
  const [name, setName] = useState('');
  const [host, setHost] = useState('');
  const [port, setPort] = useState(45876);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [created, setCreated] = useState(null); // response from backend
  const [copied, setCopied] = useState(false);

  if (!open) return null;

  const reset = () => {
    setName(''); setHost(''); setPort(45876);
    setCreated(null); setError(null); setCopied(false);
  };

  const close = () => { reset(); onClose?.(); };

  const submit = async (e) => {
    e.preventDefault();
    setError(null); setBusy(true);
    try {
      const r = await api.post('/api/hosts', {
        name,
        ip_address: host || null,
        port: Number(port) || 45876,
      });
      setCreated(r.data);
      onCreated?.();
    } catch (err) {
      setError(err?.response?.data?.detail || 'Не вдалося створити систему');
    } finally {
      setBusy(false);
    }
  };

  const copy = async () => {
    if (!created?.docker_compose) return;
    try {
      await navigator.clipboard.writeText(created.docker_compose);
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    } catch {
      // Clipboard API can fail on insecure origins — fallback: select the pre.
    }
  };

  // ─── UI ───────────────────────────────────────────────────────────────
  return (
    <div
      className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-start justify-center z-50 p-4 overflow-y-auto"
      onClick={close}
    >
      <div
        className="bg-white rounded-xl shadow-2xl w-full max-w-2xl mt-10 p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-800">Додати систему</h2>
          <button onClick={close} className="text-gray-400 hover:text-gray-700 text-2xl leading-none">
            ×
          </button>
        </div>

        {!created ? (
          // ─── Form step ────────────────────────────────────────────────
          <form onSubmit={submit} className="space-y-4">
            <div className="text-sm text-gray-500 mb-2">
              Заповніть форму — ми згенеруємо унікальний токен агента
              і готовий <code className="text-gray-700">docker-compose.yml</code>,
              який треба запустити на машині, що моніториться.
            </div>

            <div>
              <label className="text-xs font-medium text-gray-700 block mb-1">Назва</label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="prod-web-01"
                className="w-full border border-gray-200 rounded px-3 py-2 text-sm focus:outline-none focus:border-blue-400"
                required
                autoFocus
              />
            </div>

            <div className="grid grid-cols-3 gap-3">
              <div className="col-span-2">
                <label className="text-xs font-medium text-gray-700 block mb-1">Хост / IP</label>
                <input
                  type="text"
                  value={host}
                  onChange={(e) => setHost(e.target.value)}
                  placeholder="10.0.0.42"
                  className="w-full border border-gray-200 rounded px-3 py-2 text-sm focus:outline-none focus:border-blue-400"
                />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-700 block mb-1">Порт</label>
                <input
                  type="number"
                  value={port}
                  onChange={(e) => setPort(e.target.value)}
                  min={1}
                  max={65535}
                  className="w-full border border-gray-200 rounded px-3 py-2 text-sm font-mono focus:outline-none focus:border-blue-400"
                />
              </div>
            </div>

            {error && (
              <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded p-2">
                {error}
              </div>
            )}

            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={close}
                className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800"
              >
                Скасувати
              </button>
              <button
                type="submit"
                disabled={busy || !name}
                className="bg-blue-600 text-white px-5 py-2 rounded text-sm font-medium
                           hover:bg-blue-700 disabled:bg-blue-300 transition"
              >
                {busy ? 'Створення…' : 'Додати систему'}
              </button>
            </div>
          </form>
        ) : (
          // ─── Result step ─────────────────────────────────────────────
          <div className="space-y-4">
            <div className="bg-green-50 border border-green-200 rounded p-3 text-sm text-green-800">
              ✓ Систему <strong>{created.name}</strong> створено. Запустіть
              цей <code>docker-compose.yml</code> на цільовій машині,
              і за ~15 секунд вона з'явиться в онлайні.
            </div>

            <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs">
              <Field label="Name" value={created.name} />
              <Field label="Host / IP" value={created.ip_address || '—'} />
              <Field label="Port" value={created.port} />
              <Field label="Hub URL" value={created.hub_url} />
              <div className="col-span-2">
                <div className="text-gray-500 mb-0.5">Public Key</div>
                <code className="block bg-gray-50 border border-gray-200 rounded px-2 py-1 text-[11px] break-all font-mono">
                  {created.public_key}
                </code>
              </div>
              <div className="col-span-2">
                <div className="text-gray-500 mb-0.5">Token (unique per host)</div>
                <code className="block bg-gray-50 border border-gray-200 rounded px-2 py-1 text-[11px] break-all font-mono">
                  {created.api_token}
                </code>
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between mb-1">
                <div className="text-xs font-medium text-gray-700">docker-compose.yml</div>
                <button
                  onClick={copy}
                  className={`text-xs px-3 py-1 rounded ${
                    copied
                      ? 'bg-green-100 text-green-700'
                      : 'bg-blue-600 text-white hover:bg-blue-700'
                  }`}
                >
                  {copied ? '✓ Скопійовано' : 'Copy docker compose'}
                </button>
              </div>
              <pre className="bg-gray-900 text-gray-100 text-[11px] rounded p-3 overflow-x-auto font-mono leading-5">
{created.docker_compose}
              </pre>
            </div>

            <div className="flex justify-end pt-2">
              <button
                onClick={close}
                className="bg-gray-100 text-gray-700 hover:bg-gray-200 px-4 py-2 text-sm rounded"
              >
                Готово
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Field({ label, value }) {
  return (
    <div>
      <div className="text-gray-500">{label}</div>
      <div className="font-medium text-gray-800 truncate">{value}</div>
    </div>
  );
}
