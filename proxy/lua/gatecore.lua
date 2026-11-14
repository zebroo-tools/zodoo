-- Decision logic of the access gate in front of /system/ and /code/.
--
-- Pure Lua (LuaJIT + its bundled "bit" module), no ngx.* -- so every rule can
-- be tested with a plain `luajit` (zodoo/src/zodoo/tests/test_dashauth.py).
-- dashauth.lua is the thin openresty glue around it.
--
-- Two ways in, one session afterwards:
--
--   * SSO ticket: zCloud checks its own session and the user's rights, then
--     signs a short-lived, single-use ticket for exactly one host and one
--     area. The browser POSTs it to <area>/__sso. Format:
--
--         base64url(payload) "." base64url(HMAC-SHA256(key, base64url(payload)))
--         payload = "1|<aud host>|<area>|<sub>|<iat>|<exp>|<jti>"
--
--     The key is per instance and per area (GATE_SSO_KEY_SYSTEM /
--     GATE_SSO_KEY_CODE) and never reaches a browser.
--   * Password fallback: the shared password of the area, POSTed to
--     <area>/__auth (unchanged form, so the old zCloud button keeps working).
--
-- Both create a random server-side session (shared dict) with an absolute and
-- an idle lifetime. The cookie only carries the session id.

local bit = require("bit")
local band, bor, bxor, bnot = bit.band, bit.bor, bit.bxor, bit.bnot
local rshift, lshift, ror, tobit = bit.rshift, bit.lshift, bit.ror, bit.tobit

local _M = {}

_M.CLOCK_SKEW = 30 -- seconds of tolerance for iat/exp between zCloud and us
_M.MAX_TICKET_LIFETIME = 300 -- refuse tickets that claim to live longer

---------------------------------------------------------------------------
-- SHA-256 / HMAC-SHA256
---------------------------------------------------------------------------

local K = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1,
    0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
    0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
    0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
    0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
    0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
    0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
    0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
    0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
}

local function u32be(n)
    return string.char(
        band(rshift(n, 24), 0xff),
        band(rshift(n, 16), 0xff),
        band(rshift(n, 8), 0xff),
        band(n, 0xff)
    )
end

function _M.sha256(msg)
    local len = #msg
    -- Padding: 0x80, zeros, 64-bit big-endian bit length (messages here are
    -- far below 2^32 bits, so the upper word is 0).
    local pad = 64 - ((len + 9) % 64)
    if pad == 64 then
        pad = 0
    end
    msg = msg .. "\128" .. string.rep("\0", pad) .. u32be(0)
        .. u32be(tobit(len * 8))

    local h0, h1, h2, h3 = 0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a
    local h4, h5, h6, h7 = 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19
    local w = {}
    for chunk = 1, #msg, 64 do
        for i = 0, 15 do
            local a, b, c, d = msg:byte(chunk + i * 4, chunk + i * 4 + 3)
            w[i] = bor(lshift(a, 24), lshift(b, 16), lshift(c, 8), d)
        end
        for i = 16, 63 do
            local x, y = w[i - 15], w[i - 2]
            local s0 = bxor(ror(x, 7), ror(x, 18), rshift(x, 3))
            local s1 = bxor(ror(y, 17), ror(y, 19), rshift(y, 10))
            w[i] = tobit(w[i - 16] + s0 + w[i - 7] + s1)
        end
        local a, b, c, d, e, f, g, h = h0, h1, h2, h3, h4, h5, h6, h7
        for i = 0, 63 do
            local S1 = bxor(ror(e, 6), ror(e, 11), ror(e, 25))
            local ch = bxor(band(e, f), band(bnot(e), g))
            local t1 = tobit(h + S1 + ch + K[i + 1] + w[i])
            local S0 = bxor(ror(a, 2), ror(a, 13), ror(a, 22))
            local maj = bxor(band(a, b), band(a, c), band(b, c))
            local t2 = tobit(S0 + maj)
            h, g, f, e = g, f, e, tobit(d + t1)
            d, c, b, a = c, b, a, tobit(t1 + t2)
        end
        h0, h1, h2, h3 = tobit(h0 + a), tobit(h1 + b), tobit(h2 + c),
            tobit(h3 + d)
        h4, h5, h6, h7 = tobit(h4 + e), tobit(h5 + f), tobit(h6 + g),
            tobit(h7 + h)
    end
    return u32be(h0) .. u32be(h1) .. u32be(h2) .. u32be(h3) .. u32be(h4)
        .. u32be(h5) .. u32be(h6) .. u32be(h7)
end

local function xor_pad(key, byte)
    local out = {}
    for i = 1, 64 do
        out[i] = string.char(bxor(key:byte(i) or 0, byte))
    end
    return table.concat(out)
