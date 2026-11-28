// SPM Studio Agent Hub — approval gate for Pi (loaded with `pi -e spm-hub-gate.ts` when full access is off).
//
// Before every tool call that can change something (bash, write, edit, and tools of other extensions) Pi asks
// the Agent Hub through a confirm dialog. The hub answers at once when its access settings allow the action
// (SPM Studio folders, read-only commands, "Always allow" answers); otherwise it shows Allow / Always allow /
// Deny to the user. Reading tools never ask.

const READ_ONLY = new Set(["read", "grep", "find", "ls"]);

export default function (pi: any) {
  pi.on("tool_call", async (event: any, ctx: any) => {
    const name = String(event?.toolName ?? "");
    if (READ_ONLY.has(name)) return undefined;
    if (!ctx?.ui?.confirm) return undefined;
    let payload = "{}";
    try {
      payload = JSON.stringify({ tool: name, input: event?.input ?? {} });
    } catch {
      payload = JSON.stringify({ tool: name, input: {} });
    }
    const ok = await ctx.ui.confirm("spm-hub-approval", payload);
    if (!ok) {
      return {
        block: true,
        reason:
          "Not allowed by the user or by SPM Studio's access settings. Tell the user what you wanted to do and " +
          "why; they can allow it or widen the access in Agent Hub › Settings › Access.",
      };
    }
    return undefined;
  });
}
