"""File Operation Tools"""
import os
import shutil
from pathlib import Path
from .registry import Tool, registry

class ReadFile(Tool):
    def __init__(self):
        super().__init__(
            name="read_file",
            description="Read the contents of a file",
            parameters={
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to read",
                    "required": True
                }
            }
        )
    
    def execute(self, file_path: str) -> str:
        try:
            path = Path(file_path)
            if not path.exists():
                return f"File not found: {file_path}"
            
            if path.stat().st_size > 1_000_000:  # 1MB limit
                return "File too large (max 1MB)"
            
            content = path.read_text(encoding='utf-8')
            return content[:5000] + "..." if len(content) > 5000 else content
        except Exception as e:
            return f"Error reading file: {str(e)}"

class WriteFile(Tool):
    def __init__(self):
        super().__init__(
            name="write_file",
            description="Write content to a file (creates or overwrites)",
            permission="destructive",
            parameters={
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to write",
                    "required": True
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file",
                    "required": True
                }
            }
        )
    
    def execute(self, file_path: str, content: str) -> str:
        try:
            path = Path(file_path)
            path.parent.mkdir(parents=True, exist_ok=True)

            # Handle large content by writing in chunks
            max_chunk = 4000
            if len(content) > max_chunk:
                chunks = [content[i:i+max_chunk] for i in range(0, len(content), max_chunk)]
                with open(path, 'w', encoding='utf-8') as f:
                    for chunk in chunks:
                        f.write(chunk)
                return f"Successfully wrote {len(content)} chars to {file_path} (chunked)"
            else:
                path.write_text(content, encoding='utf-8')
                return f"Successfully wrote to {file_path}"
        except Exception as e:
            return f"Error writing file: {str(e)}"

class ListFiles(Tool):
    def __init__(self):
        super().__init__(
            name="list_files",
            description="List files and directories in a path",
            parameters={
                "path": {
                    "type": "string",
                    "description": "Directory path to list (default: current directory)",
                    "required": False
                }
            }
        )
    
    def execute(self, path: str = ".") -> str:
        try:
            p = Path(path)
            if not p.exists():
                return f"Directory not found: {path}"
            
            items = []
            for item in sorted(p.iterdir()):
                prefix = "📁 " if item.is_dir() else "📄 "
                size = item.stat().st_size if item.is_file() else 0
                items.append(f"{prefix}{item.name} ({size // 1024}KB)")
            
            return "\n".join(items) if items else "Empty directory"
        except Exception as e:
            return f"Error listing files: {str(e)}"

class CreateFolder(Tool):
    def __init__(self):
        super().__init__(
            name="create_folder",
            description="Create a new directory",
            permission="write",
            parameters={
                "folder_path": {
                    "type": "string",
                    "description": "Path of the folder to create",
                    "required": True
                }
            }
        )
    
    def execute(self, folder_path: str) -> str:
        try:
            Path(folder_path).mkdir(parents=True, exist_ok=True)
            return f"Created directory: {folder_path}"
        except Exception as e:
            return f"Error creating folder: {str(e)}"

# Register all tools
def register_tools():
    registry.register(ReadFile())
    registry.register(WriteFile())
    registry.register(ListFiles())
    registry.register(CreateFolder())