end

function _M.hmac_sha256(key, msg)
    if #key > 64 then
        key = _M.sha256(key)
    end
    return _M.sha256(
        xor_pad(key, 0x5c) .. _M.sha256(xor_pad(key, 0x36) .. msg)
    )
end

function _M.hex(s)
    return (s:gsub(".", function(c)
        return string.format("%02x", c:byte())
    end))
end

---------------------------------------------------------------------------
-- base64url (no padding)
---------------------------------------------------------------------------

local B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
local B64_REV = {}
for i = 1, #B64 do
    B64_REV[B64:byte(i)] = i - 1
end

function _M.b64url_encode(s)
    local out = {}
    for i = 1, #s, 3 do
        local a, b, c = s:byte(i, i + 2)
        local n = lshift(a, 16) + lshift(b or 0, 8) + (c or 0)
        local chars = 2 + (b and 1 or 0) + (c and 1 or 0)
        for j = 1, chars do
            local idx = band(rshift(n, (4 - j) * 6), 63) + 1
            out[#out + 1] = B64:sub(idx, idx)
        end
    end
    return table.concat(out)
end

function _M.b64url_decode(s)
    if type(s) ~= "string" or #s % 4 == 1 then
        return nil
    end
    local out = {}
    for i = 1, #s, 4 do
        local n, cnt = 0, 0
        for j = i, math.min(i + 3, #s) do
            local v = B64_REV[s:byte(j)]
            if not v then
                return nil
            end
            n = n * 64 + v
            cnt = cnt + 1
        end
        n = n * 64 ^ (4 - cnt)
        local bytes = cnt - 1
        for j = 1, bytes do
            out[#out + 1] =
                string.char(band(rshift(n, (3 - j) * 8), 0xff))
        end
    end
    return table.concat(out)
end

---------------------------------------------------------------------------
-- helpers
---------------------------------------------------------------------------

-- Constant-time string comparison (no leak of length/prefix via timing).
function _M.const_eq(a, b)
    if type(a) ~= "string" or type(b) ~= "string" then
        return false
    end
    if #a ~= #b then
        return false
    end
    local diff = 0
    for i = 1, #a do
        diff = bor(diff, bxor(a:byte(i), b:byte(i)))
    end
    return diff == 0
end

local function split(s, sep)
    local out = {}
    for part in (s .. sep):gmatch("(.-)" .. sep:gsub("%p", "%%%0")) do
        out[#out + 1] = part
    end
    return out
end

-- Fingerprint of the credential a session was made with. Stored in the
-- session: change the password or rotate the key and the old sessions stop
-- working on the next request, without a proxy restart.
local fp_cache = {}
function _M.fingerprint(secret)
    local fp = fp_cache[secret]
    if not fp then
        fp = _M.hex(_M.sha256("zodoo-gate-fp:" .. secret)):sub(1, 16)
        fp_cache[secret] = fp
    end
    return fp
end

-- Area base path ("/system") -> cookie name and the special paths below it.
function _M.area(base)
    local name = base:gsub("^/", ""):gsub("[^%w_]", "_")
    return {
        base = base,
        cookie = "zodoo_gate_" .. name,
        cookie_path = base .. "/",
        auth = base .. "/__auth",
        sso = base .. "/__sso",
        logout = base .. "/__logout",
    }
end

---------------------------------------------------------------------------
-- tickets
---------------------------------------------------------------------------

-- Reference implementation of what zCloud signs (also used by the tests).
function _M.make_ticket(key, t)
    local payload = table.concat({
        "1", t.aud, t.area, t.sub, tostring(t.iat), tostring(t.exp), t.jti,
    }, "|")
    local p = _M.b64url_encode(payload)
    return p .. "." .. _M.b64url_encode(_M.hmac_sha256(key, p))
end

-- Returns claims table or nil, reason. Does NOT consume the jti; the caller
-- does that atomically (dict:add) so a ticket cannot be used twice even when
-- two workers see it at the same moment.
function _M.verify_ticket(ticket, key, host, area_base, now)
    if type(ticket) ~= "string" or ticket == "" or #ticket > 2048 then
        return nil, "missing"
    end
    if not key or key == "" then
        return nil, "sso disabled"
    end
    local p, sig = ticket:match("^([%w_-]+)%.([%w_-]+)$")
    if not p then
        return nil, "malformed"
    end
    local want = _M.b64url_encode(_M.hmac_sha256(key, p))
    if not _M.const_eq(sig, want) then
        return nil, "bad signature"
    end
    local payload = _M.b64url_decode(p)
    if not payload then
        return nil, "malformed"
    end
    local f = split(payload, "|")
    if #f ~= 7 or f[1] ~= "1" then
        return nil, "bad version"
    end
    local claims = {
        aud = f[2], area = f[3], sub = f[4],
        iat = tonumber(f[5]), exp = tonumber(f[6]), jti = f[7],
    }
    if not claims.iat or not claims.exp or #claims.jti < 16 then
        return nil, "malformed"
    end
    if claims.aud:lower() ~= (host or ""):lower() then
        return nil, "wrong audience"
    end
    if claims.area ~= area_base then
        return nil, "wrong area"
    end
    if claims.exp - claims.iat > _M.MAX_TICKET_LIFETIME then
        return nil, "lifetime too long"
    end
    if now > claims.exp + _M.CLOCK_SKEW then
        return nil, "expired"
    end
    if claims.iat > now + _M.CLOCK_SKEW then
        return nil, "issued in the future"
    end
    return claims
end

-- Atomically mark a ticket as used. jti_dict follows the ngx.shared.DICT API
-- (add fails when the key already exists).
function _M.consume_jti(jti_dict, claims, now)
    local ttl = math.max(1, claims.exp + _M.CLOCK_SKEW - now + 1)
    local ok, err = jti_dict:add(claims.area .. ":" .. claims.jti, true, ttl)
    if ok then
        return true
    end
    return nil, err == "exists" and "already used" or (err or "store failed")
end

---------------------------------------------------------------------------
-- sessions
---------------------------------------------------------------------------

-- value: "<sub>|<way>|<since>|<fp>"; dict TTL = idle lifetime, refreshed on
-- every request; the absolute lifetime is checked against <since>.
function _M.session_create(dict, area_base, sid, sub, way, fp, now, idle)
    local value = table.concat({ sub or "", way, tostring(now), fp }, "|")
    local ok, err = dict:set(area_base .. ":" .. sid, value, idle)
    if not ok then
        return nil, err or "store failed"
    end
    return true
end

-- fps: {sso = <fp of current key or nil>, password = <fp or nil>}
function _M.session_check(dict, area_base, sid, fps, now, max_age, idle)
    if type(sid) ~= "string" or not sid:match("^[%w_-]+$") or #sid < 32 then
        return nil, "no session"
    end
    local k = area_base .. ":" .. sid
    local value = dict:get(k)
    if not value then
        return nil, "no session"
    end
    local f = split(value, "|")
    local way, since, fp = f[2], tonumber(f[3]), f[4]
    if not since or now - since > max_age then
        dict:delete(k)
        return nil, "expired"
    end
    if not fps[way] or fps[way] ~= fp then
        dict:delete(k)
        return nil, "credential changed"
    end
    dict:set(k, value, idle) -- slide the idle window
    return { sub = f[1], way = way, since = since }
end

function _M.session_delete(dict, area_base, sid)
    if type(sid) == "string" and sid ~= "" then
        dict:delete(area_base .. ":" .. sid)
    end
end

-- All values of one cookie name from a raw Cookie header. An old cookie of
-- the same name with Path=/ (from the previous gate) may be sent alongside
-- the new one; every value is tried.
function _M.cookie_values(header, name)
    local out = {}
    if type(header) ~= "string" then
        return out
    end
    for pair in (header .. ";"):gmatch("%s*([^;]*);") do
        local k, v = pair:match("^([^=]+)=(.*)$")
        if k and k:match("^%s*(.-)%s*$") == name then
            out[#out + 1] = v:match("^%s*(.-)%s*$")
        end
    end
    return out
end

function _M.set_cookie(name, value, path, max_age, secure)
    local c = name .. "=" .. value .. "; Path=" .. path
        .. "; HttpOnly; SameSite=Lax; Max-Age=" .. tostring(max_age)
    if secure then
        c = c .. "; Secure"
    end
    return c
end

---------------------------------------------------------------------------
-- settings
---------------------------------------------------------------------------

local function truthy(v)
    v = (v or ""):lower()
    return v == "1" or v == "true" or v == "yes" or v == "on"
end

-- getenv: function(name) -> string|nil. Area-specific names are passed in.
function _M.settings(getenv)
    local devmode = getenv("DEVMODE") == "1"
    local secure = getenv("GATE_COOKIE_SECURE")
    local s = {
        devmode = devmode,
        -- TLS ends at the router in front of us, so $scheme is always http
        -- here and cannot decide this. Default: Secure, except in DEVMODE.
        secure = (secure == nil or secure == "") and not devmode
            or truthy(secure),
        max_age = tonumber(getenv("GATE_SESSION_MAX_S") or "") or 8 * 3600,
        idle = tonumber(getenv("GATE_SESSION_IDLE_S") or "") or 2 * 3600,
    }
    return s
end

return _M
