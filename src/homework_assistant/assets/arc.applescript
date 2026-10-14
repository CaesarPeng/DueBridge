property allowedDomains : {}
use framework "Foundation"
use scripting additions

on schoolURL(raw)
    set parts to current application's NSURLComponents's componentsWithString:raw
    if parts is missing value then return false
    if (parts's |scheme|() as text) is not "https" then return false
    if (parts's |user|()) is not missing value or (parts's |password|()) is not missing value then return false
    if (parts's |port|()) is not missing value then
        if (parts's |port|() as integer) is not 443 then return false
    end if
    set hostName to parts's |host|() as text
    repeat with pattern in allowedDomains
        set domainName to pattern as text
        if domainName starts with "*." then
            if hostName ends with (text 2 thru -1 of domainName) then return true
        else if hostName is domainName then
            return true
        end if
    end repeat
    return false
end schoolURL

on run argv
    set actionName to item 1 of argv
    set savedDelimiters to AppleScript's text item delimiters
    set AppleScript's text item delimiters to ","
    set allowedDomains to text items of (item 2 of argv)
    set AppleScript's text item delimiters to savedDelimiters
    tell application "Arc"
        if actionName is "list" then
            set rows to {}
            repeat with w in windows
                if not incognito of w then
                    repeat with t in tabs of w
                        set address to URL of t
                        if my schoolURL(address) then set end of rows to {id of w, id of t, address}
                    end repeat
                end if
            end repeat
            set jsonData to current application's NSJSONSerialization's dataWithJSONObject:rows options:0 |error|:(missing value)
            return (current application's NSString's alloc()'s initWithData:jsonData encoding:4) as text
        else if actionName is "open" then
            set address to item 3 of argv
            if not my schoolURL(address) then error "Unsupported course source"
            set w to missing value
            repeat with candidate in windows
                if not incognito of candidate then
                    set w to candidate
                    exit repeat
                end if
            end repeat
            if w is missing value then set w to make new window with properties {mode:"normal"}
            set t to make new tab at end of tabs of w with properties {URL:address}
            select t
            if minimizable of w and minimized of w then set minimized of w to false
            activate
            return id of t
        else if actionName is "execute" or actionName is "focus" then
            set windowID to item 3 of argv
            set tabID to item 4 of argv
            if actionName is "execute" then set codeText to read POSIX file (item 5 of argv) as «class utf8»
            repeat with w in windows
                if id of w is windowID and not incognito of w then
                    repeat with t in tabs of w
                        if id of t is tabID then
                            if not my schoolURL(URL of t) then error "Course tab changed"
                            if actionName is "focus" then
                                select t
                                if minimizable of w and minimized of w then set minimized of w to false
                                activate
                                return "ready"
                            end if
                            return execute t javascript codeText
                        end if
                    end repeat
                end if
            end repeat
            error "Course tab unavailable"
        end if
    end tell
    error "Unknown collector action"
end run
