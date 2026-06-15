export default function ThinkingState({ response }) {
  return (
    <div style={{ textAlign: "center", animation: "fadeIn 0.5s ease" }}>
      {/* Outer Glow Spinner */}
      <div style={{
        width: 70, height: 70,
        border: "3px solid rgba(59, 130, 246, 0.1)",
        borderTop: "3px solid #3b82f6",
        borderRight: "3px solid rgba(59, 130, 246, 0.5)",
        borderRadius: "50%",
        margin: "0 auto 2.5rem",
        animation: "spin 1s cubic-bezier(0.5, 0, 0.5, 1) infinite",
        boxShadow: "0 0 15px rgba(59, 130, 246, 0.2)",
      }} />
      
      <p style={{ 
        color: "#94a3b8", fontSize: "1.2rem", fontWeight: 500,
        letterSpacing: "0.025em"
      }}>
        Processing...
      </p>

      <style>{`
        @keyframes spin { 
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); } 
        }
        @keyframes fadeIn {
          from { opacity: 0; }
          to { opacity: 1; }
        }
      `}</style>
    </div>
  );
}
