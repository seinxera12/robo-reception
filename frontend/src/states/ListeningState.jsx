import { useEffect, useState } from "react";

export default function ListeningState({ onPttToggle, audioLevel }) {
  const bars = 16;
  const [ticker, setTicker] = useState(0);

  // Organic micro-movement when user is silent
  useEffect(() => {
    const interval = setInterval(() => {
      setTicker((t) => (t + 1) % 100);
    }, 50);
    return () => clearInterval(interval);
  }, []);

  return (
    <div style={{ textAlign: "center", animation: "fadeIn 0.5s ease" }}>
      {/* Waveform container */}
      <div style={{
        display: "flex", alignItems: "center",
        justifyContent: "center", gap: 5,
        height: 100, marginBottom: "2rem",
      }}>
        {Array.from({ length: bars }).map((_, i) => {
          const phase = (i / bars) * Math.PI;
          // Calculate an organic height based on audio level plus some sine wave ripple
          const rawHeight = 8 + (audioLevel * 70) * Math.abs(Math.sin(phase)) + 6 * Math.sin(phase + ticker * 0.4);
          const finalHeight = Math.max(8, Math.min(90, rawHeight));
          
          return (
            <div 
              key={i} 
              style={{
                width: 6, 
                borderRadius: 4,
                height: finalHeight,
                background: "linear-gradient(to top, #3b82f6 0%, #60a5fa 100%)",
                boxShadow: "0 0 10px rgba(59, 130, 246, 0.4)",
                transition: "height 0.08s cubic-bezier(0.4, 0, 0.2, 1)",
              }} 
            />
          );
        })}
      </div>

      <p style={{ 
        color: "#60a5fa", fontSize: "1.4rem", fontWeight: 600, 
        letterSpacing: "0.05em", textTransform: "uppercase", 
        marginBottom: "0.5rem"
      }}>
        Listening...
      </p>

      {/* Cancel button */}
      <button
        onClick={onPttToggle}
        style={{
          background: "rgba(239, 68, 68, 0.1)",
          border: "1px solid rgba(239, 68, 68, 0.3)",
          color: "#ef4444",
          padding: "8px 20px",
          borderRadius: "20px",
          cursor: "pointer",
          fontSize: "0.9rem",
          fontWeight: 600,
          transition: "background 0.2s, color 0.2s",
          marginTop: "1rem"
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.background = "rgba(239, 68, 68, 0.2)";
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.background = "rgba(239, 68, 68, 0.1)";
        }}
      >
        Tap to Cancel
      </button>

      <style>{`
        @keyframes fadeIn {
          from { opacity: 0; transform: scale(0.95); }
          to { opacity: 1; transform: scale(1); }
        }
      `}</style>
    </div>
  );
}
