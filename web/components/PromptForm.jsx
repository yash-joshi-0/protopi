// Component: PromptForm takes the next command and walks the command history.
function PromptForm(props) {
  const [command, setCommand] = React.useState("");
  const history = React.useRef([]);
  const historyIndex = React.useRef(0);

  // Contract: Hand the typed command upward and remember it in the history.
  async function submit(event) {
    event.preventDefault();
    const submitted = command.trim();

    if (!submitted) {
      return;
    }

    setCommand("");
    history.current.push(submitted);
    historyIndex.current = history.current.length;
    await props.onSubmit(submitted);
  }

  // Contract: Walk the command history with the up and down arrow keys.
  function navigateHistory(event) {
    if (event.key !== "ArrowUp" && event.key !== "ArrowDown") {
      return;
    }

    if (history.current.length === 0) {
      return;
    }

    event.preventDefault();
    const step = event.key === "ArrowUp" ? -1 : 1;
    const bounded = Math.max(
      0,
      Math.min(history.current.length, historyIndex.current + step),
    );
    historyIndex.current = bounded;
    setCommand(history.current[bounded] || "");
  }

  return (
    <form className="prompt" onSubmit={submit}>
      <input
        autoComplete="off"
        autoCapitalize="off"
        spellCheck={false}
        placeholder="command"
        autoFocus
        value={command}
        onChange={(event) => setCommand(event.target.value)}
        onKeyDown={navigateHistory}
      />

      <button type="submit" disabled={props.busy}>
        {props.busy ? "..." : "Run"}
      </button>
    </form>
  );
}
