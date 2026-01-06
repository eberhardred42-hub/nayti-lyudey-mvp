export async function sendClientEvent(event: string, props?: Record<string, unknown>) {
  try {
    await fetch("/api/events/client", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ event, props }),
    });
  } catch {
    // ignore
  }
}
