// Component: AdminPage shows the login card until signed in, then the console.
function AdminPage() {
  const [session, setSession] = React.useState(null);
  const [failure, setFailure] = React.useState("");

  // Contract: Ask the server which session, if any, this browser still holds.
  function refreshSession() {
    readSession().then(setSession, (error) =>
      setFailure("Console unreachable: " + error),
    );
  }

  React.useEffect(refreshSession, []);

  if (failure) {
    return (
      <main className="card login">
        <p className="error">{failure}</p>
      </main>
    );
  }

  if (session === null) {
    return (
      <main className="card login">
        <p className="meta">Loading...</p>
      </main>
    );
  }

  if (!session.authenticated) {
    return <LoginCard session={session} onSignedIn={setSession} />;
  }

  return <ConsoleCard session={session} onSignedOut={refreshSession} />;
}
