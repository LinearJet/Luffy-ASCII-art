# Enhanced AI Fish Function with execution fixes and memory
function ai
    if not set -q argv
        echo "Usage: ai <your query>"
        return 1
    end

    set -l query_string "$argv"
    set -l current_dir "$PWD"
    set -l backend_script ~/.config/fish/scripts/ai_backend.py
    
    set -l temp_dir "$HOME/.cache"
    if not test -d "$temp_dir"
        mkdir -p "$temp_dir"
    end
    set -l ai_output_file "$temp_dir/ai_last_output"
    set -l ai_context_file "$temp_dir/ai_deep_context"

    if not test -f "$backend_script"
        echo -e "\033[0;31m❌ AI backend not found. Run setup again.\033[0m"
        return 1
    end

    echo -n -e "\033[0;36m🤖 Analyzing environment...\033[0m"
    
    # Comprehensive context gathering
    set -l deep_context ""
    set -l dir_structure (find . -maxdepth 2 -type f -exec ls -la {} \; 2>/dev/null | head -30)
    set -l git_repos (find . -maxdepth 2 -name ".git" -type d 2>/dev/null | sed 's|/.git||')
    set -l executables (find . -maxdepth 1 -type f -executable 2>/dev/null)
    set -l source_files (find . -maxdepth 1 \( -name "*.c" -o -name "*.cpp" -o -name "*.py" -o -name "*.sh" -o -name "*.js" -o -name "*.go" -o -name "*.rs" \) 2>/dev/null)
    
    # System info
    set -l compilers ""
    for compiler in gcc g++ clang python3 node rustc go javac
        if command -v $compiler >/dev/null 2>&1
            set compilers "$compilers $compiler"
        end
    end
    
    set -l recent_history (history --max=3 | string join "\n")
    set -l context_data ""
    if test -f "$ai_output_file"
        set context_data (cat "$ai_output_file")
    end
    
    set deep_context "DIR_STRUCTURE: $dir_structure
