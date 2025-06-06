#!/usr/bin/env python3
"""
AI Terminal Assistant Backend for Termux
Place in ~/.config/fish/scripts/backend.py
"""

import os, sys, json, subprocess, requests, time, threading, shutil, re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

class Colors:
    CYAN, GREEN, YELLOW, RED, BOLD, END = '\033[96m', '\033[92m', '\033[93m', '\033[91m', '\033[1m', '\033[0m'

class AIAssistant:
    def __init__(self, initial_dir=None):
        self.openrouter_key = os.getenv('OPENROUTER_API_KEY')
        self.gemini_key = os.getenv('GEMINI_API_KEY')
        self.home_dir = os.path.expanduser('~')
        
        # Use passed directory or current directory
        if initial_dir and os.path.exists(initial_dir):
            self.working_dir = os.path.abspath(initial_dir)
        else:
            self.working_dir = os.getcwd()
        
        # Fix working directory if in restricted area
        restricted = ['/system', '/proc', '/dev', '/sys', '/root']
        if any(self.working_dir.startswith(p) for p in restricted):
            self.working_dir = self.home_dir
            
        # Always change to working directory
        os.chdir(self.working_dir)
        self.print_color(f"📂 Working in: {self.working_dir}", Colors.CYAN)
        
        self.load_preferences()
        
    def load_preferences(self):
        self.preferences = {}
        try:
            config_path = os.path.join(self.home_dir, '.config', 'fish', 'ai_config.json')
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    self.preferences = json.load(f).get('prefs', {})
        except: pass
        
    def print_color(self, text: str, color: str = Colors.END):
        print(f"{color}{text}{Colors.END}")
        
    def scan_directory(self, path: str = None) -> Dict:
        if path is None: path = self.working_dir
        try:
            result = {
                'current_dir': path, 'files': [], 'dirs': [], 'code_files': [],
                'package_files': [], 'executables': [], 'python_files': [],
                'is_git': False, 'git_status': None, 'total_files': 0
            }
            
            # Check git repository
            if os.path.exists(os.path.join(path, '.git')):
                result['is_git'] = True
                try:
                    git_cmd = subprocess.run(['git', 'status', '--porcelain'], 
                                           capture_output=True, text=True, cwd=path, timeout=5)
                    if git_cmd.returncode == 0:
                        result['git_status'] = git_cmd.stdout.strip()
                except: pass

            # Scan files
            for item in os.listdir(path):
                if item.startswith('.'): continue
                item_path = os.path.join(path, item)
                
                if os.path.isfile(item_path):
                    result['files'].append(item)
                    result['total_files'] += 1
                    
                    # Check if executable
                    if os.access(item_path, os.X_OK):
                        result['executables'].append(item)
                    
                    # Categorize files
                    if item in ['requirements.txt', 'package.json', 'Pipfile', 'pyproject.toml', 'Cargo.toml', 'Makefile']:
                        result['package_files'].append(item)
                    elif item.endswith('.py'):
                        result['python_files'].append(item)
                    elif item.endswith(('.js', '.java', '.cpp', '.c', '.go', '.rs', '.php', '.html')):
                        result['code_files'].append(item)
                elif os.path.isdir(item_path):
                    result['dirs'].append(item)
                    
            return result
        except Exception as e:
            return {'error': str(e), 'current_dir': path}

    def check_file_exists(self, filename: str) -> Tuple[bool, str]:
        """Check if file exists and return full path"""
        # Check in current directory
        current_path = os.path.join(self.working_dir, filename)
        if os.path.exists(current_path):
            return True, current_path
            
        # Check without extension for executables
        if '.' not in filename:
            exec_path = os.path.join(self.working_dir, filename)
            if os.path.exists(exec_path) and os.access(exec_path, os.X_OK):
                return True, exec_path
                
        return False, ""

    def create_file_with_content(self, filename: str, content: str) -> bool:
        """Create a file with content, handling large files properly"""
        try:
            # Use absolute path
            filepath = os.path.join(self.working_dir, filename)
            
            # Write content directly to file
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            
            self.print_color(f"📝 Created {filename} ({len(content)} chars)", Colors.GREEN)
            
            # Make executable if it's a script
            if filename.endswith(('.sh', '.py')) or not '.' in filename:
                os.chmod(filepath, 0o755)
                
            return True
        except Exception as e:
            self.print_color(f"❌ Failed to create {filename}: {e}", Colors.RED)
            return False

    def safe_change_directory(self, target_dir: str) -> bool:
        """Safely change directory with proper validation"""
        try:
            # Handle relative paths
            if not os.path.isabs(target_dir):
                target_dir = os.path.join(self.working_dir, target_dir)
            
            # Normalize path
            target_dir = os.path.abspath(target_dir)
            
            # Check if directory exists
            if not os.path.exists(target_dir):
                self.print_color(f"❌ Directory does not exist: {target_dir}", Colors.RED)
                return False
                
            if not os.path.isdir(target_dir):
                self.print_color(f"❌ Not a directory: {target_dir}", Colors.RED)
                return False
            
            # Change directory
            os.chdir(target_dir)
            self.working_dir = target_dir
            self.print_color(f"📂 Changed to: {self.working_dir}", Colors.CYAN)
            return True
            
        except Exception as e:
            self.print_color(f"❌ Failed to change directory: {e}", Colors.RED)
            return False

    def execute_command(self, command: str) -> Tuple[int, str, str]:
        try:
            # Pre-process command for better execution
            original_command = command
            
            # Handle directory operations more safely
            if ' && cd ' in command or command.startswith('cd '):
                return self.handle_directory_operations(command)
            
            # Handle file creation with heredoc
            if '<<' in command and 'EOF' in command:
                return self.handle_heredoc_creation(command)
            
            # Fix GCC compilation
            if 'gcc ' in command and '.c' in command:
                command = self.fix_gcc_command(command)
            
            # Handle executable files (check if they exist first)
            if command.startswith('./'):
                exec_name = command.split()[0][2:]  # Remove ./
                exists, full_path = self.check_file_exists(exec_name)
                if not exists:
                    return 1, "", f"Executable '{exec_name}' not found in {self.working_dir}"
                # Make sure it's executable
                os.chmod(full_path, 0o755)
                
            # Handle Python files
            elif command.startswith('python ') or command.startswith('python3 '):
                parts = command.split()
                if len(parts) > 1:
                    python_file = parts[1]
                    exists, full_path = self.check_file_exists(python_file)
                    if not exists:
                        return 1, "", f"Python file '{python_file}' not found in {self.working_dir}"
            
            # Fix GUI commands for Termux
            gui_commands = ['xdg-open', 'open', 'start']
            for gui_cmd in gui_commands:
                if gui_cmd in command:
                    if shutil.which('termux-open'):
                        command = command.replace(gui_cmd, 'termux-open')
                    else:
                        return 1, "", "Install termux-tools: pkg install termux-tools"
            
            self.print_color(f"🔧 Executing: {command}", Colors.CYAN)
            self.print_color(f"📍 In directory: {self.working_dir}", Colors.YELLOW)
            
            # Execute command with proper environment
            env = os.environ.copy()
            env['PWD'] = self.working_dir
            
            # Special handling for interactive/animation programs
            is_interactive = any(cmd in command for cmd in ['./donut', './snake', './game', 'python3 calculator.py', 'python3 game'])
            
            if is_interactive:
                self.print_color("🎮 Running interactive program...", Colors.GREEN)
                self.print_color("Press Ctrl+C to stop", Colors.YELLOW)
                
                # Run without capturing output for real-time display
                try:
                    result = subprocess.run(
                        command,
                        shell=True,
                        cwd=self.working_dir,
                        env=env,
                        timeout=60  # Shorter timeout for animations
                    )
                    return result.returncode, "Interactive program completed", ""
                except subprocess.TimeoutExpired:
                    return 0, "Animation stopped after 60 seconds", ""
                except KeyboardInterrupt:
                    return 0, "Program interrupted by user", ""
            else:
                # Normal execution with output capture
                result = subprocess.run(
                    command, 
                    shell=True, 
                    capture_output=True, 
                    text=True,
                    cwd=self.working_dir, 
                    timeout=300,
                    env=env
                )
                
                # Log execution details
                if result.returncode != 0:
                    self.print_color(f"❌ Command failed with exit code: {result.returncode}", Colors.RED)
                    if result.stderr:
                        self.print_color(f"Error details: {result.stderr[:500]}", Colors.RED)
                
                return result.returncode, result.stdout, result.stderr
            
        except subprocess.TimeoutExpired:
            return 1, "", "Command timed out after 5 minutes"
        except FileNotFoundError as e:
            return 1, "", f"Command not found: {str(e)}"
        except Exception as e:
            return 1, "", f"Execution error: {str(e)}"

    def handle_directory_operations(self, command: str) -> Tuple[int, str, str]:
        """Handle directory creation and navigation safely"""
        try:
            if ' && cd ' in command:
                parts = command.split(' && ')
                for part in parts:
                    part = part.strip()
                    if part.startswith('mkdir '):
                        dir_name = part.replace('mkdir -p ', '').replace('mkdir ', '').strip()
                        # Use absolute path
                        if not os.path.isabs(dir_name):
                            dir_name = os.path.join(self.working_dir, dir_name)
                        os.makedirs(dir_name, exist_ok=True)
                        self.print_color(f"📁 Created directory: {dir_name}", Colors.GREEN)
                    elif part.startswith('cd '):
                        dir_name = part.replace('cd ', '').strip()
                        if not self.safe_change_directory(dir_name):
                            return 1, "", f"Failed to change to directory {dir_name}"
                    else:
                        # Execute other commands in the current directory
                        result = subprocess.run(part, shell=True, capture_output=True, text=True, 
                                              cwd=self.working_dir, timeout=300)
                        if result.stdout: print(result.stdout)
                        if result.stderr: print(result.stderr)
                        if result.returncode != 0:
                            return result.returncode, result.stdout, result.stderr
                return 0, "Directory operations completed", ""
            elif command.startswith('cd '):
                dir_name = command.replace('cd ', '').strip()
                if self.safe_change_directory(dir_name):
                    return 0, f"Changed to {self.working_dir}", ""
                else:
                    return 1, "", f"Failed to change to directory {dir_name}"
        except Exception as e:
            return 1, "", f"Directory operation error: {str(e)}"

    def handle_heredoc_creation(self, command: str) -> Tuple[int, str, str]:
        """Handle heredoc file creation (cat > file << EOF)"""
        try:
            # Parse heredoc command
            if 'cat >' in command and '<<' in command:
                parts = command.split('<<')
                if len(parts) >= 2:
                    file_part = parts[0].strip()
                    filename = file_part.replace('cat >', '').strip()
                    
                    # Get content between EOF markers (this should be handled by the AI response parser)
                    # For now, just create an empty file and let the next command fill it
                    filepath = os.path.join(self.working_dir, filename)
                    with open(filepath, 'w') as f:
                        f.write("")  # Empty file for now
                    
                    self.print_color(f"📝 Created {filename} (ready for content)", Colors.GREEN)
                    return 0, f"Created {filename}", ""
            
            # Execute as normal command if not a standard heredoc
            result = subprocess.run(command, shell=True, capture_output=True, text=True,
                                  cwd=self.working_dir, timeout=60)
            return result.returncode, result.stdout, result.stderr
            
        except Exception as e:
            return 1, "", f"Heredoc creation error: {str(e)}"

    def fix_gcc_command(self, command: str) -> str:
        """Fix GCC compilation command"""
        if '-lm' not in command:
            # Check if C file uses math functions
            c_files = [f for f in command.split() if f.endswith('.c')]
            for c_file in c_files:
                c_file_path = os.path.join(self.working_dir, c_file)
                if os.path.exists(c_file_path):
                    try:
                        with open(c_file_path, 'r') as f:
                            content = f.read()
                            if any(x in content for x in ['#include <math.h>', 'sin(', 'cos(', 'sqrt(', 'pow(']):
                                command = command.replace('gcc ', 'gcc -lm ')
                                break
                    except:
                        pass
        return command

    def web_scrape(self, url: str, query: str = "") -> str:
        """Simple web scraping functionality"""
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Android; Mobile; rv:40.0) Gecko/40.0 Firefox/40.0'}
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            # Simple text extraction
            text = response.text
            if query:
                # Find relevant sections containing the query
                lines = text.split('\n')
                relevant = [line.strip() for line in lines if query.lower() in line.lower()]
                return '\n'.join(relevant[:10])  # First 10 relevant lines
            
            return text[:2000]  # First 2000 chars
        except Exception as e:
            return f"Scraping error: {e}"

    def search_packages(self, search_term: str) -> List[str]:
        """Search for packages using pkg"""
        try:
            # Search available packages
            result = subprocess.run(f"pkg list-all | grep -i {search_term} | head -10", 
                                  shell=True, capture_output=True, text=True, timeout=10)
            if result.returncode == 0 and result.stdout:
                return result.stdout.strip().split('\n')[:5]
            return []
        except:
            return []

    def call_ai_api(self, prompt: str) -> Optional[str]:
        # Try OpenRouter first
        if self.openrouter_key:
            try:
                response = requests.post("https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self.openrouter_key}", "Content-Type": "application/json"},
                    json={"model": "google/gemini-2.0-flash-lite-001", "messages": [{"role": "user", "content": prompt}], 
                          "max_tokens": 1500, "temperature": 0.3}, timeout=30)
                if response.status_code == 200:
                    return response.json()["choices"][0]["message"]["content"]
            except: pass
                
        # Try Gemini
        if self.gemini_key:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={self.gemini_key}"
                response = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}], 
                                       "generationConfig": {"temperature": 0.3, "maxOutputTokens": 1500}}, timeout=30)
                if response.status_code == 200:
                    result = response.json()
                    return result['candidates'][0]['content']['parts'][0]['text']
            except: pass
                
        self.print_color("❌ No API keys configured. Set OPENROUTER_API_KEY or GEMINI_API_KEY", Colors.RED)
        return None

    def create_prompt(self, user_request: str) -> str:
        dir_info = self.scan_directory()
        git_info = ""
        if dir_info.get('is_git'):
            git_info = f"Git Repository: Yes\nGit Status: {dir_info.get('git_status', 'Clean')[:100]}\n"
        
        exec_info = ""
        if dir_info.get('executables'):
            exec_info = f"Executables: {', '.join(dir_info.get('executables', []))}\n"
            
        python_info = ""
        if dir_info.get('python_files'):
            python_info = f"Python Files: {', '.join(dir_info.get('python_files', []))}\n"
        
        return f"""You are an AI assistant for Termux on Android. Execute user requests with precise commands.

Request: {user_request}

Current Environment:
- Directory: {dir_info.get('current_dir')}
- Files ({dir_info.get('total_files', 0)}): {', '.join(dir_info.get('files', [])[:10])}
- Code: {', '.join(dir_info.get('code_files', []))}
- Configs: {', '.join(dir_info.get('package_files', []))}
{exec_info}{python_info}{git_info}

CRITICAL FILE CREATION RULES:
1. For LARGE C files (>50 lines): Use "file_create" type, NOT echo or cat commands
2. For multiline content: NEVER use echo with \\n - use "file_create" type instead
3. For shell escapes: Avoid complex quoting - use "file_create" for any content with quotes/escapes

CRITICAL DIRECTORY RULES:
1. ALWAYS use absolute paths or verify cd operations
2. For "cd .." or "cd dirname": Use absolute path format
3. Before running commands after cd: Verify directory change worked
4. Use "mkdir -p /absolute/path && cd /absolute/path" format

CRITICAL COMPILATION RULES:
1. After creating C files: ALWAYS compile with "gcc filename.c -o filename"
2. After compilation: ALWAYS test executable with "./filename"
3. For math functions: gcc automatically adds -lm when needed
4. Check compilation errors and fix before execution

EXECUTION PRIORITY:
- If user says "execute donut" and donut exists → run "./donut"
- If user says "run calculator" and calculator.py exists → run "python3 calculator.py"
- If files don't exist, create them first with "file_create" type
- NEVER skip compilation step for C files
- ALWAYS verify file existence in your analysis

For animations/programs: Create complete working code using "file_create", compile if needed, then execute
For git operations: Check if directory is git repo first
For web scraping: Use Python with requests library

Respond with JSON:
{{
    "analysis": "What you'll do (mention file creation method)",
    "steps": [
        {{"description": "Step description", "command": "exact command", "type": "command|file_create|git|info", "filename": "file.c", "content": "full file content"}}
    ],
    "summary": "Brief summary"
}}

Step Types:
- "command": Execute shell command
- "file_create": Create file with content (use for large files, multiline content)
- "git": Git operations
- "info": Information display

IMPORTANT: Use "file_create" type for ANY file >30 lines or with complex content. The system will handle file creation properly."""

    def parse_response(self, response: str) -> Dict:
        try:
            # Clean up response to extract JSON
            response_clean = response.strip()
            
            # Try to find JSON block
            json_match = re.search(r'\{.*\}', response_clean, re.DOTALL)
            if json_match:
                json_str = json_match.group()
                return json.loads(json_str)
            
            # If no JSON found, create a simple command structure
            return {
                "analysis": "Direct execution", 
                "steps": [{"description": response_clean, "command": response_clean, "type": "command"}], 
                "summary": "Command execution"
            }
        except Exception as e:
            self.print_color(f"⚠️  JSON parse error: {e}", Colors.YELLOW)
            return {
                "analysis": "Text response", 
                "steps": [{"description": response, "command": "", "type": "info"}], 
                "summary": response[:100]
            }

    def execute_step(self, step: Dict) -> bool:
        step_type = step.get('type', 'command')
        description = step.get('description', '')
        command = step.get('command', '')
        
        self.print_color(f"\n📋 {description}", Colors.YELLOW)
        
        if step_type == 'file_create':
            # Handle file creation
            filename = step.get('filename', '')
            content = step.get('content', '')
            if filename and content:
                return self.create_file_with_content(filename, content)
            else:
                self.print_color("❌ Missing filename or content for file creation", Colors.RED)
                return False
                
        elif step_type == 'info':
            self.print_color(f"ℹ️  {command or description}", Colors.CYAN)
            return True
        elif command:
            # Pre-execution checks
            if command.startswith('./'):
                exec_name = command.split()[0][2:]
                exists, _ = self.check_file_exists(exec_name)
                if not exists:
                    self.print_color(f"❌ Executable '{exec_name}' not found", Colors.RED)
                    return False
                    
            elif 'python3 ' in command:
                parts = command.split()
                for i, part in enumerate(parts):
                    if part.endswith('.py'):
                        exists, _ = self.check_file_exists(part)
                        if not exists:
                            self.print_color(f"❌ Python file '{part}' not found", Colors.RED)
                            return False
                        break
            
            return_code, stdout, stderr = self.execute_command(command)
            
            if stdout: 
                self.print_color("✓ Output:", Colors.GREEN)
                print(stdout)
            if stderr and return_code != 0:
                self.print_color("❌ Error:", Colors.RED)
                print(stderr)
            elif stderr:
                self.print_color("⚠ Warnings:", Colors.YELLOW)
                print(stderr)
                
            return return_code == 0
        return True

    def process_request(self, user_request: str):
        self.print_color(f"🎯 Processing: {user_request}", Colors.BOLD)
        
        # Quick file existence check for execution requests
        if any(word in user_request.lower() for word in ['execute', 'run', 'start']):
            dir_info = self.scan_directory()
            self.print_color(f"📁 Found {len(dir_info.get('files', []))} files in current directory", Colors.CYAN)
            if dir_info.get('executables'):
                self.print_color(f"🔧 Executables: {', '.join(dir_info['executables'])}", Colors.GREEN)
            if dir_info.get('python_files'):
                self.print_color(f"🐍 Python files: {', '.join(dir_info['python_files'])}", Colors.GREEN)
        
        # Thinking animation
        def animate():
            chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
            for i in range(15):
                print(f"\r{Colors.CYAN}🧠 Analyzing {chars[i % len(chars)]}{Colors.END}", end="", flush=True)
                time.sleep(0.1)
            print(f"\r{Colors.GREEN}🧠 Analysis complete!{Colors.END}")
            
        threading.Thread(target=animate).start()
        time.sleep(1.5)
        
        # Get AI response
        prompt = self.create_prompt(user_request)
        ai_response = self.call_ai_api(prompt)
        
        if not ai_response:
            return
            
        # Execute plan
        try:
            plan = self.parse_response(ai_response)
            if 'analysis' in plan:
                self.print_color(f"\n🔍 {plan['analysis']}", Colors.CYAN)
                
            if 'steps' in plan:
                self.print_color(f"\n🚀 Executing {len(plan['steps'])} steps:", Colors.BOLD)
                success = 0
                for i, step in enumerate(plan['steps'], 1):
                    self.print_color(f"\n--- Step {i}/{len(plan['steps'])} ---", Colors.BOLD)
                    if self.execute_step(step): 
                        success += 1
                    else:
                        self.print_color(f"⚠️  Step {i} failed, continuing...", Colors.YELLOW)
                        
                self.print_color(f"\n📊 Completed: {success}/{len(plan['steps'])} steps", Colors.BOLD)
                
            if 'summary' in plan:
                self.print_color(f"\n📝 {plan['summary']}", Colors.GREEN)
                
        except Exception as e:
            self.print_color(f"❌ Execution error: {e}", Colors.RED)
            import traceback
            traceback.print_exc()

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 backend.py \"your request\" [initial_directory]")
        sys.exit(1)
        
    user_request = sys.argv[1]
    initial_dir = sys.argv[2] if len(sys.argv) > 2 else None
    
    assistant = AIAssistant(initial_dir)
    
    try:
        assistant.process_request(user_request)
    except KeyboardInterrupt:
        assistant.print_color("\n🛑 Cancelled", Colors.YELLOW)
        sys.exit(130)
    except Exception as e:
        assistant.print_color(f"❌ Error: {e}", Colors.RED)
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()