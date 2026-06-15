export default function IdleState({ onPttToggle, pttState }) {
  return (
    <div style={{ textAlign: "center", animation: "fadeIn 0.6s ease" }}>
      {/* Pulse/Glow Avatar container */}
      <div 
        onClick={onPttToggle}
        style={{
          width: 180, height: 180, borderRadius: "50%",
          background: "radial-gradient(circle, #3b82f6 0%, #1d4ed8 70%, #1e40af 100%)",
          margin: "0 auto 2.5rem",
          display: "flex", alignItems: "center", justifyContent: "center",
          cursor: "pointer",
          animation: "pulse 2.2s ease-in-out infinite",
          boxShadow: "0 0 50px rgba(59, 130, 246, 0.5), inset 0 0 20px rgba(255, 255, 255, 0.2)",
          border: "2px solid rgba(147, 197, 253, 0.4)",
          transition: "transform 0.2s, box-shadow 0.2s",
        }}
        onMouseDown={(e) => {
          e.currentTarget.style.transform = "scale(0.95)";
        }}
        onMouseUp={(e) => {
          e.currentTarget.style.transform = "scale(1.05)";
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.transform = "scale(1.05)";
          e.currentTarget.style.boxShadow = "0 0 65px rgba(59, 130, 246, 0.7), inset 0 0 25px rgba(255, 255, 255, 0.3)";
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.transform = "scale(1)";
          e.currentTarget.style.boxShadow = "0 0 50px rgba(59, 130, 246, 0.5), inset 0 0 20px rgba(255, 255, 255, 0.2)";
        }}
      >
        {/* Mic Icon SVG */}
        <svg 
          width="50" height="50" viewBox="0 0 24 24" 
          fill="none" stroke="white" strokeWidth="2.5" 
          strokeLinecap="round" strokeLinejoin="round"
        >
          <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
          <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
          <line x1="12" x2="12" y1="19" y2="22" />
        </svg>
      </div>

      <h1 style={{ 
        fontSize: "2.5rem", fontWeight: 700, 
        letterSpacing: "-0.025em", marginBottom: "0.75rem",
        background: "linear-gradient(to right, #ffffff, #93c5fd)",
        WebkitBackgroundClip: "text",
        WebkitTextFillColor: "transparent",
      }}>
        Welcome to Reception
      </h1>
      
      <p style={{ 
        color: "#94a3b8", fontSize: "1.2rem", fontWeight: 400,
        maxWidth: 400, margin: "0 auto", lineHeight: 1.6
      }}>
        Tap the avatar to begin check-in
      </p>

      <style>{`
        @keyframes pulse {
          0%, 100% { transform: scale(1); opacity: 1; filter: brightness(1); }
          50% { transform: scale(1.05); opacity: 0.9; filter: brightness(1.15); }
        }
        @keyframes fadeIn {
          from { opacity: 0; transform: translateY(10px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}
