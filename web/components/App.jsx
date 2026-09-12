const ADMIN_PATH = "/admin";

// Component: App picks the page from the address the browser is showing.
function App() {
  if (window.location.pathname === ADMIN_PATH) {
    return <AdminPage />;
  }

  return <ChatPage />;
}
