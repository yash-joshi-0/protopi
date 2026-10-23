const CHAT_POLL_INTERVAL_MS = 4000;

// Component: ChatPage is the main screen, showing the chat and taking new messages.
function ChatPage() {
  const [messages, setMessages] = React.useState([]);
  const [limits, setLimits] = React.useState({ username: 32, body: 500 });
  const [notice, setNotice] = React.useState("");
  const [loaded, setLoaded] = React.useState(false);

  // Contract: Pull the stored messages and the limits the server enforces.
  const refresh = React.useCallback(async () => {
    try {
      const payload = await readMessages();

      if (payload.error) {
        setNotice(payload.error);
        return;
      }

      setMessages(payload.messages || []);
      setLimits({
        username: payload.maximum_username_length,
        body: payload.maximum_message_length,
      });
      setNotice("");
    } catch (error) {
      setNotice("Chat unreachable: " + error);
    } finally {
      setLoaded(true);
    }
  }, []);

  React.useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, CHAT_POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [refresh]);

  // Contract: Show a sent message straight away rather than waiting for the poll.
  function handleSent(message) {
    setNotice("");
    setMessages((previous) => previous.concat(message));
  }

  return (
    <main className="card chat">
      <header>
        <h1>PROTOPI CHAT</h1>
        <a className="meta" href="/admin">
          Admin console
        </a>
      </header>

      {loaded ? (
        <MessageList messages={messages} />
      ) : (
        <div className="messages">
          <p className="meta">Loading messages...</p>
        </div>
      )}

      <ChatForm
        maximumUsernameLength={limits.username}
        maximumMessageLength={limits.body}
        onSent={handleSent}
        onError={setNotice}
      />

      {notice ? <p className="error">{notice}</p> : null}
    </main>
  );
}
