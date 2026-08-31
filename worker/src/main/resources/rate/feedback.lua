-- AIMD 피드백: 429(RATE_LIMITED) = 곱셈 감소, 연속 성공 N회 = 덧셈 증가.
--
-- 감소를 크게(x0.5) 증가를 작게(+1) 하는 비대칭이 핵심이다. provider 한도를 넘는 상태는
-- 즉시 벗어나야 하고(429는 실패한 호출 = 낭비), 한도 탐색은 천천히 해야 재진입 발진이 없다.
--
-- KEYS[1] = rate:bucket:{model}
-- ARGV[1] = op ('throttle' | 'success')
-- ARGV[2] = initial_rpm, ARGV[3] = min_rpm, ARGV[4] = max_rpm
-- ARGV[5] = decrease_factor, ARGV[6] = successes_to_increase, ARGV[7] = increase_step
-- ARGV[8] = retry_after_ms (provider 힌트, 없으면 0)
-- 반환   = { rpm, cooldown_ms, streak }

local key      = KEYS[1]
local op       = ARGV[1]
local init_rpm = tonumber(ARGV[2])
local min_rpm  = tonumber(ARGV[3])
local max_rpm  = tonumber(ARGV[4])
local factor   = tonumber(ARGV[5])
local need     = tonumber(ARGV[6])
local step     = tonumber(ARGV[7])
local hint_ms  = tonumber(ARGV[8])

local t   = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)

local st  = redis.call('HMGET', key, 'rpm', 'streak')
local rpm = tonumber(st[1]) or init_rpm
rpm = math.max(min_rpm, math.min(max_rpm, rpm))
local streak = tonumber(st[2]) or 0

local cooldown = 0
if op == 'throttle' then
  rpm = math.max(min_rpm, math.floor(rpm * factor))
  streak = 0
  -- 힌트가 있으면 그 값을, 없으면 새 rate에서 토큰 1개가 차는 시간을 쿨다운으로 쓴다.
  cooldown = hint_ms
  if cooldown <= 0 then cooldown = math.ceil(60000 / rpm) end
  -- tokens=0, ts=쿨다운 종료 시각 → 쿨다운 동안 보충이 일어나지 않는다 (acquire.lua의 elapsed<=0)
  redis.call('HSET', key, 'rpm', rpm, 'tokens', 0, 'ts', now + cooldown,
             'cooldown_until', now + cooldown, 'streak', 0)
else
  streak = streak + 1
  if streak >= need then
    rpm = math.min(max_rpm, rpm + step)
    streak = 0
  end
  redis.call('HSET', key, 'rpm', rpm, 'streak', streak)
end
redis.call('EXPIRE', key, 604800)

return { rpm, cooldown, streak }
