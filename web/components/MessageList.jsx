// Component: MessageList shows the stored chat messages, oldest first.
function MessageList(props) {
  const paneRef = React.useRef(null);

  React.useEffect(() => {
    const pane = paneRef.current;

    if (pane) {
      pane.scrollTop = pane.scrollHeight;
    }
  }, [props.messages]);

  if (props.messages.length === 0) {
    return (
      <div className="messages" ref={paneRef}>
        <p className="meta">No messages yet. Say something.</p>
      </div>
    );
  }

  return (
    <div className="messages" ref={paneRef}>
      {props.messages.map((message) => (
        <article className="message" key={message.id}>
          <header className="message-header">
            <span className="message-username">{message.username}</span>
            <time className="meta">{formatSentAt(message.sent_at_ms)}</time>
          </header>
          <p className="message-body">{message.body}</p>
        </article>
      ))}
    </div>
  );
}
