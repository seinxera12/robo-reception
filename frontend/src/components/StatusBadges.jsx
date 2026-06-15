export default function StatusBadges({ badges }) {
  const items = [
    { key: "checkedIn",        label: "Checked In" },
    { key: "hostNotified",     label: "Host Notified" },
    { key: "hostAcknowledged", label: "Host On Their Way" },
  ];

  // Don't render anything if no badges have been activated yet
  if (!Object.values(badges).some(Boolean)) return null;

  return (
    <div style={{
      position: "fixed", 
      bottom: "2.5rem",
      display: "flex", 
      gap: 16,
      flexWrap: "wrap", 
      justifyContent: "center",
      padding: "0 1rem",
      zIndex: 100,
      animation: "slideUp 0.5s cubic-bezier(0.16, 1, 0.3, 1)",
    }}>
      {items.map(({ key, label }) => {
        const isActive = badges[key];
        return (
          <div 
            key={key} 
            style={{
              display: "flex", 
              alignItems: "center", 
              gap: 10,
              padding: "10px 20px", 
              borderRadius: "30px",
              background: isActive 
                ? "rgba(20, 83, 45, 0.65)" 
                : "rgba(30, 41, 59, 0.5)",
              border: `1.5px solid ${isActive ? "#22c55e" : "rgba(255,255,255,0.06)"}`,
              color: isActive ? "#a7f3d0" : "#64748b",
              fontSize: "0.95rem", 
              fontWeight: 600,
              boxShadow: isActive 
                ? "0 4px 15px rgba(34, 197, 94, 0.25)" 
                : "0 4px 15px rgba(0,0,0,0.15)",
              backdropFilter: "blur(10px)",
              transition: "all 0.5s cubic-bezier(0.4, 0, 0.2, 1)",
            }}
          >
            {/* Status indicator (Checkmark or empty circle) */}
            <span style={{
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              width: 18,
              height: 18,
              borderRadius: "50%",
              border: `1.5px solid ${isActive ? "#22c55e" : "#475569"}`,
              background: isActive ? "#22c55e" : "transparent",
              color: isActive ? "#064e3b" : "transparent",
              fontSize: "0.75rem",
              fontWeight: 800,
              transition: "all 0.4s",
            }}>
              ✓
            </span>
            <span>{label}</span>
          </div>
        );
      })}

      <style>{`
        @keyframes slideUp {
          from { opacity: 0; transform: translateY(15px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}