GIT_REPOS: $git_repos
EXECUTABLES: $executables
SOURCE_FILES: $source_files
COMPILERS: $compilers
RECENT_HISTORY: $recent_history
PWD: $PWD"
    
    printf '%s\n%s' "$deep_context" "$context_data" > "$ai_context_file"

    echo -e "\r\033[K\033[0;36m🤖 Processing...\033[0m"
    
    set -l response_json
    set -l stderr_tmp (mktemp -p "$temp_dir")

    if command python3 "$backend_script" --query "$query_string" --cwd "$current_dir" --context-file "$ai_context_file" 2> "$stderr_tmp" | read -lz response_json
        # Success
    else
        echo -e "\r\033[K\033[0;31m❌ AI Backend Error\033[0m"
        cat "$stderr_tmp"
        rm -f "$stderr_tmp"
        return 1
    end
    rm -f "$stderr_tmp"

    echo -e "\r\033[K"

    if test -z "$response_json"
        echo -e "\033[0;31m❌ Empty response\033[0m"
        return 1
    end

    # Parse and execute
    set -l num_actions 0
    if command -v jq >/dev/null 2>&1
        set num_actions (echo "$response_json" | jq 'length')
    else
        echo -e "\033[0;33m⚠️ Install jq: pkg install jq\033[0m"
        return 1
    end

    if test "$num_actions" -eq 0
       echo -e "\033[0;96m🤖 No actions needed\033[0m"
       return 0
    end

    # Execute actions with better handling
    set -l action_outputs ""
    
    for i in (seq 0 (math $num_actions - 1))
        set -l action (echo "$response_json" | jq -r ".[$i]")
        set -l type (echo "$action" | jq -r ".type")
        set -l content (echo "$action" | jq -r ".content // \"\"")
        set -l command (echo "$action" | jq -r ".command // \"\"")
        set -l path (echo "$action" | jq -r ".path // \"\"")
        set -l auto_exec (echo "$action" | jq -r ".auto_execute // true")
        
        switch "$type"
            case "text"
                echo -e "\033[0;96m🤖 $content\033[0m"
                set action_outputs "$action_outputs\nAI: $content"
                
            case "error"
                echo -e "\033[0;31m❌ $content\033[0m"
                set action_outputs "$action_outputs\nERROR: $content"
                
            case "cmd"
                if test -n "$command"
                    echo -e "\033[0;93m💻 $command\033[0m"
                    
                    # Safety check
                    if string match -qr "(rm -rf|format|shutdown|reboot|dd if=)" "$command"
                        read -P "⚠️ Execute potentially dangerous command? [y/N] " -l confirm
                        if not string match -qi "y" "$confirm"
                            echo -e "\033[0;90m⏭️ Skipped dangerous command\033[0m"
                            continue
                        end
                    else if test "$auto_exec" = "false"
                        read -P "Execute? [Y/n] " -l confirm
                        if string match -qi "n" "$confirm"
                            echo -e "\033[0;90m⏭️ Skipped by user\033[0m"
                            continue
                        end
                    end
                    
                    # Enhanced execution with proper output handling
                    set -l output_file (mktemp -p "$temp_dir")
                    set -l timing_start (date +%s)
                    
                    # Use fish for better execution
                    begin
                        eval "$command"
                    end 2>&1 | tee "$output_file"
                    set -l status_code $status
                    
                    set -l timing_end (date +%s)
                    set -l duration (math $timing_end - $timing_start)
                    set -l cmd_output (cat "$output_file")
                    rm -f "$output_file"
                    
                    if test $status_code -eq 0
                        echo -e "\033[0;32m✅ Success ($duration s)\033[0m"
                    else
                        echo -e "\033[0;31m❌ Failed: exit $status_code ($duration s)\033[0m"
                    end
                    
                    set action_outputs "$action_outputs\nCMD: $command\nSTATUS: $status_code\nOUTPUT: $cmd_output"
                end
                
            case "run"
                # New enhanced run action for GUI/interactive programs
                set -l executable (echo "$action" | jq -r ".executable")
                set -l args (echo "$action" | jq -r ".args // \"\"")
                set -l background (echo "$action" | jq -r ".background // false")
                
                if test -n "$executable"
                    echo -e "\033[0;95m🚀 Running: $executable $args\033[0m"
                    
                    if test "$background" = "true"
                        # Run in background for GUI apps
                        nohup $executable $args > /dev/null 2>&1 &
                        set -l pid $last_pid
                        echo -e "\033[0;32m✅ Started in background (PID: $pid)\033[0m"
                        set action_outputs "$action_outputs\nBACKGROUND_RUN: $executable (PID: $pid)"
                    else
                        # Run interactively for terminal programs
                        if test -x "$executable"
                            $executable $args
                            set -l status_code $status
                            if test $status_code -eq 0
                                echo -e "\033[0;32m✅ Program completed\033[0m"
                            else
                                echo -e "\033[0;31m❌ Program exited with code $status_code\033[0m"
                            end
                            set action_outputs "$action_outputs\nRUN: $executable\nSTATUS: $status_code"
                        else
                            echo -e "\033[0;31m❌ File not executable: $executable\033[0m"
                        end
                    end
                end
                
            case "compile_run"
                set -l source_file (echo "$action" | jq -r ".source")
                set -l compiler_cmd (echo "$action" | jq -r ".compile_command")
                set -l run_cmd (echo "$action" | jq -r ".run_command // \"\"")
                
                if test -n "$source_file" && test -f "$source_file"
                    echo -e "\033[0;94m🔨 Compiling $source_file\033[0m"
                    echo -e "\033[0;93m💻 $compiler_cmd\033[0m"
                    
                    eval "$compiler_cmd"
                    set -l compile_status $status
                    
                    if test $compile_status -eq 0
                        echo -e "\033[0;32m✅ Compilation successful\033[0m"
                        
                        if test -n "$run_cmd"
                            echo -e "\033[0;95m🚀 Running compiled program\033[0m"
                            read -P "Run? [Y/n] " -l run_confirm
                            if not string match -qi "n" "$run_confirm"
                                eval "$run_cmd"
                                set -l run_status $status
                                set action_outputs "$action_outputs\nCOMPILE_RUN: $source_file\nRUN_STATUS: $run_status"
                            end
                        end
                    else
                        echo -e "\033[0;31m❌ Compilation failed\033[0m"
                    end
                end
                
            case "file"
                if test -n "$path"
                    echo -e "\033[0;94m📄 Writing: $path\033[0m"
                    
                    set -l parent_dir (dirname "$path")
                    if test "$parent_dir" != "." && not test -d "$parent_dir"
                        mkdir -p "$parent_dir" 2>/dev/null
                    end
                    
                    set -l decoded_content (printf '%b' "$content")
                    
                    if printf '%s' "$decoded_content" > "$path" 2>/dev/null
                        set -l file_size (wc -c < "$path" 2>/dev/null || echo "unknown")
                        echo -e "\033[0;32m✅ File written ($file_size bytes)\033[0m"
                        set action_outputs "$action_outputs\nFILE_WRITTEN: $path"
                    else
                        echo -e "\033[0;31m❌ Failed to write file\033[0m"
                    end
                end
                
            case "install"
                set -l packages (echo "$action" | jq -r ".packages[]" 2>/dev/null)
                set -l manager (echo "$action" | jq -r ".manager // \"pkg\"")
                
                if test -n "$packages"
                    echo -e "\033[0;92m📦 Installing with $manager: $packages\033[0m"
                    for package in $packages
                        echo -e "\033[0;90m  Installing $package...\033[0m"
                        eval "$manager install -y $package"
                        if test $status -eq 0
                            echo -e "\033[0;32m  ✅ $package installed\033[0m"
                        else
                            echo -e "\033[0;31m  ❌ $package failed\033[0m"
                        end
                    end
                end
        end
    end
    
    # Save context for next call
    set -l full_context "$action_outputs\nTIMESTAMP: "(date)
    printf '%s' "$full_context" > "$ai_output_file"
    printf '%s\n\nLAST_RESULTS:\n%s' "$deep_context" "$full_context" > "$ai_context_file"
