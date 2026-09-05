"""NallyBridge Tool — sends commands to connected bridge devices."""

from .registry import Tool
from .result import ToolResult


class BridgeTool(Tool):
    """Execute a command on a connected NallyBridge device."""

    def __init__(self):
        super().__init__(
            name="bridge_execute",
            description=(
                "Execute a command on a connected remote device via NallyBridge. "
                "The device must have NallyBridge running and connected. "
                "Supported tools: run_command, file_ops, read_file, system_health."
            ),
            parameters={
                "device": {
                    "type": "string",
                    "description": "Device name to execute on (e.g. 'desktop'). Use 'any' for first available.",
                },
                "tool": {
                    "type": "string",
                    "enum": ["run_command", "file_ops", "read_file", "system_health"],
                    "description": "Tool to execute on the bridge device.",
                },
                "args": {
                    "type": "object",
                    "description": (
                        "Arguments for the tool. E.g. for run_command: {'command': 'dir'}. "
                        "For file_ops: {'action': 'list', 'file_path': 'C:\\\\Users\\\\Desktop'}."
                    ),
                },
            },
            permission="safe",
        )

    def execute(self, device: str, tool: str, args=None):
        """Run a remote tool; preserve remote success as ToolResult.ok.

        The bridge WS protocol still returns (result, success). This method
        maps that tuple into ToolResult so the registry does not re-infer
        success from the result string alone.
        """
        # Ensure args is a dict (LLM may pass it as a JSON string)
        if args is None:
            args = {}
        elif isinstance(args, str):
            import json

            try:
                args = json.loads(args)
            except (json.JSONDecodeError, TypeError):
                args = {}

        allowed_tools = ["run_command", "file_ops", "read_file", "system_health"]
        if tool not in allowed_tools:
            return ToolResult.failure(
                error=(
                    f"Error: Unsupported bridge tool: {tool}. "
                    f"Allowed: {', '.join(allowed_tools)}"
                ),
                tool="bridge_execute",
            )

        # Import here to avoid circular imports at module level
        from ..web.bridge_handler import bridge_registry

        if device == "any":
            target = bridge_registry.find_device_for_tool(tool)
            if not target:
                return ToolResult.failure(
                    error=(
                        "Error: No bridge devices connected. "
                        "Make sure NallyBridge is running and connected."
                    ),
                    tool="bridge_execute",
                )
            device_id = target.device_id
        else:
            target = bridge_registry.get_device(device)
            if not target:
                for did, d in bridge_registry.devices.items():
                    if did.endswith(f":{device}") or did == device:
                        target = d
                        device_id = did
                        break
                else:
                    available = list(bridge_registry.devices.keys())
                    return ToolResult.failure(
                        error=(
                            f"Error: Bridge device '{device}' not connected. "
                            f"Available devices: {available if available else '(none)'}"
                        ),
                        tool="bridge_execute",
                    )
            else:
                device_id = device

        if tool not in target.tools:
            return ToolResult.failure(
                error=(
                    f"Error: Bridge '{device_id}' does not support tool '{tool}'. "
                    f"Available: {target.tools}"
                ),
                tool="bridge_execute",
            )

        # Always asyncio.run — this method runs inside a thread pool executor.
        import asyncio

        try:
            result, success = asyncio.run(
                bridge_registry.send_tool_request(device_id, tool, args)
            )
        except Exception as e:
            return ToolResult.failure(
                error=f"Error communicating with bridge: {e}",
                tool="bridge_execute",
                remote_tool=tool,
            )

        # Preserve remote success bit — do not drop it.
        if success:
            return ToolResult.success(
                value=result,
                tool="bridge_execute",
                remote_tool=tool,
                device=device_id,
            )

        err = result if str(result).lower().startswith("error") else f"Error: {result}"
        return ToolResult.failure(
            error=err,
            value=result,
            tool="bridge_execute",
            remote_tool=tool,
            device=device_id,
        )


def register(registry):
    """Register the bridge tool."""
    registry.register(BridgeTool())
