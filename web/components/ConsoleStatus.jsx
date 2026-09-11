// Component: ConsoleStatus shows the hotspot state beside the console title.
function ConsoleStatus(props) {
  const session = props.session;
  const parts = [
    session.ssid,
    "ap " + (session.access_point_active ? "up" : "off"),
    "clients " + session.station_count,
    "timeout " + session.command_timeout_seconds + "s",
  ];

  return <span className="meta">{parts.join(" · ")}</span>;
}
