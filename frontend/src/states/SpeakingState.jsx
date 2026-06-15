export default function SpeakingState({ response, transcript }) {
  return (
    <div style={{ 
      textAlign: "center", 
      maxWidth: 640, 
      padding: "0 2.5rem",
      animation: "fadeInUp 0.6s cubic-bezier(0.16, 1, 0.3, 1)"
    }}>
      {/* Transcript bubble */}
      {transcript && (
        <div style={{ 
          display: "inline-block",
          background: "rgba(255, 255, 255, 0.03)",
          border: "1px solid rgba(255, 255, 255, 0.05)",
          borderRadius: "16px",
          padding: "6px 14px",
          fontSize: "0.9rem", 
          color: "#94a3b8",
          marginBottom: "1.5rem"
        }}>
          You: <span style={{ color: "#cbd5e1", fontStyle: "italic" }}>"{transcript}"</span>
        </div>
      )}

      {/* Main response card */}
      <div style={{
        background: "rgba(30, 41, 59, 0.4)", 
        borderRadius: "24px",
        padding: "2rem 2.5rem",
        fontSize: "1.4rem", 
        lineHeight: 1.6,
        fontWeight: 400,
        color: "#f8fafc",
        border: "1px solid rgba(147, 197, 253, 0.15)",
        boxShadow: "0 20px 40px rgba(0, 0, 0, 0.3), inset 0 1px 0 rgba(255,255,255,0.05)",
        backdropFilter: "blur(12px)",
        textAlign: "left",
      }}>
        {response}
      </div>

      {/* Pulsing indicator dots */}
      <div style={{
        display: "flex", justifyContent: "center",
        gap: 8, marginTop: "2rem",
      }}>
        {[0, 1, 2].map(i => (
          <div key={i} style={{
            width: 10, height: 10, borderRadius: "50%",
            background: "#60a5fa",
            boxShadow: "0 0 8px rgba(96, 165, 250, 0.6)",
            animation: `bounce 1.2s ease-in-out ${i * 0.2}s infinite`,
          }} />
        ))}
      </div>

      <style>{`
        @keyframes bounce {
          0%, 100% { transform: translateY(0); opacity: 0.3; }
          50% { transform: translateY(-10px); opacity: 1; }
        }
        @keyframes fadeInUp {
          from { opacity: 0; transform: translateY(20px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}
