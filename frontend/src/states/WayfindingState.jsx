import FloorPlan from "../components/FloorPlan";

export default function WayfindingState({ 
  route, 
  currentFloor, 
  onFloorChange, 
  onClose,
  onPttToggle,
  pttState
}) {
  const currentSteps = route?.filter(s => s.floor === currentFloor) ?? [];
  const destination = route?.[route.length - 1];
  
  // Extract destination name cleanly
  const destName = destination?.instruction
    ? destination.instruction
        .replace("Arrive at ", "")
        .replace(" — your destination", "")
    : "Your Destination";

  return (
    <div style={{
      width: "100vw", height: "100vh",
      display: "flex", flexDirection: "column",
      padding: "2rem",
      boxSizing: "border-box",
      animation: "fadeIn 0.6s cubic-bezier(0.16, 1, 0.3, 1)",
    }}>
      {/* Header */}
      <div style={{ 
        display: "flex", 
        justifyContent: "space-between", 
        alignItems: "center",
        marginBottom: "1.5rem",
        borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
        paddingBottom: "1rem"
      }}>
        <div>
          <h2 style={{ margin: 0, fontSize: "1.8rem", fontWeight: 700, color: "#f8fafc" }}>
            Directions to {destName}
          </h2>
          <p style={{ color: "#94a3b8", margin: "0.25rem 0 0", fontSize: "1rem" }}>
            Follow the green path on the map
          </p>
        </div>
        
        {/* Back to welcome button */}
        <button
          onClick={onClose}
          style={{
            background: "rgba(255, 255, 255, 0.05)",
            border: "1px solid rgba(255, 255, 255, 0.1)",
            color: "#e2e8f0",
            padding: "10px 20px",
            borderRadius: "20px",
            cursor: "pointer",
            fontSize: "0.95rem",
            fontWeight: 600,
            transition: "all 0.2s",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = "rgba(255, 255, 255, 0.1)";
            e.currentTarget.style.borderColor = "rgba(255, 255, 255, 0.2)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = "rgba(255, 255, 255, 0.05)";
            e.currentTarget.style.borderColor = "rgba(255, 255, 255, 0.1)";
          }}
        >
          Back to Welcome
        </button>
      </div>

      {/* Main Area (Split: Map & Steps) */}
      <div style={{ 
        flex: 1, 
        display: "flex", 
        gap: "2rem",
        minHeight: 0,
        width: "100%"
      }}>
        {/* Left: Map */}
        <div style={{ 
          flex: 1.3,
          background: "rgba(15, 23, 42, 0.3)",
          border: "1px solid rgba(255, 255, 255, 0.05)",
          borderRadius: "20px",
          padding: "1rem",
          display: "flex",
          flexDirection: "column",
          position: "relative",
          minHeight: 0,
          boxShadow: "inset 0 0 20px rgba(0,0,0,0.4)"
        }}>
          <FloorPlan
            route={route}
            currentFloor={currentFloor}
            onFloorChange={onFloorChange}
          />
        </div>

        {/* Right: Steps and PTT */}
        <div style={{ 
          flex: 1, 
          display: "flex", 
          flexDirection: "column", 
          gap: "1.5rem",
          minHeight: 0
        }}>
          {/* Step List card */}
          <div style={{
            flex: 1,
            background: "rgba(30, 41, 59, 0.25)",
            border: "1px solid rgba(255, 255, 255, 0.05)",
            borderRadius: "20px",
            padding: "1.5rem",
            display: "flex",
            flexDirection: "column",
            minHeight: 0,
          }}>
            <h3 style={{ margin: "0 0 1rem 0", fontSize: "1.2rem", fontWeight: 600, color: "#cbd5e1" }}>
              Route Directions
            </h3>
            
            <div style={{
              flex: 1,
              overflowY: "auto",
              display: "flex",
              flexDirection: "column",
              gap: 10,
              paddingRight: "0.5rem"
            }}>
              {currentSteps.map((step) => (
                <div 
                  key={step.step} 
                  style={{
                    display: "flex", 
                    gap: 12, 
                    alignItems: "center",
                    background: "rgba(30, 41, 59, 0.6)", 
                    border: "1px solid rgba(255, 255, 255, 0.03)",
                    borderRadius: "12px", 
                    padding: "12px 16px",
                    animation: `fadeInUp 0.4s ease ${step.step * 0.05}s both`
                  }}
                >
                  <span style={{
                    background: "#3b82f6", 
                    color: "white",
                    borderRadius: "50%", 
                    width: 28, 
                    height: 28,
                    display: "flex", 
                    alignItems: "center", 
                    justifyContent: "center",
                    fontSize: "0.9rem", 
                    fontWeight: 700, 
                    flexShrink: 0,
                    boxShadow: "0 0 8px rgba(59, 130, 246, 0.4)"
                  }}>{step.step}</span>
                  
                  <span style={{ color: "#e2e8f0", fontSize: "1rem", lineHeight: 1.4 }}>
                    {step.instruction}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Follow-up Voice Interaction Card */}
          <div style={{
            background: "rgba(30, 41, 59, 0.4)",
            border: "1px solid rgba(147, 197, 253, 0.1)",
            borderRadius: "20px",
            padding: "1.25rem",
            display: "flex",
            alignItems: "center",
            gap: "1.25rem",
            boxShadow: "0 10px 20px rgba(0,0,0,0.2)"
          }}>
            {/* PTT Toggle Button */}
            <button
              onClick={onPttToggle}
              disabled={pttState === "busy"}
              style={{
                width: 50, height: 50, borderRadius: "50%",
                background: pttState === "recording" 
                  ? "radial-gradient(circle, #ef4444 0%, #dc2626 100%)" 
                  : pttState === "busy"
                    ? "#475569"
                    : "radial-gradient(circle, #3b82f6 0%, #1d4ed8 100%)",
                border: "none",
                cursor: pttState === "busy" ? "not-allowed" : "pointer",
                display: "flex", alignItems: "center", justifyContent: "center",
                boxShadow: pttState === "recording" 
                  ? "0 0 15px rgba(239, 68, 68, 0.6)" 
                  : "0 0 15px rgba(59, 130, 246, 0.4)",
                flexShrink: 0,
                transition: "all 0.2s",
                animation: pttState === "recording" ? "pttPulse 1s ease-in-out infinite" : "none"
              }}
            >
              {/* Mic Icon */}
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5">
                <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
                <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                <line x1="12" x2="12" y1="19" y2="22" />
              </svg>
            </button>

            <div>
              <h4 style={{ margin: 0, fontSize: "1.05rem", fontWeight: 600, color: "#f1f5f9" }}>
                {pttState === "recording" ? "Recording... Tap again to cancel" : 
                 pttState === "busy" ? "Processing..." : "Ask a follow-up question"}
              </h4>
              <p style={{ margin: "4px 0 0 0", fontSize: "0.85rem", color: "#94a3b8" }}>
                {pttState === "recording" ? "VAD will stop automatically when you finish" : 
                 pttState === "busy" ? "The assistant is listening/thinking..." : "e.g. \"Where is the kitchen?\""}
              </p>
            </div>
          </div>
        </div>
      </div>

      <style>{`
        @keyframes fadeIn {
          from { opacity: 0; }
          to { opacity: 1; }
        }
        @keyframes fadeInUp {
          from { opacity: 0; transform: translateY(10px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes pttPulse {
          0%, 100% { transform: scale(1); filter: brightness(1); }
          50% { transform: scale(1.08); filter: brightness(1.15); }
        }
      `}</style>
    </div>
  );
}
