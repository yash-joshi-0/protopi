const CONSOLE_INTRO = "Type a command and press Enter. Arrow keys walk the history.";
const CLEAR_COMMAND = "clear";

// Component: ConsoleCard runs commands for a signed-in session.
function ConsoleCard(props) {
  const session = props.session;
  const [lines, setLines] = React.useState([
    { key: 0, text: CONSOLE_INTRO, className: "meta" },
  ]);
  const [workingDirectory, setWorkingDirectory] = React.useState(
    session.working_directory,
  );
  const [busy, setBusy] = React.useState(false);
  const nextKey = React.useRef(1);

  // Contract: Append one line to the transcript.
  function appendLine(text, className) {
    const key = nextKey.current;
    nextKey.current += 1;
    setLines((previous) =>
      previous.concat({ key: key, text: text, className: className }),
    );
  }

  // Contract: Run one command and show its output, exit code, and directory.
  async function runCommand(submitted) {
    appendLine("$ " + submitted, "echo");
    setBusy(true);

    try {
      const result = await sendJson(
        "/run",
        { command: submitted },
        session.csrf_token,
      );

      if (result.status === 401) {
        appendLine("Session expired.", "failure");
        props.onSignedOut();
        return;
      }

      if (result.payload.error) {
        appendLine(result.payload.error, "failure");
        return;
      }

      if (result.payload.output) {
        appendLine(result.payload.output.replace(/\n$/, ""), null);
      }

      if (result.payload.exit_code !== 0) {
        appendLine("[exit " + result.payload.exit_code + "]", "failure");
      }

      setWorkingDirectory(result.payload.working_directory);
    } catch (error) {
      appendLine("Console unreachable: " + error, "failure");
    } finally {
      setBusy(false);
    }
  }

  // Contract: Clear the transcript locally, or send the command to the Pi.
  async function handleCommand(submitted) {
    if (submitted === CLEAR_COMMAND) {
      setLines([]);
      return;
    }

    await runCommand(submitted);
  }

  // Contract: End the session on the server and return to the login card.
  async function signOut() {
    try {
      await sendJson("/logout", {}, session.csrf_token);
    } catch (error) {
      appendLine("Sign out failed: " + error, "failure");
    }

    props.onSignedOut();
  }

  return (
    <main className="card">
      <header>
        <h1>PROTOPI CONSOLE</h1>
        <ConsoleStatus session={session} />
        <button type="button" onClick={signOut}>
          Sign out
        </button>
      </header>

      <OutputPane lines={lines} />
      <div className="working-directory">{workingDirectory}</div>
      <PromptForm busy={busy} onSubmit={handleCommand} />
    </main>
  );
}
