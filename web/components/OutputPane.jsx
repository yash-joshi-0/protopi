// Component: OutputPane renders the command transcript and keeps it scrolled down.
function OutputPane(props) {
  const paneRef = React.useRef(null);

  React.useEffect(() => {
    const pane = paneRef.current;

    if (pane) {
      pane.scrollTop = pane.scrollHeight;
    }
  }, [props.lines]);

  return (
    <pre className="output" ref={paneRef}>
      {props.lines.map((line) => (
        <span key={line.key} className={line.className}>
          {line.text + "\n"}
        </span>
      ))}
    </pre>
  );
}
