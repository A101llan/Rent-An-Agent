(function () {
  if (window.AgentHubWidget) return;

  var script = document.currentScript;
  if (!script) return;

  var apiKey = script.getAttribute("data-api-key");
  var webUrl = (script.getAttribute("data-agenthub-url") || "http://localhost:3000").replace(/\/$/, "");
  var apiUrl = (script.getAttribute("data-agenthub-api") || "http://localhost:8000").replace(/\/$/, "");

  if (!apiKey) {
    console.error("[AgentHub] data-api-key is required on the embed script tag.");
    return;
  }

  var open = false;
  var root = document.createElement("div");
  root.id = "agenthub-widget-root";
  root.style.cssText =
    "position:fixed;bottom:20px;right:20px;z-index:2147483646;font-family:system-ui,sans-serif;";

  var panel = document.createElement("div");
  panel.style.cssText =
    "display:none;width:380px;height:520px;max-height:calc(100vh - 100px);border-radius:16px;overflow:hidden;box-shadow:0 12px 40px rgba(0,0,0,0.45);margin-bottom:12px;border:1px solid #3f3f46;";

  var iframe = document.createElement("iframe");
  iframe.title = "AgentHub Agent";
  iframe.allow = "clipboard-write";
  iframe.style.cssText = "width:100%;height:100%;border:0;background:#09090b;";
  iframe.src =
    webUrl +
    "/embed/chat?key=" +
    encodeURIComponent(apiKey) +
    "&api=" +
    encodeURIComponent(apiUrl);

  panel.appendChild(iframe);

  var button = document.createElement("button");
  button.type = "button";
  button.setAttribute("aria-label", "Open AgentHub agent");
  button.style.cssText =
    "width:56px;height:56px;border-radius:9999px;border:none;cursor:pointer;background:linear-gradient(135deg,#6366f1,#4f46e5);color:#fff;font-size:22px;box-shadow:0 8px 24px rgba(79,70,229,0.45);float:right;";
  button.innerHTML = "&#129302;";

  button.addEventListener("click", function () {
    open = !open;
    panel.style.display = open ? "block" : "none";
    button.innerHTML = open ? "&#10005;" : "&#129302;";
  });

  root.appendChild(panel);
  root.appendChild(button);
  document.body.appendChild(root);

  window.AgentHubWidget = {
    open: function () {
      open = true;
      panel.style.display = "block";
      button.innerHTML = "&#10005;";
    },
    close: function () {
      open = false;
      panel.style.display = "none";
      button.innerHTML = "&#129302;";
    },
  };
})();
