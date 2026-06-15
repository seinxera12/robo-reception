import { useEffect, useRef } from "react";

// Import SVGs as raw strings using Vite's ?raw import
import floorPlan1 from "../../../data/floor_plan_f1.svg?raw";
import floorPlan2 from "../../../data/floor_plan_f2.svg?raw";

const floorPlans = { 1: floorPlan1, 2: floorPlan2 };

export default function FloorPlan({ route, currentFloor, onFloorChange }) {
  const containerRef = useRef(null);

  useEffect(() => {
    if (!containerRef.current) return;

    // 1. Clear all previous highlights
    containerRef.current.querySelectorAll(".highlighted-route").forEach(el => {
      el.classList.remove("highlighted-route");
    });

    if (!route) return;

    // 2. Filter route steps belonging to the current floor
    const floorSteps = route.filter(step => step.floor === currentFloor);

    // 3. Highlight nodes and corridors sequentially
    floorSteps.forEach((step, index) => {
      // Highlight the room/node group
      const nodeEl = containerRef.current.querySelector(`#node-${step.node_id}`);
      if (nodeEl) {
        setTimeout(() => {
          nodeEl.classList.add("highlighted-route");
        }, index * 400); // 400ms stagger between steps
      }

      // Highlight the corridor leading to the next step
      if (index < floorSteps.length - 1) {
        const nextStep = floorSteps[index + 1];
        
        // Try forward direction id (e.g. corridor-reception-lobby-f1)
        let corridorId = `corridor-${step.node_id}-${nextStep.node_id}`;
        let corridorEl = containerRef.current.querySelector(`#${corridorId}`);
        
        // If not found, try reverse direction id (e.g. corridor-lobby-f1-reception)
        if (!corridorEl) {
          corridorId = `corridor-${nextStep.node_id}-${step.node_id}`;
          corridorEl = containerRef.current.querySelector(`#${corridorId}`);
        }

        if (corridorEl) {
          setTimeout(() => {
            corridorEl.classList.add("highlighted-route");
          }, index * 400 + 200); // Highlight corridors halfway between node highlights
        }
      }
    });
  }, [route, currentFloor]);

  const svgContent = floorPlans[currentFloor] ?? floorPlans[1];
  
  // Extract all unique floors visited in the route
  const floors = route
    ? [...new Set(route.map(s => s.floor))].sort()
    : [1];

  return (
    <div style={{ width: "100%", height: "100%", display: "flex", flexDirection: "column" }}>
      {/* Floor Switcher tabs (only show if route spans multiple floors) */}
      {floors.length > 1 && (
        <div style={{
          display: "flex", gap: 10, justifyContent: "center", marginBottom: "1.25rem", zIndex: 10
        }}>
          {floors.map(floor => (
            <button
              key={floor}
              onClick={() => onFloorChange(floor)}
              style={{
                padding: "8px 20px", 
                borderRadius: "30px",
                border: "1px solid rgba(255, 255, 255, 0.15)", 
                cursor: "pointer",
                background: currentFloor === floor ? "#3b82f6" : "rgba(30, 41, 59, 0.6)",
                color: currentFloor === floor ? "white" : "#94a3b8",
                fontWeight: 600,
                fontSize: "0.9rem",
                boxShadow: currentFloor === floor ? "0 4px 12px rgba(59, 130, 246, 0.3)" : "none",
                transition: "all 0.3s cubic-bezier(0.4, 0, 0.2, 1)",
              }}
              onMouseEnter={(e) => {
                if (currentFloor !== floor) {
                  e.currentTarget.style.background = "rgba(255, 255, 255, 0.08)";
                }
              }}
              onMouseLeave={(e) => {
                if (currentFloor !== floor) {
                  e.currentTarget.style.background = "rgba(30, 41, 59, 0.6)";
                }
              }}
            >
              Floor {floor}
            </button>
          ))}
        </div>
      )}

      {/* SVG Container */}
      <div
        ref={containerRef}
        dangerouslySetInnerHTML={{ __html: svgContent }}
        style={{ 
          flex: 1, 
          width: "100%", 
          display: "flex", 
          alignItems: "center", 
          justifyContent: "center",
          minHeight: 0 
        }}
      />

      {/* CSS Styling injected for highlighting classes inside the SVG */}
      <style>{`
        /* Animate rectangles and paths in SVG */
        .highlighted-route rect,
        .highlighted-route path {
          stroke: #22c55e !important;
          stroke-width: 4px !important;
          filter: drop-shadow(0 0 12px rgba(34, 197, 94, 0.8));
          transition: all 0.5s ease-in-out;
        }
        
        /* Highlight text within highlighted node groups */
        .highlighted-route text {
          fill: #86efac !important;
          font-weight: 700 !important;
          transition: all 0.5s ease-in-out;
        }

        /* Specific style for corridor lines */
        path.highlighted-route[id^="corridor-"] {
          stroke: #22c55e !important;
          stroke-width: 16px !important;
          opacity: 0.8;
          stroke-linecap: round;
        }

        /* Base SVG transition states */
        svg g rect, svg g path, svg path {
          transition: stroke 0.4s ease, stroke-width 0.4s ease, filter 0.4s ease;
        }
      `}</style>
    </div>
  );
}
