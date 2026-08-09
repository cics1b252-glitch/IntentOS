export const demoMissions = Object.freeze([
  {
    title: "Review monthly income plan", objective: "Compare supplied portfolio scenarios.",
    status: "running", domain: "Financial demonstration", priority: "High",
    progress: 58, capabilities: ["Scenario review", "Public summary"],
    nextAction: "Review the presented assumptions.", selected: true,
  },
  {
    title: "Research accessible interaction", objective: "Organize public references.",
    status: "ready", domain: "Research demonstration", priority: "Medium",
    progress: 20, capabilities: ["Reference organization"],
  },
  {
    title: "Prepare vehicle integration notes", objective: "Structure supplied engineering notes.",
    status: "draft", domain: "Engineering demonstration", priority: "Medium",
    progress: 10, capabilities: ["Document structure"],
  },
  {
    title: "Confirm external draft", objective: "Wait for explicit approval before the simulated action.",
    status: "waiting", domain: "Confirmation demonstration", priority: "High",
    progress: 80, capabilities: ["Draft preparation"], alerts: ["Confirmation required"],
  },
  {
    title: "Archive reviewed references", objective: "Demonstrate a completed public state.",
    status: "completed", domain: "Knowledge demonstration", priority: "Low", progress: 100,
  },
  {
    title: "Load unavailable source", objective: "Demonstrate a public failure state.",
    status: "failed", domain: "Provider demonstration", priority: "Low", progress: 35,
    alerts: ["Demonstration source unavailable"],
  },
]);

export const demoFixture = Object.freeze({
  route: "home",
  navigation: { current: "home" },
  selectedMission: demoMissions[0].title,
  missions: demoMissions,
  workspaceState: "welcome",
  context: [
    {
      title: "Income objective supplied for demonstration", type: "user",
      source: "Local demonstration fixture", relevance: 88, availability: "available",
      sensitive: false, summary: "A supplied objective, not an inferred preference.",
    },
    {
      title: "Unavailable historical context", type: "historical",
      source: "Demonstration archive", availability: "unavailable",
      summary: "This scenario demonstrates missing context.",
    },
  ],
  provenance: [{
    type: "project-memory", source: "Local demonstration fixture",
    version: "Studio 2", reliability: "Demonstration only", availability: "available",
  }],
  capabilities: [
    { name: "Scenario review", state: "available", description: "Demonstration capability" },
    { name: "Public summary", state: "selected", description: "Demonstration capability" },
    { name: "External provider", state: "unavailable", description: "No provider is connected" },
  ],
  agents: [{
    name: "Demonstration coordinator", description: "Local presentation-only software component.",
    state: "available", capability: "Public state composition",
  }],
  relationships: [{
    source: "Supplied income objective", relationship: "supports",
    target: "Monthly plan review", provenance: "Demonstration fixture",
    notes: "This relationship is explicitly provided by fixture data.",
  }],
  activity: {
    pulse: { state: "idle", label: "Shell ready" },
    execution: { state: "queued", label: "No active execution", detail: "Demonstration mode" },
    timeline: {
      label: "Recent public activity",
      items: [
        { type: "mission-created", timestamp: "2026-07-30T09:00:00Z", description: "Demonstration mission loaded.", source: "Local fixture" },
        { type: "context-added", timestamp: "2026-07-30T09:02:00Z", description: "Public context added.", source: "Local fixture" },
      ],
    },
    confidence: { mode: "unavailable" },
    message: "The Shell is using local demonstration data.",
  },
  systemStatus: {
    local: "ready", connectivity: "offline demonstration",
    providerAvailability: "simulated unavailable", demonstration: true,
  },
  panels: {
    missionRailOpen: true, contextOpen: true,
    contextPinned: false, navigationExpanded: true,
  },
  preferences: {
    appearance: "system", ambient: "neutral",
    density: "comfortable", motion: "full",
  },
});

export const emptyDemoFixture = Object.freeze({
  ...demoFixture, missions: [], selectedMission: null,
  workspaceState: "empty", context: [], provenance: [],
  capabilities: [], agents: [], relationships: [],
});
