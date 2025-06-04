# Save as ~/.config/fish/scripts/ai_backend.py
import os
import subprocess
import argparse
import json
import re
import sqlite3
import platform
import shutil
import time
from pathlib import Path
from typing import Dict, List, Any

class AIMemory:
    def __init__(self):
        config_dir = Path.home() / ".config" / "ai_assistant"
        config_dir.mkdir(parents=True, exist_ok=True)
        self.memory_file = str(config_dir / "memory.db")
        self.init_database()
    
    def init_database(self):
        conn = sqlite3.connect(self.memory_file)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS command_history (
                id INTEGER PRIMARY KEY,
                command TEXT,
                success BOOLEAN,
                output TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                context TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS preferences (
                key TEXT PRIMARY KEY,
                value TEXT,
                frequency INTEGER DEFAULT 1
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS action_results (
                id INTEGER PRIMARY KEY,
                action_type TEXT,
                content TEXT,
                success BOOLEAN,
                error_msg TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def remember_command(self, command: str, success: bool, output: str = "", context: str = ""):
        conn = sqlite3.connect(self.memory_file)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO command_history (command, success, output, context) VALUES (?, ?, ?, ?)",
                      (command, success, output, context))
        conn.commit()
        conn.close()
    
    def remember_action_result(self, action_type: str, content: str, success: bool, error_msg: str = ""):
        conn = sqlite3.connect(self.memory_file)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO action_results (action_type, content, success, error_msg) VALUES (?, ?, ?, ?)",
                      (action_type, content, success, error_msg))
        conn.commit()
        conn.close()
    
    def get_recent_context(self, limit: int = 10) -> List[Dict]:
        conn = sqlite3.connect(self.memory_file)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT command, success, output, timestamp 
            FROM command_history 
            ORDER BY timestamp DESC 
            LIMIT ?
        """, (limit,))
        results = cursor.fetchall()
        conn.close()
        
        return [{"command": r[0], "success": bool(r[1]), "output": r[2], "timestamp": r[3]} for r in results]

class ContextGatherer:
    def __init__(self):
        self.memory = AIMemory()
    
    def gather_context(self, cwd: str, query: str, context_data: str = "") -> Dict[str, Any]:
        context = {
            'cwd': cwd,
            'files': self._get_files(cwd),
            'system': self._get_system_info(),
            'project_type': self._detect_project(cwd),
            'shell': os.environ.get('SHELL', '').split('/')[-1],
            'recent_context': self.memory.get_recent_context(5)
        }
        
        # Add provided context data (from previous commands)
        if context_data.strip():
            context['previous_outputs'] = context_data.strip()
        
        # Read specific files mentioned in query
        file_matches = re.findall(r'\b(\w+\.\w+)\b', query)
        for filename in file_matches:
            filepath = os.path.join(cwd, filename)
            if os.path.isfile(filepath):
                context[f'file_{filename}'] = self._read_file(filepath)
        
        return context
    
    def _get_files(self, cwd: str) -> List[str]:
        try:
            files = []
            for item in os.listdir(cwd):
                if not item.startswith('.'):
                    path = os.path.join(cwd, item)
                    if os.path.isfile(path):
                        size = os.path.getsize(path)
                        files.append(f"{item} ({size}B)")
                    else:
                        files.append(f"{item}/")
            return files[:15]  # Limit to 15 items
        except:
            return []
    
    def _get_system_info(self) -> Dict[str, Any]:
        return {
            'platform': platform.system(),
            'is_termux': 'com.termux' in os.environ.get('PREFIX', ''),
            'is_root': os.geteuid() == 0 if hasattr(os, 'geteuid') else False,
            'package_managers': [mgr for mgr in ['pkg', 'apt', 'pip3', 'npm'] if shutil.which(mgr)],
            'user': os.environ.get('USER', 'unknown'),
            'home': os.path.expanduser('~')
        }
    
    def _detect_project(self, cwd: str) -> str:
        project_files = {
            'package.json': 'nodejs',
            'requirements.txt': 'python',
            'pyproject.toml': 'python',
            'Cargo.toml': 'rust',
            'go.mod': 'go',
            'Makefile': 'c/cpp',
            'CMakeLists.txt': 'cmake',
            'config.fish': 'fish_config'
        }
        
        for file, ptype in project_files.items():
            if os.path.exists(os.path.join(cwd, file)):
                return ptype
        return 'general'
    
    def _read_file(self, filepath: str) -> str:
        try:
            if os.path.getsize(filepath) > 2048:
                return f"[Large file: {os.path.getsize(filepath)} bytes - showing first 1000 chars]\n" + \
                       open(filepath, 'r', encoding='utf-8', errors='ignore').read()[:1000]
            
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        except Exception as e:
            return f"[Error reading file: {str(e)}]"

def generate_completions(query: str, context: Dict) -> List[str]:
    """Generate command/query completions"""
    common_patterns = [
        "create a python script",
        "install package",
        "list files in",
        "search for",
        "fix the error",
        "configure",
        "update",
        "what is",
        "how to",
        "show me"
    ]
    
    # Filter based on current input
    if query:
        suggestions = [p for p in common_patterns if query.lower() in p.lower()]
        
        # Add context-specific suggestions
        if context.get('project_type') == 'python':
            suggestions.extend(["run python script", "install pip package", "create virtual environment"])
        elif context.get('project_type') == 'nodejs':
            suggestions.extend(["npm install", "run node script", "package.json"])
            
        # Add file-specific suggestions
        for file_info in context.get('files', []):
            if '.py' in file_info:
                suggestions.append(f"run {file_info.split()[0]}")
                
        return suggestions[:5]
    
    return common_patterns[:5]

def validate_file_content(content: str, file_type: str) -> str:
    """Validate and fix file content formatting"""
    if file_type in ['python', 'py']:
        # Ensure proper Python formatting
        lines = content.split('\\n')
        fixed_lines = []
        
        for line in lines:
            # Handle common issues
            if line.strip():
                fixed_lines.append(line)
            else:
                fixed_lines.append("")
        
        return '\\n'.join(fixed_lines)
    
    return content

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True)
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--context-data", default="")
    parser.add_argument("--fix-mode", action="store_true")
    parser.add_argument("--complete-mode", action="store_true")
    args = parser.parse_args()

    # Check API key
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print(json.dumps([{"type": "error", "content": "GOOGLE_API_KEY not set. Get one from https://makersuite.google.com/app/apikey"}]))
        return

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
    except ImportError:
        print(json.dumps([{"type": "error", "content": "Install: pip install google-generativeai"}]))
        return

    memory = AIMemory()
    context_gatherer = ContextGatherer()
    context = context_gatherer.gather_context(args.cwd, args.query, args.context_data)

    # Handle completion mode
    if args.complete_mode:
        suggestions = generate_completions(args.query, context)
        for suggestion in suggestions:
            print(suggestion)
        return

    # Handle fix mode
    if args.fix_mode:
        prompt = f"""Analyze this error and provide a concise fix:

ERROR: "{args.query}"
CONTEXT: {json.dumps(context, indent=2)}

Provide only a brief, actionable fix suggestion (1-2 sentences max)."""
        
        try:
            model = genai.GenerativeModel('gemini-2.0-flash-exp')
            response = model.generate_content(prompt)
            print(response.text.strip())
        except Exception as e:
            print(f"Error analysis failed: {str(e)}")
        return

    # Main AI processing
    prompt = f"""You are an autonomous AI assistant that helps with command-line tasks. 

CRITICAL REQUIREMENTS:
1. **File Content**: When writing files, use proper newline escaping (\\n) but ensure content is readable
2. **Status Awareness**: You can see previous command outputs - use this information to provide accurate status reports
3. **Error Handling**: Check actual results, don't assume success
4. **Context Usage**: Use provided context instead of running redundant commands

CONTEXT:
{json.dumps(context, indent=2)}

USER REQUEST: "{args.query}"

RESPONSE FORMAT: JSON array of actions

AVAILABLE ACTIONS:
- {{"type": "text", "content": "message to user"}}
- {{"type": "cmd", "command": "shell_command", "auto_execute": true, "use_output_for_next": false}}
- {{"type": "file", "path": "filepath", "content": "properly_escaped_content"}}
- {{"type": "config", "path": "config_path", "append": "content_to_append"}}
- {{"type": "install", "packages": ["pkg1", "pkg2"], "manager": "pkg"}}

IMPORTANT FILE WRITING RULES:
- Python files: Use \\n between statements, proper indentation
- Config files: Use \\n for line breaks
- Always include shebang for executable scripts
- Handle permission errors gracefully

EXAMPLES:

For "create python script hello.py":
[
  {{"type": "text", "content": "Creating a Python script that prints hello world."}},
  {{"type": "file", "path": "hello.py", "content": "#!/usr/bin/env python3\\n\\nprint(\\"Hello, World!\\")\\n"}}
]

For "install python packages for ML":
[
  {{"type": "text", "content": "Installing machine learning packages."}},
  {{"type": "install", "packages": ["numpy", "pandas", "scikit-learn"], "manager": "pip3"}}
]

For "what's in current directory":
[
  {{"type": "text", "content": "Current directory contains: {', '.join(context.get('files', []))}. This is a {context.get('project_type', 'general')} project."}}
]

Execute the request:"""

    try:
        model = genai.GenerativeModel('gemini-2.0-flash-exp')
        response = model.generate_content(prompt)
        
        # Clean response
        cleaned = response.text.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        
        try:
            actions = json.loads(cleaned.strip())
            
            # Validate and fix file contents
            for action in actions:
                if action.get('type') == 'file' and 'content' in action:
                    file_ext = action.get('path', '').split('.')[-1].lower()
                    action['content'] = validate_file_content(action['content'], file_ext)
                    
        except json.JSONDecodeError as e:
            # If JSON parsing fails, wrap response as text
            actions = [{"type": "text", "content": cleaned.strip()}]
        
        if not isinstance(actions, list):
            actions = [{"type": "error", "content": "Invalid response format"}]
        
        print(json.dumps(actions, ensure_ascii=False))

    except Exception as e:
        print(json.dumps([{"type": "error", "content": f"AI error: {str(e)}"}]))

if __name__ == "__main__":
    main()