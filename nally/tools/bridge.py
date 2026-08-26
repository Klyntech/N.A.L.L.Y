"""NallyBridge Tool — sends commands to connected bridge devices."""

import os

from .registry import Tool


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
                    "description": "Arguments for the tool. E.g. for run_command: {'command': 'dir'}. For file_ops: {'action': 'list', 'file_path': 'C:\\\\Users\\\\Desktop'}.",
                },
            },
            permission="safe",
        )

    def execute(self, device: str, tool: str, args=None) -> str:
        # Ensure args is a dict (LLM may pass it as a JSON string)
        if args is None:
            args = {}
        elif isinstance(args, str):
            import json
            try:
                args = json.loads(args)
            except (json.JSONDecodeError, TypeError):
                args = {}

        # Validate tool name
        allowed_tools = ["run_command", "file_ops", "read_file", "system_health"]
        if tool not in allowed_tools:
            return f"Error: Unsupported bridge tool: {tool}. Allowed: {', '.join(allowed_tools)}"

        # Import here to avoid circular imports at module level
        from ..web.bridge_handler import bridge_registry

        # Find device
        if device == "any":
            target = bridge_registry.find_device_for_tool(tool)
            if not target:
                return "Error: No bridge devices connected. Make sure NallyBridge is running and connected."
            device_id = target.device_id
        else:
            target = bridge_registry.get_device(device)
            if not target:
                # Try to find by suffix match
                for did, d in bridge_registry.devices.items():
                    if did.endswith(f":{device}") or did == device:
                        target = d
                        device_id = did
                        break
                else:
                    available = list(bridge_registry.devices.keys())
                    return (
                        f"Error: Bridge device '{device}' not connected. "
                        f"Available devices: {available if available else '(none)'}"
                    )
            device_id = device

        # Check tool is supported by this bridge
        if tool not in target.tools:
            return f"Error: Bridge '{device_id}' does not support tool '{tool}'. Available: {target.tools}"

        # Send request and wait for result — always use asyncio.run() since
        # this method runs inside a thread pool executor (no event loop present).
        import asyncio

        try:
            result, success = asyncio.run(
                bridge_registry.send_tool_request(device_id, tool, args)
            )
        except Exception as e:
            return f"Error communicating with bridge: {e}"

        return result


def register(registry):
    """Register the bridge tool."""
    registry.register(BridgeTool())
