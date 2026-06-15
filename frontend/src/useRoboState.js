import { useReducer } from "react";

const initialState = {
  uiState: "idle",           // "idle" | "listening" | "thinking" | "speaking" | "wayfinding"
  transcript: "",            // visitor transcript
  response: "",              // agent response
  route: null,               // wayfinding route [{step, node_id, instruction, floor}]
  currentFloor: 1,           // active floor to display
  badges: {
    checkedIn: false,
    hostNotified: false,
    hostAcknowledged: false,
  },
  audioLevel: 0,             // volume level (0-1) for waveform meter
  pttState: "idle",          // "idle" | "recording" | "busy"
};

function reducer(state, action) {
  switch (action.type) {
    case "SET_STATE": {
      // If we are showing the wayfinding map, don't transition back to idle automatically
      // when the speaker finishes. This keeps the directions visible.
      if (action.state === "idle" && state.uiState === "wayfinding") {
        return { ...state, pttState: "idle" };
      }
      
      const newPttState = 
        action.state === "thinking" || action.state === "speaking" ? "busy" :
        action.state === "listening" ? "recording" : "idle";

      return { 
        ...state, 
        uiState: action.state,
        pttState: newPttState
      };
    }

    case "START_RECORDING":
      return {
        ...state,
        uiState: "listening",
        pttState: "recording",
        transcript: "",
        response: "",
      };

    case "CANCEL_RECORDING":
      return {
        ...state,
        uiState: "idle",
        pttState: "idle",
      };

    case "SET_TRANSCRIPT":
      return { ...state, transcript: action.text };

    case "SET_RESPONSE":
      return { ...state, response: action.text };

    case "SET_AUDIO_LEVEL":
      return { ...state, audioLevel: action.level };

    case "SET_ROUTE":
      return {
        ...state,
        uiState: "wayfinding",
        route: action.route,
        currentFloor: action.floor_changes?.[0] ?? 1,
      };

    case "SET_FLOOR":
      return { ...state, currentFloor: action.floor };

    case "SET_BADGE":
      return {
        ...state,
        badges: { ...state.badges, [action.badge]: true },
      };

    case "RESET_SESSION":
      return {
        ...initialState,
        // Reset everything
      };

    case "RESET_BADGES":
      return { ...state, badges: initialState.badges };

    default:
      return state;
  }
}

export function useRoboState() {
  return useReducer(reducer, initialState);
}
