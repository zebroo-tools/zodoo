-- Access gate for the monitoring dashboard (/system/) and the browser editor
-- (/code/). openresty glue; every decision lives in gatecore.lua.
--
-- Wired from dashboard.conf / coding.conf via:
--     rewrite_by_lua_block { require("dashauth").gate(os.getenv("DASHBOARD_PASSWORD")) }
--     rewrite_by_lua_block { require("dashauth").gate(os.getenv("CODING_PASSWORD"), "/code", "zodoo code") }
-- The rewrite phase runs before access_by_lua_file (backend resolution), so an
-- unauthenticated request never reaches the backend.
--
-- Ways in (each area has its own cookie, session store key and secrets, so
-- /system and /code never open each other):
--   POST <area>/__sso    ticket from zCloud, key GATE_SSO_KEY_<AREA>
--   POST <area>/__auth   shared password (fallback, also the old zCloud form)
--   GET|POST <area>/__logout   ends the session
--
-- Settings (env): GATE_SSO_KEY_SYSTEM, GATE_SSO_KEY_CODE (empty -> SSO off for
-- that area), GATE_COOKIE_SECURE, GATE_SESSION_MAX_S, GATE_SESSION_IDLE_S,
-- GATE_LIMIT_PER_MIN, GATE_LIMIT_BURST, DEVMODE. Without password and key the area is open in DEVMODE and answers
-- 503 everywhere else (fail closed).
--
-- Sessions live in lua_shared_dict gate_sessions, used ticket ids in gate_jti
-- (see proxy/gate.http.conf). A proxy restart ends all sessions.
--
-- Transition: the generated compose file mounts THIS file straight from
-- ~/.odoo/images. After `odoo setup upgrade` without `odoo reload` +
-- `odoo build proxy` the proxy still runs the old nginx.conf (no shared dicts)
-- and gatecore.lua is not mounted yet. Then legacy_gate() keeps the previous
-- password-only behaviour instead of answering 500.

local has_core, core = pcall(require, "gatecore")

local _M = {}

local DEFAULT_BASE = "/system"

local function esc(s)
    return (s:gsub("[&<>\"]", {
        ["&"] = "&amp;", ["<"] = "&lt;", [">"] = "&gt;", ['"'] = "&quot;",
    }))
end

