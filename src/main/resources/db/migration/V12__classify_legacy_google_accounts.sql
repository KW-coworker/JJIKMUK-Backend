-- Accounts created by the previous Google auto-signup implementation used
-- this deterministic nickname prefix and an unreachable random password.
UPDATE users
SET auth_provider = 'GOOGLE',
    profile_completed = FALSE
WHERE auth_provider = 'LOCAL'
  AND nickname LIKE '구글유저_%';
