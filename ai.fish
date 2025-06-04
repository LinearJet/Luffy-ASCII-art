# Save as ~/.config/fish/functions/ai.fish

function ai
    if not set -q argv
        echo "Usage: ai <your query>"
        return 1
    end

    set -l query_string "$argv"
    set -l current_dir "$PWD"
    set -l backend_script (status dirname)"/../scripts/ai_backend.py"

    if not test -f "$backend_script"
        echo -e "\033[0;31m❌ AI backend not found at '$backend_script'\033[0m"
        return 1
    end

    echo -n -e "\033[0;36m🤖 Processing...\033[0m"
    
    # Get recent command history and output
    set -l context_data ""
    if test -f /tmp/ai_last_output
        set context_data (cat /tmp/ai_last_output)
    end
    
    set -l response_json
    set -l stderr_tmp (mktemp)

    if command python3 "$backend_script" --query "$query_string" --cwd "$current_dir" --context-data "$context_data" 2> "$stderr_tmp" | read -lz response_json
        # Success
    else
        echo -e "\r\033[K\033[0;31m❌ AI Backend Error\033[0m"
        cat "$stderr_tmp"
        rm -f "$stderr_tmp"
        return 1
    end
    rm -f "$stderr_tmp"

    echo -e "\r\033[K" # Clear processing line

    if test -z "$response_json"
        echo -e "\033[0;31m❌ Empty response\033[0m"
        return 1
    end

    # Parse and execute actions
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

    # Execute actions
    set -l last_output ""
    set -l action_outputs ""
    
    for i in (seq 0 (math $num_actions - 1))
        set -l action (echo "$response_json" | jq -r ".[$i]")
        set -l type (echo "$action" | jq -r ".type")
        set -l content (echo "$action" | jq -r ".content // \"\"")
        set -l command (echo "$action" | jq -r ".command // \"\"")
        set -l path (echo "$action" | jq -r ".path // \"\"")
        set -l auto_exec (echo "$action" | jq -r ".auto_execute // true")
        set -l use_output (echo "$action" | jq -r ".use_output_for_next // false")
        
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
                    
                    # Check for dangerous commands
                    if string match -qr "(rm -rf|format|shutdown|reboot)" "$command"
                        read -P "⚠️ Execute dangerous command? [y/N] " -l confirm
                        if not string match -qi "y" "$confirm"
                            echo -e "\033[0;90m⏭️ Skipped\033[0m"
                            set action_outputs "$action_outputs\nCMD SKIPPED: $command"
                            continue
                        end
                    else if test "$auto_exec" = "false"
                        read -P "Execute? [y/N] " -l confirm
                        if not string match -qi "y" "$confirm"
                            echo -e "\033[0;90m⏭️ Skipped\033[0m"
                            set action_outputs "$action_outputs\nCMD SKIPPED: $command"
                            continue
                        end
                    end
                    
                    # Execute and capture output
                    set -l output_file (mktemp)
                    set -l cmd_start_time (date +%s)
                    
                    eval "$command" 2>&1 | tee "$output_file"
                    set -l status_code $status
                    set -l cmd_output (cat "$output_file")
                    
                    if test "$use_output" = "true"
                        set last_output "$cmd_output"
                    end
                    
                    # Store output for next AI call
                    set action_outputs "$action_outputs\nCMD: $command\nOUTPUT: $cmd_output\nEXIT_CODE: $status_code"
                    
                    rm -f "$output_file"
                    
                    if test $status_code -eq 0
                        echo -e "\033[0;32m✅ Success\033[0m"
                    else
                        echo -e "\033[0;31m❌ Failed (exit $status_code)\033[0m"
                        _ai_fix_error "$command" $status_code "$cmd_output"
                    end
                end
                
            case "file"
                if test -n "$path"
                    echo -e "\033[0;94m📄 Writing: $path\033[0m"
                    
                    # Create parent directory
                    set -l parent_dir (dirname "$path")
                    if test "$parent_dir" != "." && not test -d "$parent_dir"
                        if mkdir -p "$parent_dir" 2>/dev/null
                            echo -e "\033[0;90m📁 Created directory: $parent_dir\033[0m"
                        else
                            echo -e "\033[0;33m⚠️ Creating directory with sudo...\033[0m"
                            if sudo mkdir -p "$parent_dir" 2>/dev/null
                                echo -e "\033[0;90m📁 Created directory with sudo: $parent_dir\033[0m"
                            else
                                echo -e "\033[0;31m❌ Failed to create directory\033[0m"
                                set action_outputs "$action_outputs\nFILE_WRITE_FAILED: $path (directory creation failed)"
                                continue
                            end
                        end
                    end
                    
                    # Decode content properly (handle newlines)
                    set -l decoded_content (echo "$content" | sed 's/\\n/\n/g' | sed 's/\\t/\t/g')
                    
                    # Write file with proper error handling
                    if printf '%s' "$decoded_content" > "$path" 2>/dev/null
                        echo -e "\033[0;32m✅ File written successfully\033[0m"
                        set -l file_size (wc -c < "$path" 2>/dev/null || echo "unknown")
                        set action_outputs "$action_outputs\nFILE_WRITTEN: $path ($file_size bytes)"
                    else
                        echo -e "\033[0;33m⚠️ Permission denied, trying with sudo...\033[0m"
                        if printf '%s' "$decoded_content" | sudo tee "$path" >/dev/null 2>/dev/null
                            echo -e "\033[0;32m✅ File written with elevated permissions\033[0m"
                            set -l file_size (wc -c < "$path" 2>/dev/null || echo "unknown")
                            set action_outputs "$action_outputs\nFILE_WRITTEN_SUDO: $path ($file_size bytes)"
                        else
                            echo -e "\033[0;31m❌ Failed to write file\033[0m"
                            set action_outputs "$action_outputs\nFILE_WRITE_FAILED: $path (permission error)"
                        end
                    end
                end
                
            case "config"
                set -l expanded_path (string replace '~' "$HOME" "$path")
                echo -e "\033[0;95m⚙️ Configuring: $expanded_path\033[0m"
                
                # Create backup
                if test -f "$expanded_path"
                    set -l backup_path "$expanded_path.backup."(date +%s)
                    if cp "$expanded_path" "$backup_path" 2>/dev/null
                        echo -e "\033[0;90m💾 Backup created: $backup_path\033[0m"
                    end
                end
                
                # Create parent directory
                set -l parent_dir (dirname "$expanded_path")
                mkdir -p "$parent_dir" 2>/dev/null
                
                # Append to config
                set -l append_content (echo "$action" | jq -r ".append // \"\"")
                if test -n "$append_content"
                    set -l decoded_append (echo "$append_content" | sed 's/\\n/\n/g')
                    
                    if printf '%s\n' "$decoded_append" >> "$expanded_path" 2>/dev/null
                        echo -e "\033[0;32m✅ Configuration updated\033[0m"
                        set action_outputs "$action_outputs\nCONFIG_UPDATED: $expanded_path"
                    else
                        echo -e "\033[0;31m❌ Failed to update config (permission denied)\033[0m"
                        set action_outputs "$action_outputs\nCONFIG_FAILED: $expanded_path (permission error)"
                    end
                end
                
            case "install"
                set -l packages (echo "$action" | jq -r ".packages[]" 2>/dev/null)
                set -l manager (echo "$action" | jq -r ".manager // \"pkg\"")
                
                if test -n "$packages"
                    echo -e "\033[0;92m📦 Installing: $packages\033[0m"
                    set -l install_output ""
                    for package in $packages
                        set -l pkg_output_file (mktemp)
                        eval "$manager install -y $package" 2>&1 | tee "$pkg_output_file"
                        set -l pkg_status $status
                        set -l pkg_out (cat "$pkg_output_file")
                        rm -f "$pkg_output_file"
                        
                        set install_output "$install_output\nPACKAGE: $package\nSTATUS: $pkg_status\nOUTPUT: $pkg_out"
                    end
                    set action_outputs "$action_outputs\nINSTALL_RESULTS: $install_output"
                end
        end
    end
    
    # Save all action outputs for next AI call
    printf '%s' "$action_outputs" > /tmp/ai_last_output