end

# Memory function
function airem --description "Store information for AI to remember"
    set -l temp_dir "$HOME/.cache"
    set -l memory_file "$temp_dir/ai_memory.txt"
    
    if not set -q argv
        echo "Usage: airem <information to remember>"
        if test -f "$memory_file"
            echo -e "\n\033[0;96mCurrent memories:\033[0m"
            cat "$memory_file"
        end
        return 1
    end
    
    set -l memory_entry "[$(date)] $argv"
    echo "$memory_entry" >> "$memory_file"
    echo -e "\033[0;32m💾 Remembered: $argv\033[0m"
end

# Shortcuts
function aia --description "AI with auto-execute"
    ai --auto "$argv"
end

function aif --description "AI fix last command"
    set -l last_cmd (history --max=1)
    ai "fix this failed command: $last_cmd"
end

function aic --description "AI with full context"
    set -l temp_dir "$HOME/.cache"
    set -l memory_file "$temp_dir/ai_memory.txt"
    set -l memory_context ""
    if test -f "$memory_file"
        set memory_context "MEMORIES: $(cat $memory_file)"
    end
    ai "$argv. $memory_context"
end

function aix --description "AI execute programs"
    ai "execute/run programs in current directory: $argv"
end

function aih --description "AI help"
    echo -e "\033[0;96m🤖 AI Assistant Help\033[0m"
    echo -e "\033[0;93mai <query>\033[0m     - Ask AI with context"
    echo -e "\033[0;93maia <query>\033[0m    - AI with auto-execute"
    echo -e "\033[0;93maif\033[0m           - Fix last failed command"
    echo -e "\033[0;93maic <query>\033[0m   - AI with memory context"
    echo -e "\033[0;93maix <query>\033[0m   - AI execute programs"
    echo -e "\033[0;93mairem <info>\033[0m  - Store info for AI memory"
    echo -e "\033[0;93maih\033[0m           - Show this help"
end