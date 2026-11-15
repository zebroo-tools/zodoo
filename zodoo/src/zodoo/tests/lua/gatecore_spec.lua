-- Unit spec for proxy/lua/gatecore.lua, run by test_dashauth.py with plain
-- luajit. Prints "ok <name>" or "FAIL <name>: <detail>" per case.
-- arg[1] = directory of gatecore.lua, arg[2] = ticket signed by Python
-- (key "py-key", aud "a.example.com", area "/system", iat 1000, exp 1060).

package.path = arg[1] .. "/?.lua;" .. package.path
local g = require("gatecore")

local function check(name, cond, detail)
    if cond then
        print("ok " .. name)
    else
        print("FAIL " .. name .. ": " .. tostring(detail))
    end
end

-- Fake of ngx.shared.DICT with a settable clock.
local clock = 0
local function dict()
    local d = { data = {} }
    function d:get(k)
        local e = self.data[k]
        if e and (not e.exp or e.exp > clock) then
            return e.v
        end
        self.data[k] = nil
    end
    function d:set(k, v, ttl)
        self.data[k] = { v = v, exp = (ttl and ttl > 0) and clock + ttl or nil }
        return true
    end
    function d:add(k, v, ttl)
        if self:get(k) ~= nil then
            return false, "exists"
        end
        return self:set(k, v, ttl)
    end
    function d:delete(k)
        self.data[k] = nil
    end
    return d
end

local KEY = "k-system-0123456789abcdef"
local function ticket(over)
    local t = {
        aud = "a.example.com", area = "/system", sub = "user-1",
        iat = 1000, exp = 1060, jti = "jti-0123456789abcdef",
    }
    for k, v in pairs(over or {}) do
        t[k] = v
    end
    return g.make_ticket(over and over.key or KEY, t)
end
local function verify(tk, now, host, area)
    return g.verify_ticket(tk, KEY, host or "a.example.com",
        area or "/system", now or 1010)
end

-- ticket checks -----------------------------------------------------------
local c, why = verify(ticket())
check("valid ticket", c and c.sub == "user-1" and c.jti, why)

c, why = verify(ticket(), 1060 + g.CLOCK_SKEW + 1)
check("expired ticket", not c and why == "expired", why)

c, why = verify(ticket(), 1060 + g.CLOCK_SKEW)
check("within clock skew", c, why)

local tk = ticket()
local p, s = tk:match("^(.-)%.(.*)$")
local flipped = s:sub(1, -2) .. (s:sub(-1) == "A" and "B" or "A")
c, why = verify(p .. "." .. flipped)
check("tampered signature", not c and why == "bad signature", why)

local forged = g.b64url_encode(
    "1|a.example.com|/system|admin|1000|1060|jti-0123456789abcdef")
c, why = verify(forged .. "." .. s)
check("tampered payload", not c and why == "bad signature", why)

c, why = verify(ticket({ key = "other-key" }))
check("wrong key", not c and why == "bad signature", why)

c, why = verify(ticket({ aud = "b.example.com" }))
check("other instance (aud)", not c and why == "wrong audience", why)

c, why = verify(ticket(), nil, "A.Example.com")
check("aud case-insensitive", c, why)

c, why = verify(ticket({ area = "/code" }))
check("code ticket on /system", not c and why == "wrong area", why)

c, why = verify(ticket({ exp = 1000 + g.MAX_TICKET_LIFETIME + 1 }))
check("lifetime too long", not c and why == "lifetime too long", why)

c, why = verify(ticket({ iat = 1100, exp = 1150 }), 1000)
check("issued in the future", not c and why == "issued in the future", why)

c, why = verify(ticket({ jti = "short" }))
check("short jti", not c and why == "malformed", why)

for _, bad in ipairs({ "", "x", "a.b.c", "!!.??", nil }) do
    c, why = verify(bad)
    check("garbage ticket " .. tostring(bad), not c, why)
end

c, why = g.verify_ticket(ticket(), nil, "a.example.com", "/system", 1010)
check("no key -> sso disabled", not c and why == "sso disabled", why)

c, why = g.verify_ticket(arg[2], "py-key", "a.example.com", "/system", 1010)
check("ticket signed by python", c and c.sub == "py-user", why)

