// content.ts - Injected into webpages

console.log("AgentHub Content Script Loaded.");

// Listen for messages from the background script
chrome.runtime.onMessage.addListener((request, _sender, _sendResponse) => {
  if (request.type === 'AGENT_MESSAGE') {
    console.log("Message from Agent:", request.payload);
    // In a full implementation, this would render a floating chat bubble React component
    // or highlight elements on the DOM based on the agent's instructions.
    
    if (request.payload.action === 'highlight') {
        const element = document.querySelector(request.payload.selector);
        if (element) {
            (element as HTMLElement).style.border = "3px solid #6366f1"; // Indigo highlight
        }
    }
  }
});

// Example of sending page context to the agent
function sendContextToAgent() {
  const context = {
    url: window.location.href,
    title: document.title,
    // Extracting text or specific DOM elements could happen here
  };
  
  chrome.runtime.sendMessage({
    type: 'SEND_TO_AGENT',
    payload: {
        event: 'PAGE_CONTEXT',
        context
    }
  });
}
