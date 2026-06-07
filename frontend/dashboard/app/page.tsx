export default function Home() {
  return (
    <main className="min-h-screen bg-gray-950 text-white flex flex-col items-center justify-center p-8">
      <div className="max-w-2xl w-full space-y-6">
        <div className="text-center space-y-2">
          <h1 className="text-4xl font-bold tracking-tight">Microtrading App</h1>
          <p className="text-gray-400 text-lg">Phase 0 Dashboard Skeleton</p>
        </div>

        <div className="grid grid-cols-1 gap-4">
          <StatusCard label="Trading Mode" value="Paper Trading Only" color="yellow" />
          <StatusCard label="Broker Connection" value="Not Connected" color="red" />
          <StatusCard label="Live Orders" value="Disabled" color="red" />
          <StatusCard label="Real-Money Execution" value="Disabled" color="red" />
        </div>

        <div className="bg-gray-800 rounded-lg p-5 border border-gray-700 text-sm text-gray-300 space-y-2">
          <p className="font-semibold text-white">System Notice</p>
          <p>
            AI interprets catalysts and may recommend opportunities to the engine.
            The <span className="text-yellow-400 font-semibold">Risk Manager has veto power</span> over
            all trade decisions. AI may not execute trades directly.
          </p>
          <p className="text-gray-500 mt-2">
            Phase 0 — Foundation only. No external connections active.
          </p>
        </div>
      </div>
    </main>
  );
}

function StatusCard({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color: "green" | "yellow" | "red";
}) {
  const colors = {
    green: "text-green-400 bg-green-950 border-green-800",
    yellow: "text-yellow-400 bg-yellow-950 border-yellow-800",
    red: "text-red-400 bg-red-950 border-red-800",
  };
  return (
    <div className={`rounded-lg border p-4 flex justify-between items-center ${colors[color]}`}>
      <span className="text-gray-300 font-medium">{label}</span>
      <span className="font-semibold">{value}</span>
    </div>
  );
}
