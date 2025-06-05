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
from typing import Dict, List, Any, Optional

class SmartMemory:
    def __init__(self):
        config_dir = Path.home() / ".cache" / "ai_assistant"
        config_dir.mkdir(parents=True, exist_ok=True)
        self.memory_file = str(config_dir / "memory.db")
        self.init_db()
    
    def init_db(self):
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
        conn.commit()
        conn.close()
    
    def store_result(self, command: str, success: bool, output: str, context: str = ""):
        conn = sqlite3.connect(self.memory_file)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO command_history (command, success, output, context)
            VALUES (?, ?, ?, ?)
        """, (command, success, output, context))
        conn.commit()
        conn.close()
    
    def get_recent_context(self, limit: int = 5) -> List[Dict]:
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
        
        return [{
            "command": r[0], "success": bool(r[1]), 
            "output": r[2], "timestamp": r[3]
        } for r in results]

class ContextAnalyzer:
    def __init__(self):
        self.memory = SmartMemory()
    
    def analyze(self, cwd: str, query: str, context_file: str = "") -> Dict[str, Any]:
        context = {
            'cwd': cwd,
            'query': query,
            'environment': self._get_environment(cwd),
            'files': self._analyze_files(cwd),
            'git_repos': self._find_git_repos(cwd),
            'executables': self._find_executables(cwd),
            'recent_history': self.memory.get_recent_context(3),
            'intent': self._classify_intent(query)
        }
        
        # Load additional context
        if context_file and os.path.exists(context_file):
            try:
                with open(context_file, 'r') as f:
                    context['previous_context'] = f.read()
            except:
                pass
        
        # Load memory file
        memory_file = Path.home() / ".cache" / "ai_memory.txt"
        if memory_file.exists():
            try:
                with open(memory_file, 'r') as f:
                    context['user_memories'] = f.read()
            except:
                pass
        
        return context
    
    def _get_environment(self, cwd: str) -> Dict[str, Any]:
        env = {
            'platform': platform.system(),
            'is_termux': 'com.termux' in os.environ.get('PREFIX', ''),
            'cwd': cwd,
            'tools': {}
        }
        
        for tool in ['gcc', 'g++', 'python3', 'node', 'rustc', 'go', 'pkg', 'git']:
            if shutil.which(tool):
                env['tools'][tool] = True
        
        return env
    
    def _analyze_files(self, cwd: str) -> Dict[str, List]:
        files = {'source': [], 'executables': [], 'others': []}
        
        try:
            for item in os.listdir(cwd):
                item_path = os.path.join(cwd, item)
                if os.path.isfile(item_path):
                    ext = os.path.splitext(item)[1].lower()
                    size = os.path.getsize(item_path)
                    is_exec = os.access(item_path, os.X_OK)
                    
                    file_info = {'name': item, 'size': size, 'executable': is_exec}
                    
                    if ext in ['.c', '.cpp', '.py', '.sh', '.js', '.go', '.rs']:
                        file_info['type'] = ext[1:]
                        files['source'].append(file_info)
                    elif is_exec:
                        files['executables'].append(file_info)
                    else:
                        files['others'].append(file_info)
        except:
            pass
        
        return files
    
    def _find_git_repos(self, cwd: str) -> List[str]:
        repos = []
        try:
            for item in os.listdir(cwd):
                if os.path.isdir(os.path.join(cwd, item, '.git')):
                    repos.append(item)
        except:
            pass
        return repos
    
    def _find_executables(self, cwd: str) -> List[Dict]:
        executables = []
        try:
            for item in os.listdir(cwd):
                item_path = os.path.join(cwd, item)
                if os.path.isfile(item_path) and os.access(item_path, os.X_OK):
                    executables.append({
                        'name': item,
                        'path': item_path,
                        'size': os.path.getsize(item_path)
                    })
        except:
            pass
        return executables
    
    def _classify_intent(self, query: str) -> str:
        query_lower = query.lower()
        
        if any(word in query_lower for word in ['compile', 'build', 'make']):
            return 'compilation'
        elif any(word in query_lower for word in ['run', 'execute', 'start']):
            return 'execution'
        elif any(word in query_lower for word in ['remove', 'delete', 'rm']):
            return 'deletion'
        elif any(word in query_lower for word in ['install', 'setup']):
            return 'installation'
        elif any(word in query_lower for word in ['fix', 'debug', 'error']):
            return 'debugging'
        else:
            return 'general'

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True)
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--context-file", default="")
    args = parser.parse_args()

    # Check API key
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        error_msg = "GOOGLE_API_KEY not set. Get one from https://makersuite.google.com/app/apikey"
        print(json.dumps([{"type": "error", "content": error_msg}]))
        return

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
    except ImportError:
        print(json.dumps([{"type": "error", "content": "Run: pip3 install google-generativeai"}]))
        return

    analyzer = ContextAnalyzer()
    context = analyzer.analyze(args.cwd, args.query, args.context_file)

    # Optimized prompt for better execution handling
    prompt = f"""You are an advanced AI assistant with comprehensive system understanding.

CONTEXT:
{json.dumps(context, indent=2)}

USER QUERY: "{args.query}"
INTENT: {context.get('intent', 'general')}

AVAILABLE ACTIONS:
- {{"type": "text", "content": "message"}}
- {{"type": "cmd", "command": "shell_command", "auto_execute": true/false}}
- {{"type": "run", "executable": "program", "args": "arguments", "background": true/false}}
- {{"type": "file", "path": "filepath", "content": "content_with_\\n_newlines"}}
- {{"type": "compile_run", "source": "file.c", "compile_command": "gcc file.c -o program", "run_command": "./program"}}
- {{"type": "install", "packages": ["pkg1"], "manager": "pkg"}}

EXECUTION RULES:

**For Interactive/GUI Programs (C spinning donut, Python animations, games):**
- Use "run" action with background=false for terminal programs
- Use "run" action with background=true for GUI applications
- Always make executables runnable before executing
- For C programs: compile first, then run the executable

**For Flask/Web Apps:**
- Use "cmd" action for starting servers
- Set auto_execute=false for user confirmation
- Include proper startup commands

**For Package Installation:**
- Analyze previous context to understand available packages
- Use appropriate package manager (pkg for Termux)
- Install dependencies intelligently

**Safety:**
- Always verify dangerous operations
- Use proper paths and executable permissions
- Handle compilation errors gracefully

EXAMPLES:

Run C donut program:
[
  {{"type": "compile_run", "source": "donut.c", "compile_command": "gcc donut.c -o donut -lm", "run_command": "./donut"}},
  {{"type": "text", "content": "Donut animation should be running in your terminal!"}}
]

Run Python script:
[
  {{"type": "run", "executable": "python3", "args": "script.py", "background": false}}
]

Start Flask app:
[
  {{"type": "cmd", "command": "python3 app.py", "auto_execute": false}}
]

Install ML packages:
[
  {{"type": "install", "packages": ["numpy", "scipy", "scikit-learn"], "manager": "pip3"}}
]

Execute based on context and intent:"""

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
        except json.JSONDecodeError:
            actions = [{"type": "text", "content": cleaned.strip()}]
        
        if not isinstance(actions, list):
            actions = [{"type": "error", "content": "Invalid response format"}]
        
        # Validate actions
        for action in actions:
            if action.get('type') == 'file' and 'content' in action:
                content = action['content']
                if content and not content.endswith('\\n'):
                    action['content'] = content + '\\n'
        
        print(json.dumps(actions, ensure_ascii=False))

    except Exception as e:
        print(json.dumps([{"type": "error", "content": f"AI error: {str(e)}"}]))

if __name__ == "__main__":
    main()