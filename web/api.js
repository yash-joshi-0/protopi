// Contract: Send a JSON request and return the parsed body with its status code.
async function sendJson(path, body, token) {
  const headers = { "Content-Type": "application/json" };

  if (token) {
    headers["X-ProtoPi-Token"] = token;
  }

  const response = await fetch(path, {
    method: "POST",
    headers: headers,
    body: JSON.stringify(body),
  });

  return { status: response.status, payload: await response.json() };
}

// Contract: Read JSON from one of the GET endpoints.
async function readJson(path) {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  return response.json();
}

// Contract: Read the current session state from the server.
async function readSession() {
  return readJson("/api/session");
}

// Contract: Read the stored chat messages, oldest first.
async function readMessages() {
  return readJson("/api/messages");
}

// Contract: Format a stored timestamp as a short local clock time.
function formatSentAt(sentAtMs) {
  return new Date(sentAtMs).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}