-- single use --------------------------------------------------------------
local jti = dict()
clock = 1010
c = verify(ticket())
check("first use", g.consume_jti(jti, c, 1010))
local ok, err = g.consume_jti(jti, verify(ticket()), 1010)
check("second use refused", not ok and err == "already used", err)
check("jti kept until expiry", jti:get("/system:jti-0123456789abcdef"))
local c2 = verify(ticket({ area = "/code" }), nil, nil, "/code")
check("same jti other area independent", g.consume_jti(jti, c2, 1010))

-- sessions ----------------------------------------------------------------
local sess = dict()
local fps = { sso = g.fingerprint(KEY), password = g.fingerprint("pw") }
local SID = string.rep("A", 43)
clock = 0
g.session_create(sess, "/system", SID, "user-1", "sso", fps.sso, 0, 100)
clock = 50
local r = g.session_check(sess, "/system", SID, fps, 50, 300, 100)
check("session valid", r and r.sub == "user-1" and r.way == "sso")

check("session not valid in other area",
    not g.session_check(sess, "/code", SID, fps, 50, 300, 100))

clock = 140 -- idle window was slid at t=50 -> lives until 150
r = g.session_check(sess, "/system", SID, fps, 140, 300, 100)
check("idle window slides", r)

clock = 260 -- last refresh at 140 + idle 100 = 240
r, why = g.session_check(sess, "/system", SID, fps, 260, 300, 100)
check("idle timeout", not r and why == "no session", why)

clock = 0
g.session_create(sess, "/system", SID, "user-1", "sso", fps.sso, 0, 100)
for t = 90, 290, 90 do
    clock = t
    g.session_check(sess, "/system", SID, fps, t, 300, 100)
end
clock = 301
r, why = g.session_check(sess, "/system", SID, fps, 301, 300, 100)
check("absolute timeout", not r and why == "expired", why)

clock = 0
g.session_create(sess, "/system", SID, "", "password", fps.password, 0, 100)
r, why = g.session_check(sess, "/system", SID,
    { password = g.fingerprint("new-pw") }, 10, 300, 100)
check("password change ends session", not r and why == "credential changed",
    why)

g.session_create(sess, "/system", SID, "u", "sso", fps.sso, 0, 100)
r, why = g.session_check(sess, "/system", SID, { password = fps.password },
    10, 300, 100)
check("key removed ends sso session", not r, why)

g.session_create(sess, "/system", SID, "u", "sso", fps.sso, 0, 100)
g.session_delete(sess, "/system", SID)
check("logout deletes", not g.session_check(sess, "/system", SID, fps, 1,
    300, 100))

check("short/odd sid refused",
    not g.session_check(sess, "/system", "abc", fps, 1, 300, 100)
    and not g.session_check(sess, "/system", string.rep("A", 40) .. "|x|",
        fps, 1, 300, 100))

-- cookies -----------------------------------------------------------------
local vals = g.cookie_values(
    "a=1; zodoo_gate_system=new; zodoo_gate_system_x=no; zodoo_gate_system=old",
    "zodoo_gate_system")
check("cookie values", #vals == 2 and vals[1] == "new" and vals[2] == "old",
    table.concat(vals, ","))
check("no cookie header", #g.cookie_values(nil, "x") == 0)

local ck = g.set_cookie("zodoo_gate_system", "sid", "/system/", 28800, true)
check("cookie attributes", ck:find("Path=/system/", 1, true)
    and ck:find("HttpOnly", 1, true) and ck:find("Secure", 1, true)
    and ck:find("SameSite=Lax", 1, true), ck)

local a = g.area("/code")
check("area paths", a.cookie == "zodoo_gate_code" and a.sso == "/code/__sso"
    and a.logout == "/code/__logout" and a.cookie_path == "/code/")

-- settings ----------------------------------------------------------------
local function env(t)
    return function(k)
        return t[k]
    end
end
check("secure by default", g.settings(env({})).secure == true)
check("not secure in devmode", g.settings(env({ DEVMODE = "1" })).secure
    == false)
check("secure forced in devmode",
    g.settings(env({ DEVMODE = "1", GATE_COOKIE_SECURE = "1" })).secure)
check("secure switched off",
    g.settings(env({ GATE_COOKIE_SECURE = "0" })).secure == false)
local st = g.settings(env({}))
check("default lifetimes", st.max_age == 28800 and st.idle == 7200)