local function page(titel, msg, auth_path)
    local err = ""
    if msg then
        err = '<p class="err">' .. esc(msg) .. "</p>"
    end
    local form = ""
    if auth_path then
        form = [[<input type="password" name="password" placeholder="Passwort" autofocus>
<button type="submit">Anmelden</button>]]
    end
    return [[<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>]] .. esc(titel) .. [[</title><style>
body{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;
background:#111217;font-family:system-ui,-apple-system,sans-serif;color:#d8d9da}
form{background:#1f2128;padding:34px 30px;border-radius:10px;width:280px;
box-shadow:0 8px 30px rgba(0,0,0,.55);text-align:center}
h1{font-size:16px;font-weight:600;margin:0 0 20px}
input{width:100%;box-sizing:border-box;padding:11px 12px;margin-bottom:14px;
border:1px solid #383a42;border-radius:6px;background:#0f1015;color:#fff;font-size:14px}
input:focus{outline:none;border-color:#f60}
button{width:100%;padding:11px;border:0;border-radius:6px;background:#f60;
color:#fff;font-size:14px;font-weight:600;cursor:pointer}
button:hover{background:#ff7a1a}
.err{color:#ff6b6b;font-size:13px;margin:0 0 12px}
</style></head><body><form method="POST" action="]] .. (auth_path or "")
        .. [[">
<h1>&#128274; ]] .. esc(titel) .. [[</h1>]] .. err .. form
        .. [[</form></body></html>]]
end

-- Tells zCloud (a GET on <area>/__sso) that this proxy has the new gate and
-- whether a ticket key is configured for the area; zCloud then sends a ticket
-- instead of the old password form. Carries no secret.
local gate_header

local function respond(status, titel, msg, auth_path, cookies)
    ngx.status = status
    if gate_header then
        ngx.header["X-Zodoo-Gate"] = gate_header
    end
    ngx.header.content_type = "text/html; charset=utf-8"
    ngx.header["Cache-Control"] = "no-store"
    if cookies then
        ngx.header["Set-Cookie"] = cookies
    end
    ngx.say(page(titel, msg, auth_path))
    return ngx.exit(status)
end

local function redirect(location, cookies)
    ngx.header["Cache-Control"] = "no-store"
    if cookies then
        ngx.header["Set-Cookie"] = cookies
    end
    return ngx.redirect(location, ngx.HTTP_MOVED_TEMPORARILY)
end

local function new_sid()
    local random = require("resty.random")
    local bytes = random.bytes(32, true)
    if not bytes then
        bytes = random.bytes(32) -- weaker source still beats failing hard
    end
    return core.b64url_encode(bytes)
end

-- Cookies that end the old gate's cookie (Path=/, HMAC of the password) and,
-- optionally, the current session cookie of this area.
local function clear_cookies(a, secure)
    return {
        core.set_cookie(a.cookie, "", a.cookie_path, 0, secure),
        core.set_cookie(a.cookie, "", "/", 0, secure),
    }
end

-- Failed attempts at __auth/__sso: GATE_LIMIT_PER_MIN (10) per minute,
-- burst GATE_LIMIT_BURST (5), per client
-- address (see gate.http.conf for why this is not limit_req). Only failures
-- count: behind the router all users share one address, and a team opening
-- the dashboard from zCloud must not lock itself out.
local limiter
local function get_limiter()
    if limiter == nil then
        limiter = false
        local ok, limit_req = pcall(require, "resty.limit.req")
        if ok and ngx.shared.gate_limit then
            local per_min = tonumber(os.getenv("GATE_LIMIT_PER_MIN") or "")
                or 10
            local burst = tonumber(os.getenv("GATE_LIMIT_BURST") or "") or 5
            limiter = limit_req.new("gate_limit", per_min / 60, burst)
        end
    end
    return limiter
end

-- commit=false: only ask whether the budget is used up; true: count a failure.
local function throttle(commit)
    local l = get_limiter()
    if not l then
        return false -- proxy not rebuilt yet; nothing to count with
    end
    local delay, err = l:incoming(ngx.var.binary_remote_addr, commit)
    return not delay and err == "rejected"
end

local function start_session(a, cfg, sub, way, fp)
    local dict = ngx.shared.gate_sessions
    local sid = new_sid()
    local ok, err = core.session_create(
        dict, a.base, sid, sub, way, fp, ngx.time(), cfg.idle
    )
    if not ok then
        ngx.log(ngx.ERR, "gate: cannot store session: ", err)
        return ngx.exit(ngx.HTTP_INTERNAL_SERVER_ERROR)
    end
    return redirect(a.base .. "/", {
        core.set_cookie(a.cookie, sid, a.cookie_path, cfg.max_age, cfg.secure),
        -- drop a leftover cookie of the previous gate (Path=/)
        core.set_cookie(a.cookie, "", "/", 0, cfg.secure),
    })
end

-- Previous gate, unchanged: cookie = HMAC-SHA1 of the password with a fixed
-- secret, Path=/, 30 days. Only used until the proxy is rebuilt.
local function legacy_gate(password, base_path, titel)
    if not password or password == "" then
        return
    end
    local base = base_path or DEFAULT_BASE
    local name = base:gsub("^/", ""):gsub("[^%w_]", "_")
    local cookie, auth_path = "zodoo_gate_" .. name, base .. "/__auth"
    titel = titel or ("zodoo " .. base:gsub("^/", ""))
    local expected = ngx.encode_base64(
        ngx.hmac_sha1("zodoo-dashboard-gate", cookie .. ":" .. password)
    )
    local function eq(x, y)
        if type(x) ~= "string" or #x ~= #y then
            return false
        end
        local bit, diff = require("bit"), 0
        for i = 1, #x do
            diff = bit.bor(diff, bit.bxor(x:byte(i), y:byte(i)))
        end
        return diff == 0
    end
    if ngx.var.uri == auth_path then
        if ngx.var.request_method ~= "POST" then
            return ngx.redirect(base)
        end
        ngx.req.read_body()
        local args = ngx.req.get_post_args() or {}
        if eq(args.password, password) then
            ngx.header["Set-Cookie"] = cookie .. "=" .. expected
                .. "; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000"
            return ngx.redirect(base)
        end
        return respond(401, titel, "Falsches Passwort", auth_path)
    end
    if eq(ngx.var["cookie_" .. cookie], expected) then
        return
    end
    return respond(401, titel, nil, auth_path)
end

function _M.gate(password, base_path, titel)
    if not has_core or not ngx.shared.gate_sessions or not ngx.shared.gate_jti
    then
        ngx.log(ngx.WARN, "gate: proxy not rebuilt yet (no gatecore/shared ",
            "dicts), using the old password gate")
        return legacy_gate(password, base_path, titel)
    end
    local a = core.area(base_path or DEFAULT_BASE)
    titel = titel or ("zodoo " .. a.base:gsub("^/", ""))
    local cfg = core.settings(os.getenv)
    local key_env = "GATE_SSO_KEY_" .. a.base:gsub("^/", ""):upper()
        :gsub("[^%w]", "_")
    local key = os.getenv(key_env)
    if key == "" then
        key = nil
    end
    if password == "" then
        password = nil
    end
    gate_header = key and "2; sso" or "2"

    if not password and not key then
        if cfg.devmode then
            return -- DEVMODE without secrets: open, as before
        end
        -- Fail closed: a real instance without any credential must not
        -- serve a shell or the monitoring to everyone.
        ngx.log(ngx.WARN, "gate ", a.base, ": no password and no SSO key")
        return respond(503, titel, "Zugang nicht eingerichtet.")
    end

    local fps = {
        sso = key and core.fingerprint(key) or nil,
        password = password and core.fingerprint(password) or nil,
    }
    local auth_path = password and a.auth or nil
    local uri = ngx.var.uri
    local method = ngx.var.request_method
    local dict = ngx.shared.gate_sessions

    -- Logout: GET is fine (Grafana can only render links); a forged logout
    -- is harmless.
    if uri == a.logout then
        for _, sid in ipairs(core.cookie_values(ngx.var.http_cookie, a.cookie)) do
            core.session_delete(dict, a.base, sid)
        end
        return redirect(a.base .. "/", clear_cookies(a, cfg.secure))
    end

    if (uri == a.sso or uri == a.auth) and method == "POST" and throttle(false)
    then
        ngx.header["Retry-After"] = "60"
        return respond(429, titel, "Zu viele Versuche. Bitte kurz warten.")
    end

    if uri == a.sso then
        if method ~= "POST" then
            -- A ticket in the URL would end up in logs, history and Referer.
            return respond(401, titel,
                "Link ungültig. Bitte erneut aus zCloud öffnen.", auth_path)
        end
        ngx.req.read_body()
        local args = ngx.req.get_post_args(4) or {}
        local ticket = args.ticket
        if type(ticket) == "table" then
            ticket = nil
        end
        local now = ngx.time()
        local claims, why = core.verify_ticket(
            ticket, key, ngx.var.host, a.base, now
        )
        if claims then
            local ok, err = core.consume_jti(ngx.shared.gate_jti, claims, now)
            if not ok then
                claims, why = nil, err
            end
        end
        if not claims then
            ngx.log(ngx.WARN, "gate ", a.base, ": ticket refused: ", why)
            throttle(true)
            return respond(401, titel,
                "Link abgelaufen oder ungültig. Bitte erneut aus zCloud öffnen.",
                auth_path)
        end
        return start_session(a, cfg, claims.sub, "sso", fps.sso)
    end

    if uri == a.auth then
        if method ~= "POST" then
            return redirect(a.base .. "/")
        end
        if not password then
            return respond(401, titel,
                "Anmeldung nur über zCloud möglich.", nil)
        end
        ngx.req.read_body()
        local args = ngx.req.get_post_args(4) or {}
        if core.const_eq(args.password, password) then
            return start_session(a, cfg, "", "password", fps.password)
        end
        throttle(true)
        return respond(401, titel, "Falsches Passwort", auth_path)
    end

    -- Valid session?
    local now = ngx.time()
    for _, sid in ipairs(core.cookie_values(ngx.var.http_cookie, a.cookie)) do
        if core.session_check(dict, a.base, sid, fps, now, cfg.max_age, cfg.idle)
        then
            return
        end
    end

    if password then
        return respond(401, titel, nil, auth_path)
    end
    return respond(401, titel,
        "Bitte über zCloud öffnen.", nil)
end

return _M
