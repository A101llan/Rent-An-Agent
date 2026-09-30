// background.ts - Service Worker

let websocket: WebSocket | null = null;

chrome.runtime.onInstalled.addListener(() => {
  console.log("AgentHub Extension Installed.");
});

// Function to establish connection with AgentHub Cloud
function connectToAgentHub(token: string) {
  if (websocket) websocket.close();
  
  // Note: in prod, use wss://api.agenthub.dev
  websocket = new WebSocket(`ws://localhost:8000/api/v1/ws?token=${token}`);

  websocket.onopen = () => {
    console.log("Connected to AgentHub Runtime.");
  };

  websocket.onmessage = (event) => {
    const data = JSON.parse(event.data);
    // Forward message to the active tab (content script) or popup
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (tabs[0]?.id) {
        chrome.tabs.sendMessage(tabs[0].id, { type: 'AGENT_MESSAGE', payload: data });
      }
    });
  };

  websocket.onclose = () => {
    console.log("Disconnected from AgentHub Runtime.");
    websocket = null;
  };
}

// Listen for messages from the popup or content script
chrome.runtime.onMessage.addListener((request, _sender, sendResponse) => {
  if (request.type === 'CONNECT') {
    connectToAgentHub(request.token);
    sendResponse({ status: 'connecting' });
  } else if (request.type === 'SEND_TO_AGENT' && websocket) {
    websocket.send(JSON.stringify(request.payload));
    sendResponse({ status: 'sent' });
  }
});