end

# Quick error fix function with output context
function _ai_fix_error
    set -l cmd "$argv[1]"
    set -l code "$argv[2]"
    set -l output "$argv[3]"
    
    echo -e "\033[0;93m🔧 Analyzing error...\033[0m"
    set -l fix_query "Command '$cmd' failed with exit code $code. Output: $output. Provide quick fix."
    
    set -l fix (python3 (status dirname)"/../scripts/ai_backend.py" --query "$fix_query" --cwd "$PWD" --fix-mode 2>/dev/null)
    if test -n "$fix"
        echo -e "\033[0;93m💡 Suggestion: $fix\033[0m"
    end
end

# Auto-completion function
function _ai_complete
    set -l current_token (commandline -t)
    set -l suggestions_file /tmp/ai_suggestions
    
    # Generate suggestions based on current context
    python3 (status dirname)"/../scripts/ai_backend.py" --query "suggest completions for: $current_token" --cwd "$PWD" --complete-mode > "$suggestions_file" 2>/dev/null
    
    if test -f "$suggestions_file"
        cat "$suggestions_file"
    end
end

# Bind Ctrl+Space for AI completions
bind \c\  '_ai_complete'

# Shortcuts
function aia --description "AI with auto-execute"
    ai --auto "$argv"
end

function aif --description "AI fix last command"
    set -l last_cmd (history --max=1)
    ai "fix command: $last_cmd"
end

function aic --description "AI with current context"
    set -l context_info ""
    if test -f /tmp/ai_last_output
        set context_info "Previous context: "(cat /tmp/ai_last_output | tail -20)
    end
    ai "$argv. Context: $context_info"
end