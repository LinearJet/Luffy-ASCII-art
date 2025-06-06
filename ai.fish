#!/usr/bin/env fish

# AI Terminal Assistant for Termux
# Place in ~/.config/fish/functions/ai.fish

function ai --description "AI-powered terminal assistant for Termux"
    if test (count $argv) -eq 0
        echo "🤖 AI Terminal Assistant"
        echo "Usage: ai \"your request here\""
        echo "Examples:"
        echo "  ai \"create flask app and run it\""
        echo "  ai \"search and install python packages for ML\""
        echo "  ai \"create spinning donut animation in C\""
        echo "  ai \"scrape weather data from website\""
        echo "  ai \"setup git repo and push to github\""
        return 1
    end

    set prompt (string join " " $argv)
    set backend_path ~/.config/fish/scripts/backend.py
    
    if not test -f "$backend_path"
        echo "❌ Error: backend.py not found at $backend_path"
        echo "Place backend.py in ~/.config/fish/scripts/"
        return 1
    end

    echo -n "🤖 "
    set_color cyan; echo -n "AI is analyzing"; set_color normal
    for i in (seq 3); sleep 0.2; echo -n "."; end; echo ""

    set_color yellow; echo "🔍 Request: \"$prompt\""; set_color normal; echo ""

    # Pass current directory to backend
    python3 "$backend_path" "$prompt" (pwd) 2>&1
    set exit_code $status

    echo ""
    if test $exit_code -eq 0
        set_color green; echo "✅ Task completed!"
    else
        set_color red; echo "❌ Task failed"
    end
    set_color normal
    return $exit_code
end

# Auto-completion
function __ai_complete
    echo "create flask app"
    echo "install python packages"
    echo "search packages for"
    echo "create spinning donut in C"
    echo "scrape data from website"
    echo "setup git repository"
    echo "commit and push changes"
    echo "create react app"
    echo "run animation"
    echo "fix compilation errors"
    echo "execute donut"
    echo "run calculator"
    echo "test program"
end

complete -c ai -f -a "(__ai_complete)"
bind \ca 'commandline -i "ai \"\""; commandline -C -1'

# Memory function
function airem --description "AI memory and preferences"
    set config_file ~/.config/fish/ai_config.json
    mkdir -p (dirname $config_file)
    
    if not test -f "$config_file"
        echo '{"prefs": {}, "shortcuts": {}}' > "$config_file"
    end
    
    switch $argv[1]
        case "set"
            if test (count $argv) -lt 3; echo "Usage: airem set <key> <value>"; return 1; end
            python3 -c "
import json
with open('$config_file', 'r') as f: c = json.load(f)
c['prefs']['$argv[2]'] = '$argv[3]'
with open('$config_file', 'w') as f: json.dump(c, f)
print('✅ Set $argv[2] = $argv[3]')
"
        case "get"
            if test (count $argv) -lt 2; echo "Usage: airem get <key>"; return 1; end
            python3 -c "
import json
with open('$config_file', 'r') as f: c = json.load(f)
print(c['prefs'].get('$argv[2]', 'Not set'))
"
        case "list"
            python3 -c "
import json
with open('$config_file', 'r') as f: c = json.load(f)
print('🧠 Preferences:')
for k, v in c.get('prefs', {}).items(): print(f'  {k}: {v}')
print('⚡ Shortcuts:')
for k, v in c.get('shortcuts', {}).items(): print(f'  {k}: {v}')
"
        case "*"
            echo "Usage: airem [set|get|list] <args>"
    end
end