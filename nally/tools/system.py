"""System Control Tools"""
import os
import subprocess
from .registry import Tool, registry

class RunCommand(Tool):
    def __init__(self):
        super().__init__(
            name="run_command",
            description="Execute a shell command on the system",
            permission="destructive",
            parameters={
                "command": {
                    "type": "string",
                    "description": "The command to execute",
                    "required": True
                }
            }
        )
    
    def execute(self, command: str) -> str:
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30
            )
            output = result.stdout
            if result.stderr:
                output += f"\nStderr: {result.stderr}"
            return output if output else "Command executed successfully"
        except subprocess.TimeoutExpired:
            return "Command timed out after 30 seconds"
        except Exception as e:
            return f"Error: {str(e)}"

class OpenApp(Tool):
    def __init__(self):
        super().__init__(
            name="open_app",
            description="Launch an application by name",
            parameters={
                "app_name": {
                    "type": "string",
                    "description": "Name of the application to open",
                    "required": True
                }
            }
        )
    
    def execute(self, app_name: str) -> str:
        try:
            os.startfile(app_name)
            return f"Opened {app_name}"
        except Exception as e:
            return f"Error opening {app_name}: {str(e)}"

class SetVolume(Tool):
    def __init__(self):
        super().__init__(
            name="set_volume",
            description="Set the system volume (0-100)",
            parameters={
                "level": {
                    "type": "integer",
                    "description": "Volume level from 0 to 100",
                    "required": True
                }
            }
        )
    
    def execute(self, level: int) -> str:
        try:
            level = max(0, min(100, level))
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = interface.QueryInterface(IAudioEndpointVolume)
            volume.SetMasterVolumeLevelScalar(level / 100.0, None)
            return f"Volume set to {level}%"
        except ImportError:
            return "Volume control requires: pip install pycaw comtypes"
        except Exception as e:
            return f"Error setting volume: {str(e)}"

class GetVolume(Tool):
    def __init__(self):
        super().__init__(
            name="get_volume",
            description="Get the current system volume level",
            parameters={}
        )
    
    def execute(self) -> str:
        try:
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = interface.QueryInterface(IAudioEndpointVolume)
            level = volume.GetMasterVolumeLevelScalar() * 100
            return f"Current volume: {int(level)}%"
        except ImportError:
            return "Volume control requires: pip install pycaw comtypes"
        except Exception as e:
            return f"Error getting volume: {str(e)}"

class GetSystemInfo(Tool):
    def __init__(self):
        super().__init__(
            name="get_system_info",
            description="Get system information (CPU, memory, disk usage)",
            parameters={}
        )
    
    def execute(self) -> str:
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            return f"""System Info:
- CPU Usage: {cpu}%
- Memory: {memory.percent}% used ({memory.used // (1024**3):.1f}GB / {memory.total // (1024**3):.1f}GB)
- Disk: {disk.percent}% used ({disk.used // (1024**3):.1f}GB / {disk.total // (1024**3):.1f}GB)"""
        except ImportError:
            return "System info requires: pip install psutil"
        except Exception as e:
            return f"Error getting system info: {str(e)}"

# Register only core tools (3 of 5)
def register_tools():
    registry.register(RunCommand())
    registry.register(OpenApp())
    registry.register(GetSystemInfo())
