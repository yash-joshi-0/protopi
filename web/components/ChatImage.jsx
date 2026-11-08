// Component: ChatImage shows an uploaded picture blurred until the viewer clicks it.
function ChatImage(props) {
  const [revealed, setRevealed] = React.useState(false);

  return (
    <button
      type="button"
      className={revealed ? "chat-image revealed" : "chat-image"}
      aria-pressed={revealed}
      aria-label={revealed ? "Hide image" : "Show image"}
      onClick={() => setRevealed(!revealed)}
    >
      <img src={props.src} alt="" loading="lazy" />
      {revealed ? null : <span className="chat-image-veil">Click to show</span>}
    </button>
  );
}
