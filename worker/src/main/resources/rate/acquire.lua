-- 적응형 토큰 버킷: permit 1개 획득 시도.
--
-- 이 스크립트가 존재하는 이유: 버킷은 워커 프로세스가 아니라 "모델의 provider quota"에 속한
-- 공유 상태다. 워커가 둘 이상이면 read-modify-write가 인터리브되어 합계가 provider 한도를
-- 넘는다. Lua 한 덩어리로 원자화한다 (ADR-017).
--
-- KEYS[1] = rate:bucket:{model}
-- ARGV[1] = initial_rpm, ARGV[2] = min_rpm, ARGV[3] = max_rpm, ARGV[4] = burst_seconds
-- 반환   = { granted(0|1), wait_ms, rpm, tokens*100 }
--
-- 시각은 클라이언트가 아니라 redis TIME(서버 클럭)을 쓴다 — 워커 간 클럭 스큐 배제.

local key      = KEYS[1]
local init_rpm = tonumber(ARGV[1])
local min_rpm  = tonumber(ARGV[2])
local max_rpm  = tonumber(ARGV[3])
local burst_s  = tonumber(ARGV[4])

local t   = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)

local st  = redis.call('HMGET', key, 'rpm', 'tokens', 'ts', 'cooldown_until')
local rpm = tonumber(st[1]) or init_rpm
rpm = math.max(min_rpm, math.min(max_rpm, rpm))   -- 설정이 바뀌었으면 범위로 되끌어온다

local cap    = math.max(1, rpm * burst_s / 60)
local tokens = tonumber(st[2])
if tokens == nil then tokens = cap end            -- 최초 관측: 가득 찬 상태에서 시작
local ts             = tonumber(st[3]) or now
local cooldown_until = tonumber(st[4]) or 0

-- 보충. 쿨다운 중에는 ts가 미래(=쿨다운 종료 시각)라 elapsed <= 0 → 토큰이 쌓이지 않는다.
local elapsed = now - ts
if elapsed > 0 then
  tokens = math.min(cap, tokens + elapsed * rpm / 60000.0)
  ts = now
end

local granted = 0
local wait_ms = 0
if now < cooldown_until then
  wait_ms = cooldown_until - now                  -- provider가 알려준 재시도 시각까지 하드 대기
elseif tokens >= 1 then
  tokens = tokens - 1
  granted = 1
else
  wait_ms = math.ceil((1 - tokens) * 60000 / rpm)
end

redis.call('HSET', key, 'rpm', rpm, 'tokens', tokens, 'ts', ts, 'cooldown_until', cooldown_until)
redis.call('EXPIRE', key, 604800)                 -- 7일: 안 쓰는 모델의 상태는 자연 소멸

return { granted, wait_ms, rpm, math.floor(tokens * 100) }
