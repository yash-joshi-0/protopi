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

// Contract: Read the current session state from the server.
async function readSession() {
  const response = await fetch("/api/session", {
    headers: { Accept: "application/json" },
  });

  return response.json();
}
