const USERNAME_STORAGE_KEY = "protopi-chat-username";

// Contract: Read the remembered username, or an empty string when there is none.
function readRememberedUsername() {
  try {
    return window.localStorage.getItem(USERNAME_STORAGE_KEY) || "";
  } catch (error) {
    return "";
  }
}

// Contract: Remember the username for the next visit, ignoring a blocked store.
function rememberUsername(username) {
  try {
    window.localStorage.setItem(USERNAME_STORAGE_KEY, username);
  } catch (error) {
    return;
  }
}

// Component: ChatForm takes a username and a message and sends them.
function ChatForm(props) {
  const [username, setUsername] = React.useState(readRememberedUsername);
  const [body, setBody] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  // Contract: Send the message, then hand the stored one back to the page.
  async function submit(event) {
    event.preventDefault();

    if (!username.trim() || !body.trim()) {
      props.onError("A username and a message are both needed.");
      return;
    }

    setBusy(true);

    try {
      const result = await sendJson("/api/messages", {
        username: username.trim(),
        body: body.trim(),
      });

      if (result.status !== 201) {
        props.onError(result.payload.error || "The message was not sent.");
        return;
      }

      rememberUsername(username.trim());
      setBody("");
      props.onSent(result.payload.message);
    } catch (error) {
      props.onError("Chat unreachable: " + error);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="chat-form" onSubmit={submit}>
      <label htmlFor="chat-username">Name</label>
      <input
        id="chat-username"
        maxLength={props.maximumUsernameLength}
        autoComplete="nickname"
        placeholder="who are you?"
        value={username}
        onChange={(event) => setUsername(event.target.value)}
      />

      <label htmlFor="chat-body">Message</label>
      <div className="chat-send">
        <input
          id="chat-body"
          maxLength={props.maximumMessageLength}
          autoComplete="off"
          placeholder="say something"
          value={body}
          onChange={(event) => setBody(event.target.value)}
        />

        <button type="submit" disabled={busy}>
          {busy ? "..." : "Send"}
        </button>
      </div>
    </form>
  );
}
