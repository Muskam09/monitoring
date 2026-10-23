import { useEffect, useState } from 'react';
import axios from 'axios';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';

function App() {
  const [hosts, setHosts] = useState([]);
  const [selectedHost, setSelectedHost] = useState(null);
  const [metrics, setMetrics] = useState([]);

  // Отримання списку хостів при завантаженні
  useEffect(() => {
    axios.get('http://localhost:8000/api/hosts')
      .then(res => setHosts(res.data))
      .catch(err => console.error(err));
  }, []);

  // Отримання метрик для вибраного хоста (оновлення кожні 10 секунд)
  useEffect(() => {
    if (!selectedHost) return;

    const fetchMetrics = () => {
      axios.get(`http://localhost:8000/api/hosts/${selectedHost}/metrics`)
        .then(res => {
          // Розвертаємо масив, щоб старі дані були зліва, а нові справа
          const formattedData = res.data.reverse().map(m => ({
            time: new Date(m.timestamp).toLocaleTimeString(),
            cpu: m.cpu_percent.toFixed(2),
            ram: m.ram_percent.toFixed(2)
          }));
          setMetrics(formattedData);
        });
    };

    fetchMetrics();
    const interval = setInterval(fetchMetrics, 10000);
    return () => clearInterval(interval);
  }, [selectedHost]);

  return (
    <div className="min-h-screen bg-gray-100 p-8">
      <h1 className="text-3xl font-bold text-gray-800 mb-6">DevOps Dashboard</h1>
      
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        {/* Список хостів */}
        <div className="bg-white p-4 rounded-lg shadow col-span-1">
          <h2 className="text-xl font-semibold mb-4">Підключені сервери</h2>
          <ul>
            {hosts.map(host => (
              <li 
                key={host.id} 
                onClick={() => setSelectedHost(host.id)}
                className={`p-3 mb-2 rounded cursor-pointer transition ${selectedHost === host.id ? 'bg-blue-100 border-blue-500 border' : 'bg-gray-50 hover:bg-gray-200'}`}
              >
                <div className="flex justify-between items-center">
                  <span className="font-medium text-gray-700">{host.name}</span>
                  <span className={`w-3 h-3 rounded-full ${host.is_online ? 'bg-green-500 animate-pulse' : 'bg-red-500'}`}></span>
                </div>
              </li>
            ))}
          </ul>
        </div>

        {/* Графіки */}
        <div className="bg-white p-6 rounded-lg shadow col-span-1 md:col-span-3">
          {selectedHost ? (
            <>
              <h2 className="text-xl font-semibold mb-4">Телеметрія сервера</h2>
              <div className="h-96 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={metrics}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="time" />
                    <YAxis domain={[0, 100]} />
                    <Tooltip />
                    <Legend />
                    <Line type="monotone" dataKey="cpu" stroke="#8884d8" name="CPU (%)" strokeWidth={2} dot={false} />
                    <Line type="monotone" dataKey="ram" stroke="#82ca9d" name="RAM (%)" strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </>
          ) : (
            <div className="flex h-full items-center justify-center text-gray-400">
              Оберіть сервер ліворуч для перегляду метрик
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default App;