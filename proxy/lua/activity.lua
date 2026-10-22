-- Last real (human) request through this proxy.
--
-- Hosting platforms want to stop or remove instances nobody uses. The access
-- log cannot answer that on its own: it is truncated at a size limit, and
-- monitoring hits every instance around the clock. So the proxy keeps one
-- small file with the time of the last request that looks like a person:
--
--   /var/proxy_exchange/last_activity   (host: $HOST_RUN_DIR/proxy_exchange)
--
-- `odoo last-activity` reads it on the host. The file is rewritten at most
-- once per WRITE_INTERVAL seconds across all workers, so busy instances do
-- not pay a file write per request.

local _M = {}

_M.PATH = "/var/proxy_exchange/last_activity"
_M.WRITE_INTERVAL = 60

-- Requests that run on their own while nobody looks: health checks, the
-- open-tab bus, the dashboard's auto refresh, nginx internals.
local IGNORED_PATHS = {
    "^/web/health",
    "^/websocket",
    "^/longpolling",
    "^/bus/",
    "^/system/",
    "^/stub_status",
    "^/favicon",
    "^/web/webclient/version_info",
}

-- Monitoring, scripts, crawlers and test browsers. Matched lowercase as plain
-- substrings.
local IGNORED_AGENTS = {
    "python-requests",
    "python-urllib",
    "aiohttp",
    "curl/",
    "wget/",
    "go-http-client",
    "gatus",
    "zabbix",
    "prometheus",
    "blackbox",
    "uptime",
    "kube-probe",
    "node-fetch",
    "axios",
    "undici",
    "headlesschrome",
    "bot",
    "crawler",
    "spider",
}

local IGNORED_METHODS = {
    HEAD = true,
    OPTIONS = true,
}

-- Pure decision, no ngx access, so it can be tested outside openresty.
function _M.is_activity(method, uri, user_agent)
    if IGNORED_METHODS[method or ""] then
        return false
    end
    uri = uri or ""
    for _, pattern in ipairs(IGNORED_PATHS) do
        if uri:find(pattern) then
            return false
        end
    end
    local ua = (user_agent or ""):lower()
    if ua == "" or ua == "node" then
        return false
    end
    for _, needle in ipairs(IGNORED_AGENTS) do
        if ua:find(needle, 1, true) then
            return false
        end
    end
    return true
end

local function json_string(value)
    value = tostring(value or "")
    value = value:gsub('[%c"\\]', function(c)
        if c == '"' then
            return '\\"'
        elseif c == "\\" then
            return "\\\\"
        end
        return string.format("\\u%04x", c:byte())
    end)
    return '"' .. value .. '"'
end

function _M.render(epoch, host, uri)
    return "{"
        .. '"time":' .. json_string(os.date("!%Y-%m-%dT%H:%M:%SZ", epoch)) .. ","
        .. '"epoch":' .. string.format("%d", epoch) .. ","
        .. '"host":' .. json_string(host) .. ","
        .. '"uri":' .. json_string(uri)
        .. "}\n"
end

-- Written next to the target and renamed, so a reader never sees half a file.
function _M.write(path, content)
    local tmp = path .. ".tmp"
    local f, err = io.open(tmp, "w")
    if not f then
        return nil, err
    end
    f:write(content)
    f:close()
    return os.rename(tmp, path)
end

-- Called from log_by_lua (nginx.conf, http level).
function _M.record()
    local var = ngx.var
    if not _M.is_activity(var.request_method, var.uri, var.http_user_agent) then
        return
    end
    local dict = ngx.shared.activity
    if not dict then
        return
    end
    -- add() only succeeds when the key is absent: one writer per interval.
    if not dict:add("written", true, _M.WRITE_INTERVAL) then
        return
    end
    local ok, err = _M.write(_M.PATH, _M.render(ngx.time(), var.host, var.uri))
    if not ok then
        ngx.log(ngx.ERR, "last_activity: cannot write ", _M.PATH, ": ", err)
    end
end

return _M
