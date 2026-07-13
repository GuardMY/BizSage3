/**
 * BizSage3 — SSE (Server-Sent Events) consumer.
 *
 * Parses the text/event-stream protocol from a fetch Response body
 * (ReadableStream) and dispatches structured events via a callback.
 *
 * Handles:
 *   - Standard SSE lines (event:, data:, id:, retry:)
 *   - Multi-line data payloads (multiple sequential "data:" lines)
 *   - Comments (lines starting with ":")
 *   - UTF-8 decoding
 */

export interface SSEEvent {
  event: string;
  data: string;
}

/**
 * Consume an SSE stream from a fetch Response.
 *
 * Calls `onEvent` for each parsed event block (separated by blank lines in
 * the wire format).  Returns when the stream ends or errors.
 */
export async function consumeSSE(
  response: Response,
  onEvent: (event: SSEEvent) => void,
): Promise<void> {
  if (!response.body) {
    throw new Error("Response body is null — cannot read SSE stream");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");

  let buffer = "";
  let currentEvent = "";
  let currentData = "";
  let done = false;

  const dispatch = () => {
    if (currentData !== "") {
      // Trim trailing newline from data (standard SSE convention)
      const trimmed = currentData.endsWith("\n")
        ? currentData.slice(0, -1)
        : currentData;
      onEvent({ event: currentEvent || "message", data: trimmed });
    }
    currentEvent = "";
    currentData = "";
  };

  while (!done) {
    const { value, done: streamDone } = await reader.read();
    done = streamDone;

    if (value) {
      buffer += decoder.decode(value, { stream: !done });
    }

    // Process complete lines from the buffer
    const lines = buffer.split("\n");
    // Keep the last (possibly incomplete) fragment in the buffer
    buffer = lines.pop() || "";

    for (const rawLine of lines) {
      const line = rawLine.trimEnd();

      if (line === "") {
        // Empty line — dispatch the current event
        dispatch();
        continue;
      }

      if (line.startsWith(":")) {
        // SSE comment — skip
        continue;
      }

      if (line.startsWith("event:")) {
        currentEvent = line.slice(6).trim();
        continue;
      }

      if (line.startsWith("data:")) {
        const chunk = line.slice(5);
        // Handle "data: " (space after colon) vs "data:" (no space)
        const dataLine = chunk.startsWith(" ") ? chunk.slice(1) : chunk;
        currentData += dataLine + "\n";
        continue;
      }

      if (line.startsWith("id:")) {
        // We don't use event IDs for this consumer — just skip
        continue;
      }

      if (line.startsWith("retry:")) {
        // Reconnection interval — not applicable in our usage
        continue;
      }

      // Unknown field — ignore per SSE spec
    }
  }

  // Dispatch any remaining event after stream end
  dispatch();
}
