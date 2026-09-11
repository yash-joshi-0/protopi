// Component: LoginCard collects the admin credentials and starts a session.
function LoginCard(props) {
  const [username, setUsername] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [message, setMessage] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  // Contract: Submit the credentials and hand a new session up to the app.
  async function submit(event) {
    event.preventDefault();
    setBusy(true);

    try {
      const result = await sendJson("/login", {
        username: username,
        password: password,
      });

      if (result.status === 200) {
        props.onSignedIn(result.payload);
        return;
      }

      setMessage(result.payload.error || "Sign in failed.");
    } catch (error) {
      setMessage("Console unreachable: " + error);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="card login">
      <h1>PROTOPI ADMIN</h1>
      <p className="meta">{props.session.ssid}</p>

      <form onSubmit={submit}>
        <label htmlFor="username">Username</label>
        <input
          id="username"
          autoComplete="username"
          autoFocus
          value={username}
          onChange={(event) => setUsername(event.target.value)}
        />

        <label htmlFor="password">Password</label>
        <input
          id="password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />

        <button className="primary" type="submit" disabled={busy}>
          {busy ? "Signing in..." : "Sign in"}
        </button>
      </form>

      {message ? <p className="error">{message}</p> : null}
    </main>
  );
}
